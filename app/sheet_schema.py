"""Versão e adaptação dos JSON de OCR das folhas MTG2.

``raw_extraction`` é uma transcrição do impresso e não é corrigida pelo
plano. ``sheet_data`` usa sempre o contrato canónico v2. Este módulo é a
única fronteira entre os dois, incluindo a leitura de payloads v1 já
existentes no SQLite.

A adaptação nunca modifica o dicionário recebido. Isto é importante porque
o mesmo objeto é serializado como prova do OCR e usado para construir a
versão editável.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .matching import similarity as sim
from .templates_spec import KanbanTemplate


SCHEMA_VERSION = 2
LAST_DURATION = "duracao"
LAST_LOT = "n_corte_lote"
LAST_FIELDS = (LAST_DURATION, LAST_LOT)

_LENGTH_SUFFIX = re.compile(
    r"^(?P<perfil>.+?)\s*[x×]\s*(?P<comp>\d[\d .]*(?:[,.]\d+)?)\s*(?:mm)?\s*$",
    re.IGNORECASE,
)
_DURATION = re.compile(
    r"^(?:\d{1,3}\s*(?:h|hr|hrs|m|min)|\d{1,3}\s*[:h]\s*\d{0,2})$",
    re.IGNORECASE,
)


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _clean(section: object, fields: tuple[str, ...]) -> dict[str, str | None]:
    source = section if isinstance(section, dict) else {}
    return {field: _text(source.get(field)) for field in fields}


def _fmt_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def split_profile_length(value: object) -> tuple[str | None, str | None]:
    """Produz uma interpretação candidata da célula TUBO.

    Não deve ser aplicada destrutivamente sem confirmação do plano: um perfil
    sólido ``60x300`` é uma geometria válida. O cross usa esta hipótese apenas
    para pontuar e só a materializa num match forte.
    """
    original = _text(value)
    if not original:
        return None, None
    match = _LENGTH_SUFFIX.match(original)
    if not match:
        return original, None
    length = sim.parse_number(match.group("comp"))
    profile = match.group("perfil").strip().rstrip("x× ")
    if length is None or length < 200 or not profile:
        return original, None
    return profile, _fmt_number(length)


def _last_kind(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    normalized = sim.compact(text)
    if normalized in {"DURACAO", "DURATION", "TEMPO"}:
        return LAST_DURATION
    if normalized in {
        "LOTE", "NCORTE", "NOCORTE", "NUMEROCORTE", "NCORTELOTE",
        "NOCORTELOTE", "NUMEROCORTELOTE",
    }:
        return LAST_LOT
    return None


def _classify_last_value(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    if _DURATION.fullmatch(compact):
        return LAST_DURATION
    # Os números de corte/lote reais são alfanuméricos (ex. M26P0127).
    # Um número nu é ambíguo: não se escolhe uma coluna por adivinhação.
    if any(ch.isalpha() for ch in compact) and any(ch.isdigit() for ch in compact):
        return LAST_LOT
    return None


def _resolve_last_column(raw: dict, rows: list[dict]) -> tuple[str | None, list[dict]]:
    warnings: list[dict] = []
    layout = raw.get("layout") if isinstance(raw.get("layout"), dict) else {}
    explicit = _last_kind(layout.get("ultima_coluna"))
    if explicit is None:
        explicit = _last_kind(raw.get("ultima_coluna"))

    values = [
        value for row in rows
        if (value := _text(
            row.get("ultima_coluna")
            or row.get("n_corte_lote")
            or row.get("lote")
            or row.get("duracao")
        )) is not None
    ]

    # Existe uma versão real do TPL121 em que DURAÇÃO está riscado e
    # N.º CORTE/LOTE foi escrito por cima. Se o OCR ainda devolver o título
    # impresso, os valores inequívocos impedem que M26P0127 seja gravado como
    # duração. Com mistura ou valor ambíguo não se adivinha: preserva-se a
    # célula genérica para decisão humana.
    if explicit == LAST_DURATION and values:
        classified = [_classify_last_value(value) for value in values]
        if all(kind == LAST_LOT for kind in classified):
            warnings.append({
                "code": "ultima_coluna_titulo_sobrescrito",
                "ocr_layout": LAST_DURATION,
                "inferred_layout": LAST_LOT,
            })
            return LAST_LOT, warnings
        # Um valor nu («20») é ambíguo, mas não contradiz um título DURAÇÃO
        # legível. Só um código de lote inequívoco tem força para pôr o título
        # em causa; mistura de lote/duração exige decisão humana.
        if any(kind == LAST_LOT for kind in classified):
            warnings.append({
                "code": "ultima_coluna_conflito_ambiguo",
                "ocr_layout": LAST_DURATION,
            })
            return None, warnings

    if explicit is not None:
        return explicit, warnings

    kinds: set[str] = set()
    ambiguous = False
    for row in rows:
        if _text(row.get("n_corte_lote")) or _text(row.get("lote")):
            kinds.add(LAST_LOT)
        if _text(row.get("duracao")) and not _text(row.get("ultima_coluna")):
            inferred = _classify_last_value(row.get("duracao"))
            if inferred:
                kinds.add(inferred)
        inferred = _classify_last_value(row.get("ultima_coluna"))
        if inferred:
            kinds.add(inferred)
        elif _text(row.get("ultima_coluna")):
            ambiguous = True
    if len(kinds) == 1 and not ambiguous:
        return next(iter(kinds)), warnings
    if len(kinds) > 1:
        warnings.append({"code": "ultima_coluna_mista"})
    else:
        warnings.append({"code": "ultima_coluna_desconhecida"})
    return None, warnings


def _canonical_serrote_row(row: dict) -> dict[str, str | None]:
    # v2 raw usa tubo/referencia; v1 e dados já canónicos usam
    # perfil/modelo. Preferir sempre a célula física quando existe.
    tube = row.get("tubo") if _text(row.get("tubo")) else row.get("perfil")
    # Sem projeção de comp_mm: o comprimento deixou de ser célula da folha.
    # Folhas antigas com comp_mm gravado mantêm o valor nos dados (a UI
    # ignora-o); o cruzamento usa o comprimento como evidência interna.
    return {
        "cliente": _text(row.get("cliente")),
        "ov": _text(row.get("ov")),
        "of": _text(row.get("of")),
        # TUBO é evidência conjunta. Mantém-se inteiro na projeção editável;
        # quem o canoniza é a substituição pelo valor do plano.
        "perfil": _text(tube),
        "modelo": _text(row.get("referencia")) or _text(row.get("modelo")),
        "qtd": _text(row.get("qtd")),
    }


def _qtd_total(row: dict, row_index: int, warnings: list[dict]) -> str | None:
    current = _text(row.get("qtd_total_mm"))
    qtd2 = _text(row.get("qtd2"))
    legacy_meters = _text(row.get("metros"))
    if current:
        return current
    if qtd2 and legacy_meters:
        a, b = sim.parse_number(qtd2), sim.parse_number(legacy_meters)
        if a is None or b is None or a != b:
            warnings.append({
                "code": "qtd_total_mm_conflito",
                "row_index": row_index,
                "qtd2": qtd2,
                "metros": legacy_meters,
            })
    return qtd2 or legacy_meters


def derived_length(qtd: object, total: object) -> str | None:
    """Comprimento por peça derivado do total Vanguard (qtd_total_mm / qtd).

    Nunca vira célula visual: serve apenas de evidência de pontuação/desempate
    no cross (referências irmãs que só diferem no corte)."""
    n_qtd, n_total = sim.parse_number(qtd), sim.parse_number(total)
    if n_qtd is None or n_total is None or n_qtd <= 0:
        return None
    length = n_total / n_qtd
    # Evita transformar valores de outra unidade numa medida absurda.
    if length < 250:
        return None
    return _fmt_number(length)


def _canonical_vanguard_row(
    row: dict,
    row_index: int,
    last_column: str | None,
    warnings: list[dict],
) -> dict[str, str | None]:
    total = _qtd_total(row, row_index, warnings)
    generic_last = _text(row.get("ultima_coluna"))

    out: dict[str, str | None] = {
        "cliente": _text(row.get("cliente")),
        "ov": _text(row.get("ov")),
        "of": _text(row.get("of")),
        "perfil": _text(row.get("perfil")),
        "modelo": _text(row.get("modelo")),
        "qtd": _text(row.get("qtd")),
        "qtd_total_mm": total,
    }
    if last_column == LAST_DURATION:
        out[LAST_DURATION] = generic_last or _text(row.get("duracao"))
    elif last_column == LAST_LOT:
        # Em v1 o valor vivia em ``duracao`` mesmo quando era M26P0127.
        out[LAST_LOT] = (
            generic_last or _text(row.get("n_corte_lote"))
            or _text(row.get("lote")) or _text(row.get("duracao"))
        )
    else:
        out["ultima_coluna"] = (
            generic_last or _text(row.get("n_corte_lote"))
            or _text(row.get("lote")) or _text(row.get("duracao"))
        )
    return out


def _copy_markers(raw: dict, out: dict) -> None:
    # Metadata operacional conhecida fica fora das secções e não deve cair
    # durante a projeção (a UI depende destas duas marcas).
    for key in ("_blank_page", "_ocr_error"):
        if key in raw:
            out[key] = raw[key]


def canonicalize_extraction(raw: dict | None, template: KanbanTemplate) -> dict:
    """Converte uma extração raw/v1 numa cópia canónica v2.

    A função é idempotente para ``sheet_data`` v2 e tolera payloads
    incompletos dos providers/fakes antigos.
    """
    source: dict[str, Any] = raw if isinstance(raw, dict) else {}
    rows_source = [row for row in (source.get("rows") or []) if isinstance(row, dict)]
    warnings: list[dict] = []

    out: dict[str, Any] = {
        "_schema_version": SCHEMA_VERSION,
        "header": _clean(source.get("header"), template.header_fields),
        "rows": [],
        "footer": _clean(source.get("footer"), template.footer_fields),
    }

    if template.name == "serrote_kanban":
        out["rows"] = [_canonical_serrote_row(row) for row in rows_source]
    elif template.name == "vanguard_kanban":
        last_column, last_warnings = _resolve_last_column(source, rows_source)
        warnings.extend(last_warnings)
        out["layout"] = {"ultima_coluna": last_column}
        out["rows"] = [
            _canonical_vanguard_row(row, i, last_column, warnings)
            for i, row in enumerate(rows_source)
        ]
    else:
        out["rows"] = [_clean(row, template.row_fields) for row in rows_source]

    if not out["rows"]:
        fields = template.display_fields(out)
        out["rows"] = [{field: None for field in fields}]
    if warnings:
        out["_canonical_warnings"] = warnings
    _copy_markers(source, out)
    return out


def is_v2(data: object) -> bool:
    return isinstance(data, dict) and data.get("_schema_version") == SCHEMA_VERSION


def raw_for_display(raw: dict | None, template: KanbanTemplate) -> dict:
    """Projeta raw legado para os cabeçalhos físicos v2, sem o modificar.

    Folhas antigas guardavam diretamente ``perfil/modelo/qtd2/metros``. Sem
    esta vista compatível, o separador «OCR cru» mostrava TUBO, REFERÊNCIA e a
    segunda QTD vazios apesar de os valores continuarem no JSON imutável.
    """
    source = raw if isinstance(raw, dict) else {}
    out = deepcopy(source)
    rows = [row for row in (source.get("rows") or []) if isinstance(row, dict)]
    if template.name == "serrote_kanban":
        out["rows"] = [{
            "cliente": _text(row.get("cliente")),
            "ov": _text(row.get("ov")),
            "of": _text(row.get("of")),
            "qtd": _text(row.get("qtd")),
            "tubo": _text(row.get("tubo")) or _text(row.get("perfil")),
            "referencia": (
                _text(row.get("referencia")) or _text(row.get("modelo"))
            ),
        } for row in rows]
    elif template.name == "vanguard_kanban":
        out["rows"] = [{
            "cliente": _text(row.get("cliente")),
            "ov": _text(row.get("ov")),
            "of": _text(row.get("of")),
            "modelo": _text(row.get("modelo")),
            "qtd": _text(row.get("qtd")),
            "qtd_total_mm": (
                _text(row.get("qtd_total_mm")) or _text(row.get("qtd2"))
                or _text(row.get("metros"))
            ),
            "ultima_coluna": (
                _text(row.get("ultima_coluna"))
                or _text(row.get("n_corte_lote")) or _text(row.get("lote"))
                or _text(row.get("duracao"))
            ),
        } for row in rows]
    return out
