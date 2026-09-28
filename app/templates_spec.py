"""Contratos das folhas kanban do setor de perfis (MTG2).

Há dois contratos deliberadamente distintos:

``raw_row_fields``
    As colunas impressas, pela ordem em que o OCR as encontra no papel. O
    TPL102, por exemplo, tem QTD antes de TUBO e escreve perfil + comprimento
    dentro dessa única célula.

``row_fields``
    O modelo canónico editável e cruzável. Serrote e Vanguard partilham
    Cliente/OV/OF/Perfil/Modelo/Qtd [un.]; os nomes internos continuam a ser
    os nomes estáveis do motor (``perfil``, ``modelo``, ``qtd``). O
    comprimento (``comp_mm``) é uma coluna própria nos TPL290–294; nos
    impressos anteriores continua como evidência interna. Os exports CPIS
    e BaseDados mantêm o comprimento teórico do plano.

Separar os contratos permite guardar o OCR cru sem fingir que «Tubo» e
«Perfil» são a mesma célula. A conversão vive em :mod:`app.sheet_schema`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class KanbanTemplate:
    name: str
    family: str                       # perfis
    label: str
    index_loader: str | None          # função em app.matching.loaders; None = sem cruzamento
    row_fields: tuple[str, ...]       # colunas canónicas/finais, na ordem da UI
    raw_row_fields: tuple[str, ...] | None = None  # colunas físicas, ordem do papel
    header_fields: tuple[str, ...] = ("operador", "n_operador", "setor_maquina", "data", "turno")
    footer_fields: tuple[str, ...] = ("horas_trabalhadas",)
    field_labels: dict[str, str] | None = None
    raw_field_labels: dict[str, str] | None = None
    turno_options: tuple[str, ...] = ("M", "R", "XM")
    # O TPL121 existe com duas últimas colunas alternativas. ``row_fields``
    # leva a variante por omissão para os call-sites antigos; a UI nova usa
    # ``display_fields`` e escolhe pela metadata da folha.
    dynamic_last_fields: tuple[str, ...] = ()
    document_code: str | None = None
    page_kind: str = "production"
    canonical_machine: str | None = None

    @property
    def ocr_row_fields(self) -> tuple[str, ...]:
        """Campos pedidos ao OCR (compatível com templates sem contrato raw)."""
        return self.raw_row_fields or self.row_fields

    def display_fields(self, data: dict | None = None, *, raw: bool = False) -> tuple[str, ...]:
        """Campos a mostrar para uma extração concreta.

        Quando o cabeçalho final do Vanguard não foi identificado ainda,
        conserva-se ``ultima_coluna`` e a revisão pode pedir ao humano que
        escolha a semântica, sem perder o valor lido.
        """
        if raw:
            return self.ocr_row_fields
        if not self.dynamic_last_fields:
            return self.row_fields
        layout = (data or {}).get("layout") or {}
        selected = layout.get("ultima_coluna")
        if selected not in self.dynamic_last_fields:
            selected = "ultima_coluna"
        return self.row_fields[:-1] + (selected,)

    def labels(self, *, raw: bool = False,
               data: dict | None = None) -> dict[str, str]:
        if raw:
            labels = dict(self.raw_field_labels or self.field_labels or {})
            selected = ((data or {}).get("layout") or {}).get("ultima_coluna")
            if selected in self.dynamic_last_fields:
                labels["ultima_coluna"] = (self.field_labels or {}).get(
                    selected, selected
                )
            return labels
        return self.field_labels or {}


SERROTE_KANBAN = KanbanTemplate(
    name="serrote_kanban",
    family="perfis",
    label="Serrote — Kanban de produção (TPL102)",
    index_loader="load_perfis_index",
    # UI final comum ao Kanban MES original. O comprimento saiu da vista
    # (26/08): os metros calculam-se com o comprimento teórico do plano.
    row_fields=("cliente", "ov", "of", "perfil", "modelo", "qtd"),
    # Ordem REAL medida nos scans TPL102 (não a ordem textual do PPTX).
    raw_row_fields=("cliente", "ov", "of", "qtd", "tubo", "referencia"),
    footer_fields=("horas_trabalhadas",),
    field_labels={
        "operador": "Operador", "n_operador": "N.º operador", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "cliente": "Cliente", "ov": "OV", "of": "OF", "perfil": "Perfil",
        "modelo": "Modelo", "qtd": "Qtd [un.]", "comp_mm": "Comprimento (mm)",
        "horas_trabalhadas": "Horas trabalhadas",
    },
    raw_field_labels={
        "operador": "Operador", "n_operador": "N.º", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "cliente": "Cliente", "ov": "OV", "of": "OF", "qtd": "QTD",
        "tubo": "TUBO", "referencia": "REFERÊNCIA",
        "horas_trabalhadas": "HORAS TRABALHADAS",
    },
    turno_options=("M", "R", "XM"),
)

VANGUARD_KANBAN = KanbanTemplate(
    name="vanguard_kanban",
    family="perfis",
    label="Vanguard — Kanban de produção (TPL121)",
    index_loader="load_perfis_index",
    row_fields=("cliente", "ov", "of", "perfil", "modelo", "qtd",
                "qtd_total_mm", "duracao"),
    raw_row_fields=("cliente", "ov", "of", "modelo", "qtd", "qtd_total_mm",
                    "ultima_coluna"),
    footer_fields=("metros_produzidos", "horas_trabalhadas"),
    field_labels={
        "operador": "Operador", "n_operador": "N.º operador", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "cliente": "Cliente", "ov": "OV", "of": "OF", "perfil": "Perfil",
        "modelo": "Modelo", "qtd": "Qtd [un.]", "comp_mm": "Comprimento (mm)",
        "qtd_total_mm": "Qtd total [mm]", "duracao": "Duração",
        "n_corte_lote": "N.º corte/lote", "ultima_coluna": "Duração / N.º corte-lote",
        "metros_produzidos": "Metros produzidos",
        "horas_trabalhadas": "Horas trabalhadas",
    },
    raw_field_labels={
        "operador": "Operador", "n_operador": "N.º", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "cliente": "Cliente", "ov": "OV", "of": "OF", "modelo": "MODELO",
        "qtd": "QTD", "qtd_total_mm": "QTD (Metros)",
        "ultima_coluna": "DURAÇÃO ou N.º CORTE/LOTE",
        "metros_produzidos": "METROS PRODUZIDOS",
        "horas_trabalhadas": "HORAS TRABALHADAS",
    },
    turno_options=("M", "R", "XM", "T"),
    dynamic_last_fields=("duracao", "n_corte_lote"),
)

# A TPL999 «PRODUÇÃO PERFIS» substituiu a TPL121 no planeamento e existe em
# seis variantes de máquina (Vanguard, MEBA, Serrote Disco/Doall/Fita Pav.1,
# Abocardar) — a máquina vem impressa no cabeçalho Setor/Máquina, não no
# contrato. A coluna «QTD mm» SÓ existe na variante Vanguard: nas outras
# cinco o OCR devolve `qtd_total_mm` a null e a célula fica vazia. O papel
# já está na ordem canónica, por isso não há contrato raw separado.
TPL999_KANBAN = KanbanTemplate(
    name="tpl999_kanban",
    family="perfis",
    label="Perfis — Kanban de produção (TPL999)",
    index_loader="load_perfis_index",
    # «Perf. Comp.» (perfil completo): a última coluna da TPL999. Quando o
    # operador põe um visto, aquela linha vale por todas as referências
    # daquele perfil na OF — é por isso que nessas linhas pode não haver
    # modelo nem quantidade, e a linha fica sem metros teóricos nem limite.
    row_fields=("cliente", "ov", "of", "perfil", "modelo", "qtd",
                "qtd_total_mm", "perf_comp"),
    footer_fields=("metros_produzidos", "horas_trabalhadas"),
    field_labels={
        "operador": "Operador", "n_operador": "N.º operador", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "cliente": "Cliente", "ov": "OV", "of": "OF", "perfil": "Perfil",
        "modelo": "Modelo", "qtd": "Qtd [un.]",
        "qtd_total_mm": "Qtd total [mm]", "perf_comp": "Perf. Comp.",
        "metros_produzidos": "Metros produzidos",
        "horas_trabalhadas": "Horas trabalhadas",
    },
    raw_field_labels={
        "operador": "Operador", "n_operador": "N.º", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "cliente": "CLIENTE", "ov": "OV", "of": "OF", "perfil": "PERFIL",
        "modelo": "MODELO", "qtd": "QTD", "qtd_total_mm": "QTD mm",
        "perf_comp": "PERF. COMP.",
        "metros_produzidos": "METROS PRODUZIDOS",
        "horas_trabalhadas": "HORAS TRABALHADAS",
    },
    turno_options=("M", "R", "XM"),
)


# A coluna de «perfil completo» voltou ao setor com a TPL999 (é a sua última
# coluna, um visto). O serrote TPL102 e a Vanguard TPL121 continuam sem ela:
# o motor pergunta por ela de forma neutra — sem a coluna, nunca há visto e
# o ramo não dispara.
_MARKS = frozenset({"x", "✓", "v", "sim", "ok"})


def is_marked(value: object) -> bool:
    """A célula tem um visto? (não confundir com ter um número escrito)"""
    return str(value or "").strip().lower() in _MARKS


# Compatibilidade rasa para call-sites que ainda usam ``field_value``. A
# conversão completa (incluindo o fallback ambíguo ``metros``) pertence ao
# adaptador versionado em app.sheet_schema.
_LEGACY_FIELD: dict[str, str] = {"qtd_total_mm": "qtd2"}
LEGACY_FIELD_ALIASES = {old: new for new, old in _LEGACY_FIELD.items()}


def field_value(row: dict, field: str):
    value = row.get(field)
    if value in (None, "") and field in _LEGACY_FIELD:
        return row.get(_LEGACY_FIELD[field])
    return value

PERFIS_PARAGENS = KanbanTemplate(
    name="perfis_paragens",
    family="perfis",
    label="Perfis — Paragens (TPL103 verso)",
    index_loader=None,                # paragens não se cruzam com o plano
    page_kind="stoppages",
    row_fields=("motivo", "inicio", "fim", "duracao", "resolvido"),
    raw_row_fields=("motivo", "inicio", "fim", "duracao", "resolvido"),
    footer_fields=(),
    field_labels={
        "operador": "Operador", "n_operador": "N.º operador", "setor_maquina": "Setor/Máquina",
        "data": "Data", "turno": "Turno",
        "motivo": "Motivo da paragem", "inicio": "Início", "fim": "Fim",
        "duracao": "Duração", "resolvido": "Resolvido",
    },
    turno_options=("M", "R", "XM", "T"),
)

# Revisão de 22/09/2026: comprimento próprio, sem QTD mm nem Perf. Comp.
# O verso usa o mesmo código da frente, mas o contrato de paragens.
_NEW_MACHINES = {
    "TPL290": "DISCO PAV1", "TPL291": "DOALL PAV1", "TPL292": "FITA PAV1",
    "TPL293": "MAQ. ABOCARDAR", "TPL294": "MEBA",
}
NEW_PERFIS_TEMPLATES = tuple(
    template
    for code, machine in _NEW_MACHINES.items()
    for template in (
        replace(
            TPL999_KANBAN, name=f"{code.lower()}_kanban",
            label=f"{machine} — Produção ({code})", document_code=code,
            canonical_machine=machine,
            row_fields=("cliente", "ov", "of", "perfil", "comp_mm", "modelo", "qtd"),
            field_labels={**TPL999_KANBAN.field_labels, "comp_mm": "COMP. mm"},
            raw_field_labels={**TPL999_KANBAN.raw_field_labels, "comp_mm": "COMP. mm"},
        ),
        replace(
            PERFIS_PARAGENS, name=f"{code.lower()}_paragens",
            label=f"{machine} — Paragens ({code} verso)", document_code=code,
            canonical_machine=machine, turno_options=("M", "R", "XM"),
        ),
    )
)

TEMPLATES: dict[str, KanbanTemplate] = {
    t.name: t
    for t in (SERROTE_KANBAN, VANGUARD_KANBAN, TPL999_KANBAN, PERFIS_PARAGENS,
              *NEW_PERFIS_TEMPLATES)
}

# Chaves antigas conservadas para providers e extrações existentes.
OCR_TEMPLATES = {
    "serrote": SERROTE_KANBAN, "vanguard": VANGUARD_KANBAN,
    "tpl999": TPL999_KANBAN, "paragens": PERFIS_PARAGENS,
    **{t.name: t for t in NEW_PERFIS_TEMPLATES},
}


def get_template(name: str) -> KanbanTemplate:
    return TEMPLATES[name]
