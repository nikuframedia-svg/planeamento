"""Contratos de leitura. O modelo lê documentos; não decide saldos ou datas."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _contains_replacement_character(value) -> bool:
    if isinstance(value, str):
        return "\ufffd" in value
    if isinstance(value, dict):
        return any(_contains_replacement_character(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_replacement_character(item) for item in value)
    return False


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def readable_text(self):
        # U+FFFD means that bytes were already lost while the provider formed
        # its result. It cannot be repaired without a new reading.
        if _contains_replacement_character(self.model_dump()):
            raise ValueError("A resposta contém o carácter de substituição Unicode")
        return self


class Evidence(StrictModel):
    page: int = Field(ge=1, le=250)
    text: str = Field(min_length=1, max_length=2000)
    region: tuple[float, float, float, float] | None = None
    source: Literal["document", "derived", "catalog", "human"] = "document"
    derivation: str | None = Field(default=None, max_length=1000)

    @field_validator("region")
    @classmethod
    def normalized_region(cls, value):
        if value is not None and (len(value) != 4 or any(not 0 <= number <= 1 for number in value)
                                  or value[0] >= value[2] or value[1] >= value[3]):
            raise ValueError("A região da evidência deve usar coordenadas normalizadas válidas")
        return value


class Route(StrictModel):
    reference: str = Field(min_length=1, max_length=180)
    machine_group: Literal["Vanguard", "Serrote"]
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)
    evidence: str = Field(min_length=1, max_length=1500)

    @field_validator("quantity", mode="before")
    @classmethod
    def numeric_quantity(cls, value):
        if isinstance(value, bool):
            raise ValueError("Quantidade não pode ser um booleano")
        return value


class WorkItem(StrictModel):
    """Uma necessidade documental selecionada, ainda sem depender da máquina.

    O identificador da origem é deliberadamente independente de quantidade,
    geometria e encaminhamento para que uma releitura não crie outra peça só
    porque um desses valores foi corrigido.
    """
    source_type: Literal["cut_list", "drawing", "table"]
    source_id: str = Field(min_length=1, max_length=160)
    reference: str | None = Field(default=None, max_length=180)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)
    machine_group: Literal["Vanguard", "Serrote"] | None = None
    evidence: str = Field(min_length=1, max_length=1500)
    selection: Literal["explicit", "uncertain"] = "explicit"

    @field_validator("quantity", mode="before")
    @classmethod
    def numeric_quantity(cls, value):
        if isinstance(value, bool):
            raise ValueError("Quantidade não pode ser um booleano")
        return value


class PageInventory(StrictModel):
    page: int = Field(ge=1, le=250)
    kind: Literal["distribution", "cut_list", "drawing", "assembly", "other", "blank"]
    orientation: Literal["upright", "clockwise", "counterclockwise", "upside_down", "unknown"] = "unknown"
    production_order: str | None = None
    sales_order: str | None = None
    sales_orders: list[str] = Field(default_factory=list, max_length=30)
    references: list[str] = Field(default_factory=list, max_length=100)
    routes: list[Route] = Field(default_factory=list, max_length=100)
    work_items: list[WorkItem] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class Inventory(StrictModel):
    pages: list[PageInventory] = Field(min_length=1, max_length=4)


class InventoryReference(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reference: str = Field(min_length=1, max_length=180)
    aliases: list[str] = Field(default_factory=list, max_length=30)


class WorkItemReading(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source_type: Literal["cut_list", "drawing", "table"] | None = None
    source_id: str | None = Field(default=None, max_length=160)
    reference: str | None = Field(default=None, max_length=180)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    quantity: int | None = Field(default=None, ge=1, le=10_000_000)
    machine_group: Literal["Vanguard", "Serrote"] | None = None
    evidence: str | None = Field(default=None, max_length=1500)
    selection: Literal["explicit", "uncertain"] | None = None


class PageInventoryReading(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page: int = Field(ge=1, le=250)
    kind: Literal["distribution", "cut_list", "drawing", "assembly", "other", "blank"]
    orientation: Literal["upright", "clockwise", "counterclockwise", "upside_down", "unknown"] = "unknown"
    production_order: str | None = None
    sales_order: str | None = None
    of: str | None = None
    ov: str | None = None
    sales_orders: list[str] = Field(default_factory=list, max_length=30)
    references: list[str | InventoryReference] = Field(default_factory=list, max_length=100)
    routes: list[Route] = Field(default_factory=list, max_length=100)
    work_items: list[WorkItemReading] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class InventoryReading(BaseModel):
    """Tolerant provider boundary; normalized to Inventory before persistence."""
    model_config = ConfigDict(extra="ignore")
    pages: list[PageInventoryReading] = Field(min_length=1, max_length=4)


class PageLink(StrictModel):
    pages: list[int] = Field(max_length=6)
    explanation: str = Field(min_length=1, max_length=2000)


class Piece(StrictModel):
    component_ref: str | None = Field(default=None, max_length=160,
        description="Referência de fabrico da peça/variante na linha selecionada do desenho (por exemplo, coluna NORMA DES. N°). Numa peça única sem referência autónoma de variante, o número do desenho no cartucho identifica a própria peça e deve constar também aqui. Quando existe referência distinta de variante, usa essa referência, não a referência do índice.")
    drawing_ref: str | None = Field(default=None, max_length=180,
        description="Número do desenho no cartucho; conservar a referência literal, distinta da peça/variante e da posição numérica da tabela.")
    drawing_revision: str | None = Field(default=None, max_length=80,
        description="Revisão literal do cartucho, separada da referência do desenho.")
    variant: str | None = Field(default=None, max_length=500)
    material_type: str | None = Field(default=None, max_length=100,
        description="Família do material explicitamente identificável na designação: tubo redondo, tubo retangular, barra, cantoneira, etc. Tubo com símbolo Ø e espessura de parede identifica tubo redondo; não é necessário conhecer um catálogo para o classificar.")
    material_description: str | None = Field(default=None, max_length=1000)
    profile: str | None = Field(default=None, max_length=200,
        description="Secção nominal copiada do desenho: dimensões em mm separadas por x, sem espaços, nome da família ou comprimento de corte. O comprimento fica em length_mm. Conservar a designação completa em material_description e evidence; não substituir dimensões por valores de catálogo.")
    grade: str | None = Field(default=None, max_length=100)
    quantity_required: int | None = Field(default=None, ge=1, le=10_000_000)
    length_mm: float | None = Field(default=None, gt=0, le=1_000_000)
    outer_diameter_mm: float | None = Field(default=None, gt=0, le=100_000)
    width_mm: float | None = Field(default=None, gt=0, le=100_000)
    height_mm: float | None = Field(default=None, gt=0, le=100_000)
    thickness_mm: float | None = Field(default=None, gt=0, le=100_000)
    angle_deg: float | None = Field(default=None, ge=-360, le=360)
    abocardar: Literal["X", "-"] | None = None
    chanfro: Literal["X", "-"] | None = None
    ponteira: Literal["X", "-"] | None = None
    operations: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=4000)
    identity_discriminator: str | None = Field(default=None, max_length=160,
        description="Identificador humano usado apenas quando a mesma referência representa peças físicas distintas.")
    evidence: dict[str, Evidence] = Field(default_factory=dict, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("profile")
    @classmethod
    def nominal_section(cls, value):
        # Só normalização tipográfica de secções dimensionadas. Não completar
        # cotas nem trocar medidas por um valor normalizado de catálogo.
        if value is not None and re.fullmatch(r"\s*[Øø⌀]?\s*\d+(?:[.,]\d+)?(?:\s*[xX×]\s*\d+(?:[.,]\d+)?){1,2}\s*", value):
            return re.sub(r"[\sØø⌀]", "", value).replace("×", "x").replace("X", "x").replace(",", ".")
        return value

    @field_validator("quantity_required", "length_mm", "outer_diameter_mm", "width_mm", "height_mm",
                     "thickness_mm", "angle_deg", mode="before")
    @classmethod
    def integer_quantity(cls, value):
        if isinstance(value, bool):
            raise ValueError("Quantidade não pode ser um booleano")
        return value


class Extraction(StrictModel):
    pieces: list[Piece] = Field(max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class WorkItemVerification(StrictModel):
    quantity_required: int | None = Field(default=None, ge=1, le=10_000_000)
    length_mm: float | None = Field(default=None, gt=0, le=1_000_000)
    evidence: dict[str, Evidence] = Field(default_factory=dict, max_length=2)
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("quantity_required", "length_mm", mode="before")
    @classmethod
    def numeric_values(cls, value):
        if isinstance(value, bool):
            raise ValueError("O valor não pode ser um booleano")
        return value


REQUIRED_FIELDS = ("component_ref", "drawing_ref", "material_type", "profile",
                   "grade", "quantity_required", "length_mm")
FIELD_LABELS = {
    "component_ref": "Referência da peça", "drawing_ref": "Desenho",
    "drawing_revision": "Revisão do desenho",
    "variant": "Variante selecionada", "material_type": "Tipo de material",
    "material_description": "Designação do material", "profile": "Perfil",
    "grade": "Qualidade", "quantity_required": "Quantidade",
    "length_mm": "Comprimento (mm)", "outer_diameter_mm": "Diâmetro exterior (mm)",
    "width_mm": "Largura (mm)", "height_mm": "Altura (mm)",
    "thickness_mm": "Espessura (mm)", "angle_deg": "Ângulo de corte (°)",
    "abocardar": "Abocardar", "chanfro": "Chanfrar", "ponteira": "Ponteira",
    "operations": "Operações", "notes": "Observações",
    "identity_discriminator": "Discriminador da peça",
}


def ref_key(value: str | None) -> str:
    value = re.sub(r"(?:[_\s.-]REV(?:IS[AÃ]O)?[._\s-]*[A-Z0-9]+)?\.(?:DWG|DXF|PDF)$", "", str(value or ""), flags=re.I)
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def order_number(value: str | None, prefix="OF") -> str | None:
    match = re.fullmatch(rf"\s*(?:{prefix}[\s._-]*)?(\d{{4,10}})\s*", str(value or ""), re.I)
    return prefix + match[1] if match else None


def filename_order(filename: str) -> str | None:
    match = re.search(r"(?:^|[^A-Z0-9])OF[ _.-]*(\d{4,10})(?!\d)", filename.upper())
    return "OF" + match[1] if match else None


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def need_key(of: str, group: str, piece: dict) -> str:
    # O encaminhamento muda sem criar outra necessidade física. Quantidade,
    # geometria e grupo de máquina também podem mudar numa revisão.
    return fingerprint([of, ref_key(piece.get("component_ref")),
                        ref_key(piece.get("identity_discriminator"))])


def reading_decision_fingerprint(field: str, values: dict, raw: dict | None = None) -> str:
    """Liga uma confirmação ao valor, origem e leitura original efetivamente revistos."""
    return fingerprint({"field": field, "value": values.get(field),
        "evidence": values.get("evidence", {}).get(field),
        "raw": (raw or values).get(field)})


def difference_decision_fingerprint(field: str, values: dict, plan_value, source_plan_key) -> str:
    def canonical(value):
        return int(value) if isinstance(value, float) and value.is_integer() else value
    return fingerprint({"field": field, "pdf": canonical(values.get(field)), "plan": canonical(plan_value),
                        "source_plan_key": source_plan_key})


def specification(piece: dict) -> str:
    return fingerprint({k: piece.get(k) for k in FIELD_LABELS if k not in ("notes", "variant")})
