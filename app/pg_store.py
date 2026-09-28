"""A ÚNICA porta de escrita para o Postgres.

Chamado exclusivamente no ato de validação humana: insere a folha validada e as
suas linhas em mes_kanban (append-only). Tudo o resto da app só lê do Postgres.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date

import psycopg

from .config import settings
from .matching import similarity as sim
from .production_facts import materialize_sheet
from .templates_spec import LEGACY_FIELD_ALIASES, KanbanTemplate, is_marked

APP_VERSION = "kanban-mes-mtg2 0.2.0"
SOURCE_APP = "kanban-mes-mtg2"
_SHEET_NUMBER_LOCK_KEY = 323417719602
_SHEET_NUMBER_INDEX = "validated_sheets_source_app_sheet_no_uidx"
_STORE_ATTEMPTS = 3

# campos da linha kanban → colunas de mes_kanban.production_records
# («perfil» é o tubo e «modelo» a referência — nomes canónicos do motor,
# rótulos do setor só na UI; qtd2/metros/duracao da Vanguard não têm coluna
# própria e seguem no extra jsonb, como qualquer campo fora deste mapa).
# `comp_mm` saiu do mapa (26/08): length_mm passou a levar o comprimento
# teórico do plano da linha ligada; um comp_mm manuscrito de folhas antigas
# segue no extra.
_FIELD_TO_COLUMN = {
    "of": "production_order",
    "ov": "sales_order",
    "cliente": "customer_name",
    "modelo": "model_ref",
    "perfil": "profile_type",
    "qtd": "quantity",
    "qtd_total_mm": "quantity_total_mm",
    "duracao": "duration_text",
    "n_corte_lote": "lot_ref",
    "perf_comp": "full_profile",
}
_NUMERIC_COLUMNS = {
    "quantity", "length_mm", "width_mm", "thickness_mm", "plan_quantity",
    "quantity_total_mm",
}
_BOOLEAN_COLUMNS = {"full_profile"}

# Colunas acrescentadas por migrações posteriores ao primeiro schema. A app
# sonda-as a cada validação em vez de as assumir: assim a ordem entre o deploy
# do código e a aplicação do SQL deixa de importar. Sem cache de propósito —
# a sonda é um SELECT ao information_schema por validação (raras), e a cache
# fixava para sempre o schema visto na primeira validação do processo.
_OPTIONAL_COLUMNS = ("profile_type", "full_profile", "plan_quantity",
                     "plan_length_mm", "line_meters", "meters_produced",
                     "quantity_total_mm", "duration_text", "plan_snapshot_id")


def _dsn() -> str:
    return os.environ.get("MES_PG_DSN") or settings.pg_dsn


# dd/mm/aaaa, dd-mm-aa, aaaa-mm-dd… — o que os operadores escrevem de facto
_DATE_DMY = re.compile(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$")
_DATE_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")


class InvalidSheetDate(ValueError):
    """Data manuscrita que não se consegue interpretar — o chamador decide
    como a devolver ao utilizador (422, não 500)."""


class SheetNumberConflict(RuntimeError):
    """O número público local já pertence a outro UID no PostgreSQL."""

    def __init__(self, sheet_no: object):
        self.sheet_no = sheet_no
        super().__init__(f"número público {sheet_no} já utilizado")


class SheetNumberingConfigurationError(RuntimeError):
    """O histórico não oferece o contrato necessário para numerar folhas."""


class SheetIdentityConflict(RuntimeError):
    """O UID já existe no histórico, mas não pertence a esta aplicação."""


@dataclass(frozen=True)
class StoredSheetResult:
    row_count: int
    sheet_no: int
    next_sheet_no: int
    already_stored: bool


def normalize_sheet_date(raw: object) -> str:
    """Data manuscrita → ISO (aaaa-mm-dd), SEMPRE dia/mês/ano à portuguesa.

    Antes ia crua para a coluna `date` e era o Postgres a adivinhar — com
    `DateStyle MDY`, «06/08/2026» ficou gravado como 8 de junho (aconteceu na
    primeira folha validada). Datas ambíguas cá dentro não existem: quem
    escreve 06/08 numa fábrica portuguesa quer dizer 6 de agosto.
    """
    text = str(raw or "").strip()
    m = _DATE_ISO.match(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DATE_DMY.match(text)
        if not m:
            raise InvalidSheetDate(text)
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
    try:
        return date(y, mo, d).isoformat()
    except ValueError as exc:
        raise InvalidSheetDate(text) from exc


def _columns_present(cur, table: str = "production_records") -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'mes_kanban' AND table_name = %s",
        (table,),
    )
    return {r[0] for r in cur.fetchall()}


def _store_stoppages(cur, sheet: dict, header: dict, filled: list,
                     sheet_date: str | None, operator: str,
                     operator_pernr: str | None = None) -> int:
    """Linhas do verso da folha (paragens) → mes_kanban.stoppage_records."""
    machine = str(header.get("setor_maquina") or "").strip() or None
    n = 0
    for i, row in filled:
        cur.execute(
            """
            INSERT INTO mes_kanban.stoppage_records
                (sheet_uid, row_index, sheet_date, machine, operator_name,
                 motivo, inicio, fim, duracao_horas, resolvido,
                 operator_pernr, validated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                sheet["uid"], i, sheet_date, machine,
                operator or "(desconhecido)",
                str(row.get("motivo") or "").strip() or None,
                str(row.get("inicio") or "").strip() or None,
                str(row.get("fim") or "").strip() or None,
                sim.parse_number(row.get("duracao")),
                str(row.get("resolvido") or "").strip() or None,
                operator_pernr,
            ),
        )
        n += 1
    return n


def _numbering_schema_ready(cur) -> bool:
    if not {"source_app", "sheet_no"}.issubset(
            _columns_present(cur, "validated_sheets")):
        return False
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname = 'mes_kanban' "
        "AND tablename = 'validated_sheets' AND indexname = %s",
        (_SHEET_NUMBER_INDEX,),
    )
    return cur.fetchone() is not None


def _next_number(cur, sheet_no: int, minimum_sheet_no: int) -> int:
    cur.execute(
        "SELECT COALESCE(MAX(sheet_no), 0) FROM mes_kanban.validated_sheets "
        "WHERE source_app = %s", (SOURCE_APP,),
    )
    return max(int(cur.fetchone()[0] or 0), sheet_no, minimum_sheet_no - 1) + 1


def _store_validated_sheet_once(sheet: dict, template: KanbanTemplate,
                                edit_count: int, actor: str,
                                minimum_sheet_no: int) -> StoredSheetResult:
    """Executa uma tentativa transacional de gravar a folha e as suas linhas.
    Lança em caso de erro — o chamador não deve marcar a folha como validada
    sem este INSERT ter sido confirmado."""
    data = sheet["sheet_data"] or {}
    header = data.get("header") or {}
    footer = data.get("footer") or {}
    cross = sheet.get("cross_check") or {}

    # Levanta InvalidSheetDate se a data não se interpretar — o chamador
    # transforma isso num 422 com mensagem, nunca num 500.
    sheet_date = normalize_sheet_date(header.get("data")) if str(header.get("data") or "").strip() else None
    operator = str(header.get("operador") or "").strip()
    # Identidade resolvida contra a lista de colaboradores (ver app/matching/operador.py).
    op_match = cross.get("operator") or {}
    operator_rule = op_match.get("rule") or None
    # Contrato v2: uma sugestão de identidade não pode chegar ao Postgres como
    # operador aceite. Para payloads v1, só as duas regras historicamente
    # inequívocas mantêm compatibilidade.
    operator_accepted = op_match.get("accepted")
    if operator_accepted is None:
        operator_accepted = operator_rule in ("exact", "token")
    operator_pernr = (op_match.get("pernr") or None) if operator_accepted else None
    # valor de folha (rodapé), desnormalizado para cada linha — é a única
    # coluna de horas no schema
    hours_worked = sim.parse_number(footer.get("horas_trabalhadas"))

    # linhas com conteúdo (pelo menos um campo preenchido)
    facts = materialize_sheet(sheet)
    filled = [(fact["row_index"], fact["parent_row"]) for fact in facts]

    with psycopg.connect(_dsn(), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            if not _numbering_schema_ready(cur):
                raise SheetNumberingConfigurationError(
                    "aplica a migração 017: faltam source_app, sheet_no ou o "
                    "índice único de numeração"
                )
            # Chave estável comum às instalações MTG2; o índice continua a
            # proteger contra processos antigos que não adquiram este lock.
            cur.execute("SELECT pg_advisory_xact_lock(%s)",
                        (_SHEET_NUMBER_LOCK_KEY,))
            cur.execute(
                "SELECT source_app, sheet_no FROM mes_kanban.validated_sheets "
                "WHERE sheet_uid = %s",
                (sheet["uid"],),
            )
            existing = cur.fetchone()
            if existing:
                # A folha JÁ está no Postgres (o INSERT anterior confirmou e o
                # que falhou foi marcar o staging): o commit é atómico, por
                # isso as linhas também lá estão — repetir daria colisão de PK
                # e um 500 permanente. Devolve-se o que existe.
                source_app, raw_sheet_no = existing
                if source_app != SOURCE_APP:
                    raise SheetIdentityConflict(
                        f"a folha {sheet['uid']} já existe no histórico com "
                        f"source_app={source_app!r}"
                    )
                try:
                    historic_sheet_no = int(raw_sheet_no)
                except (TypeError, ValueError) as exc:
                    raise SheetIdentityConflict(
                        f"a folha {sheet['uid']} existe no histórico sem número válido"
                    ) from exc
                if historic_sheet_no < 1:
                    raise SheetIdentityConflict(
                        f"a folha {sheet['uid']} existe no histórico sem número válido"
                    )
                cur.execute(
                    "SELECT count(*) FROM mes_kanban.production_records WHERE sheet_uid = %s",
                    (sheet["uid"],),
                )
                n_prod = cur.fetchone()[0]
                n = n_prod
                if not n_prod:
                    cur.execute(
                        "SELECT count(*) FROM mes_kanban.stoppage_records "
                        "WHERE sheet_uid = %s", (sheet["uid"],),
                    )
                    n = cur.fetchone()[0]
                return StoredSheetResult(
                    int(n), historic_sheet_no,
                    _next_number(cur, historic_sheet_no, minimum_sheet_no), True,
                )
            validated_present = _columns_present(cur, "validated_sheets")
            cur.execute(
                "SELECT COALESCE(MAX(sheet_no), 0) "
                "FROM mes_kanban.validated_sheets WHERE source_app = %s",
                (SOURCE_APP,),
            )
            historic_max = int(cur.fetchone()[0] or 0)
            try:
                proposed_no = int(sheet.get("sheet_no"))
            except (TypeError, ValueError):
                proposed_no = 0
            number_free = False
            if proposed_no > 0:
                cur.execute(
                    "SELECT 1 FROM mes_kanban.validated_sheets "
                    "WHERE source_app = %s AND sheet_no = %s",
                    (SOURCE_APP, proposed_no),
                )
                number_free = cur.fetchone() is None
            sheet_no = (proposed_no if number_free else
                        max(minimum_sheet_no, historic_max + 1, 1))
            next_sheet_no = max(
                historic_max, sheet_no, minimum_sheet_no - 1) + 1
            source_columns = [
                name for name in (
                    "source_filename", "source_page", "source_app", "sheet_no",
                    "plan_snapshot_id",
                )
                if name in validated_present
            ]
            validated_columns = (
                "sheet_uid, sheet_date, template_name, family, operator_name, "
                "operator_no, sector_machine, shift, image_sha256, "
                "raw_extraction, sheet_data, cross_check, edit_count, "
                "validated_by, app_version, operator_pernr, operator_match_rule"
                + "".join(f", {name}" for name in source_columns)
            )
            validated_values = (
                sheet["uid"], sheet_date, template.name, template.family,
                operator or "(desconhecido)",
                str(header.get("n_operador") or "") or None,
                str(header.get("setor_maquina") or "") or None,
                str(header.get("turno") or "") or None,
                sheet.get("image_sha256") or "",
                json.dumps(sheet.get("raw_extraction") or {}, ensure_ascii=False, default=str),
                json.dumps(data, ensure_ascii=False, default=str),
                json.dumps(cross, ensure_ascii=False, default=str),
                edit_count, actor, APP_VERSION,
                operator_pernr, operator_rule,
                *[(SOURCE_APP if name == "source_app" else
                   sheet_no if name == "sheet_no" else
                   cross.get("snapshot_id") if name == "plan_snapshot_id" else
                   sheet.get(name)) for name in source_columns],
            )
            cur.execute(
                f"INSERT INTO mes_kanban.validated_sheets ({validated_columns}) "
                f"VALUES ({', '.join(['%s'] * len(validated_values))})",
                validated_values,
            )
            if template.page_kind == "stoppages":
                n = _store_stoppages(cur, sheet, header, filled, sheet_date, operator,
                                     operator_pernr)
                conn.commit()
                return StoredSheetResult(
                    n, sheet_no, next_sheet_no, False)
            present = _columns_present(cur)
            optional = [c for c in _OPTIONAL_COLUMNS if c in present]
            sql = (
                "INSERT INTO mes_kanban.production_records "
                "(sheet_uid, row_index, sheet_date, family, operator_name, "
                " machine, production_order, sales_order, customer_name, "
                " model_ref, matched_plan_key, match_confidence, "
                " quantity, length_mm, width_mm, thickness_mm, lot_ref, "
                " scrap, hours_worked, extra, operator_pernr, validated_at"
                + "".join(f", {c}" for c in optional)
                + ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                  "%s, %s, %s, %s, %s, %s, %s, %s, %s, now()"
                + ", %s" * len(optional)
                + ") RETURNING id"
            )
            row_fields = set(template.display_fields(data))
            n = 0
            for fact in facts:
                i = fact["row_index"]
                row = fact["parent_row"]
                cr = fact["parent_cross"]
                cells = {c["field"]: c for c in cr.get("cells", [])}
                cols: dict[str, object] = {}
                extra: dict[str, object] = {"plan_identity": cr["plan_identity"]} if cr.get("plan_identity") else {}
                for f, value in row.items():
                    if str(f).startswith("_"):
                        continue
                    if value is None or str(value).strip() == "":
                        continue
                    # folhas lidas antes de a coluna mudar de nome
                    f = LEGACY_FIELD_ALIASES.get(f, f) if f not in row_fields else f
                    col = _FIELD_TO_COLUMN.get(f)
                    if col is None or (col in _OPTIONAL_COLUMNS and col not in present):
                        extra[f] = value
                    elif col in _BOOLEAN_COLUMNS:
                        cols[col] = is_marked(value)
                    elif col in _NUMERIC_COLUMNS:
                        cols[col] = sim.parse_number(value)
                    else:
                        cols.setdefault(col, str(value).strip())
                # Quantidade planeada da linha do plano que casou, para se poder
                # ver mais tarde porque é que uma quantidade foi assinalada.
                qtd_cell = cells.get("qtd") or {}
                if qtd_cell.get("plan_limit") is not None:
                    cols["plan_quantity"] = qtd_cell["plan_limit"]
                # Metros teóricos (qtd × comprimento do plano) e o total
                # manuscrito do rodapé — a base do controlo de desperdício.
                # length_mm é também o comprimento DO PLANO da linha ligada:
                # NULL sem match, nunca o manuscrito.
                cols["length_mm"] = cr.get("plan_length_mm")
                cols["plan_length_mm"] = cr.get("plan_length_mm")
                cols["line_meters"] = cr.get("line_meters")
                cols["meters_produced"] = sim.parse_number(
                    footer.get("metros_produzidos"))
                cols["plan_snapshot_id"] = cross.get("snapshot_id")
                plan_refs = fact["plan_refs"]
                # OF/OV como números puros, a convenção do planeamento —
                # mesmo quando o valor veio do plano (com prefixo)
                for ref_col in ("production_order", "sales_order"):
                    if cols.get(ref_col):
                        cols[ref_col] = sim.strip_ref_prefix(cols[ref_col])

                machine = row.get("maquina") or header.get("setor_maquina")
                cur.execute(
                    sql,
                    (
                        sheet["uid"], i, sheet_date, template.family,
                        operator or "(desconhecido)",
                        str(machine).strip() if machine else None,
                        cols.get("production_order"), cols.get("sales_order"),
                        cols.get("customer_name"), cols.get("model_ref"),
                        None if plan_refs else cr.get("matched_plan_key"), cr.get("p_correct"),
                        cols.get("quantity"), cols.get("length_mm"),
                        cols.get("width_mm"), cols.get("thickness_mm"),
                        cols.get("lot_ref"), cols.get("scrap"),
                        hours_worked,
                        json.dumps(extra, ensure_ascii=False, default=str) if extra else None,
                        operator_pernr,
                        *[cols.get(c) for c in optional],
                    ),
                )
                production_record_id = cur.fetchone()[0]
                child_present = _columns_present(cur, "production_record_plan_refs")
                if plan_refs and not child_present:
                    raise RuntimeError(
                        "Migração production_record_plan_refs em falta; "
                        "Perf. Comp. não pode ser validado sem proveniência."
                    )
                if plan_refs and child_present:
                    for ref in plan_refs:
                        cur.execute(
                            """
                            INSERT INTO mes_kanban.production_record_plan_refs
                                (production_record_id, sheet_uid, row_index,
                                 plan_snapshot_id, plan_key, component_ref,
                                 profile_type, length_mm, quantity_planned,
                                 quantity_made_before, remaining_before,
                                 overproduction_before, assumed_quantity,
                                 remaining_rule, extra)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                production_record_id, sheet["uid"], i,
                                ref.get("snapshot_id"), ref.get("plan_key"),
                                ref.get("component_ref"), ref.get("profile_type"),
                                ref.get("length_mm"), ref.get("quantity_planned"),
                                ref.get("quantity_made_before"),
                                ref.get("remaining_before"),
                                ref.get("overproduction_before"),
                                ref.get("assumed_quantity"),
                                ref.get("remaining_rule"),
                                json.dumps({"source": "perf_comp_x", "plan_identity": ref}, ensure_ascii=False, default=str),
                            ),
                        )
                n += 1
        conn.commit()
    return StoredSheetResult(n, sheet_no, next_sheet_no, False)


def store_validated_sheet(sheet: dict, template: KanbanTemplate,
                          edit_count: int, actor: str, *,
                          minimum_sheet_no: int = 1) -> StoredSheetResult:
    """Grava uma folha e atribui o número definitivo no mesmo commit."""
    try:
        minimum_sheet_no = max(1, int(minimum_sheet_no))
    except (TypeError, ValueError):
        minimum_sheet_no = 1
    last_error: psycopg.errors.UniqueViolation | None = None
    for attempt in range(_STORE_ATTEMPTS):
        try:
            return _store_validated_sheet_once(
                sheet, template, edit_count, actor, minimum_sheet_no)
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name not in {
                    _SHEET_NUMBER_INDEX, "validated_sheets_pkey"}:
                raise
            last_error = exc
            if attempt + 1 == _STORE_ATTEMPTS:
                break
    raise SheetNumberConflict(sheet.get("sheet_no")) from last_error
