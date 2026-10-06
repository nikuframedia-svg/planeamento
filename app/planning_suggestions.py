"""Sugestões para o registo manual (/planeamento/manual), pedido do Luís a 06/10/2026.

Só leitura e só sugere: o ecrã mostra o valor sugerido com outro tom e quem escreve por cima ganha sempre.
As regras foram medidas na importação atual do Excel (raw_mtg.plan_production_rows) e na cópia do CPIS
que vem com ela (raw_mtg.cpis_rows):

- Equipa: o mais frequente nas outras linhas da mesma OF no mesmo setor → mesma Referência noutras OF →
  cliente + tipo de obra → cliente → designação da obra → nas cantoneiras «Postes MTG3»; nos perfis vazio.
- Pav.: o mais frequente para a Equipa escolhida (em maiúsculas: mtg3 → MTG3); vazio quando é o habitual
  (ex. VFerreira).
- Data Corte: a mais frequente nas outras linhas da OF.
- Máquina: mesma OF + mesmo perfil → mesma OF → escolhas anteriores (machine_learning, filtradas pela ficha
  técnica quando a linha já existe na Carteira) → conjunto de famílias (machine_choice.effective).
- A partir da mesma Referência (OF nova): tipo de material, perfil, comprimento, 1.ª/2.ª operação, qualidade.
- Dimensões a partir da Designação (geometry.parse_profile; cantoneiras L…X…X…) e Qualidade da Des. Material.

Resultado: {campo: {"value", "source_pt", "confidence"}}; confidence = quota do valor escolhido (0–1) no nível
que decidiu. Só aparecem campos com valor.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from contextlib import nullcontext
from typing import NamedTuple

from . import planning

DEFAULT_TEAM = {"cantoneiras": "Postes MTG3", "perfis": ""}
_GRADE = re.compile(r"\bS\d{3}[A-Z0-9]*\b", re.I)
_WORD = re.compile(r"[A-ZÀ-Ý]{3,}")
_cache: dict[str, tuple[str, "Index"]] = {}
_lock = threading.Lock()


class Row(NamedTuple):
    of: str
    ref: str
    profile: str      # perfil normalizado (maiúsculas, sem espaços) para comparar
    profile_text: str  # como está no Excel, para sugerir
    material: str
    team: str
    pav: str
    machine: str
    cut_date: str
    length: float | None
    op1: str
    op2: str
    grade: str
    description: str
    customer: str
    work_type: str
    designation: str


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def profile_key(value) -> str:
    return re.sub(r"\s", "", str(value or "")).upper()


def pavilion(value) -> str:
    """Pav. como no Excel, normalizado: 1.0 → '1', mtg3 → 'MTG3'."""
    value = text(value)
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return value.upper()


def operation(value) -> str:
    value = text(value)
    return "" if value.casefold() in ("none", "null") else value


def designation_key(value) -> str:
    found = _WORD.findall(str(value or "").upper())
    return found[0] if found else ""


def machine_of(value) -> str:
    from .sector.machine_choice import normalize
    return normalize(text(value))


class Index:
    """Contagens de uma importação do Excel, para votar valores por nível."""

    def __init__(self, area: str, rows: list[Row], cpis: dict | None = None):
        self.area = area
        self.cpis = cpis or {}  # OF → (cliente, tipo de obra, descrição da obra) da cópia do CPIS
        self.by_of: dict[str, list[Row]] = defaultdict(list)
        self.votes: dict[tuple, Counter] = defaultdict(Counter)
        for r in rows:
            self.by_of[r.of].append(r)
            for level, key in self.team_levels(r.ref, r.customer, r.work_type, r.designation):
                if r.team:
                    self.votes[("team", level, key)][r.team] += 1
            if r.team:
                self.votes[("pav", "team", r.team)][r.pav] += 1
            if r.ref:
                for field in ("material", "profile_text", "length", "op1", "op2", "grade", "description"):
                    value = getattr(r, field)
                    if value not in (None, ""):
                        self.votes[(field, "ref", r.ref)][value] += 1

    @staticmethod
    def team_levels(ref, customer, work_type, designation):
        out = []
        if ref:
            out.append(("ref", ref))
        if customer and work_type:
            out.append(("cust_wt", (customer, work_type)))
        if customer:
            out.append(("cust", customer))
        key = designation_key(designation)
        if key:
            out.append(("desig", key))
        return out

    def vote(self, field, level, key, exclude_of=None, *, keep_empty=False):
        """(valor, quota) do mais frequente; exclude_of tira as linhas dessa OF (para medir sem batota)."""
        counts = self.votes.get((field, level, key))
        if not counts:
            return None
        if exclude_of and exclude_of in self.by_of:
            counts = counts.copy()
            for r in self.by_of[exclude_of]:
                if level == "team" and field == "pav" and r.team == key:
                    counts[r.pav] -= 1
                elif field == "team" and r.team and (level, key) in self.team_levels(r.ref, r.customer, r.work_type, r.designation):
                    counts[r.team] -= 1
                elif level == "ref" and r.ref == key:
                    value = getattr(r, field)
                    if value not in (None, ""):
                        counts[value] -= 1
            counts = Counter({k: v for k, v in counts.items() if v > 0})
        if not keep_empty:
            counts = Counter({k: v for k, v in counts.items() if k not in (None, "")})
        if not counts:
            return None
        value, n = counts.most_common(1)[0]
        return value, n / sum(counts.values())


def most(rows, attr, *, normalize=None):
    counts = Counter()
    for r in rows:
        value = getattr(r, attr)
        value = normalize(value) if normalize else value
        if value not in (None, ""):
            counts[value] += 1
    if not counts:
        return None
    value, n = counts.most_common(1)[0]
    return value, n / sum(counts.values())


def _rows(c, area: str, snapshot: str, other: str | None) -> tuple[list[Row], dict]:
    cpis = {}
    snaps = [s for s in (other, snapshot) if s]  # a do próprio setor fica por cima
    for s in snaps:
        for r in c.execute("SELECT production_order_no, customer_name, work_type_code, observations FROM raw_mtg.cpis_rows "
                           "WHERE snapshot_id = %s", (s,)).fetchall():
            if r["production_order_no"]:
                cpis[text(r["production_order_no"])] = (text(r["customer_name"]), text(r["work_type_code"]), text(r["observations"]))
    sql = """SELECT production_order_no, component_ref, profile_type, material_type, material_description, length_mm,
                    customer_name, designation, team, pavilion, cutting_machine, cut_date,
                    row_data->>'Equipa' AS x_team, row_data->>'Pav.' AS x_pav, row_data->>'Máquina Corte' AS x_machine,
                    row_data->>'Qual.' AS x_grade, row_data->>'1ª Oper.' AS x_op1, row_data->>'2ª Oper.' AS x_op2,
                    row_data->>'Data Corte' AS x_cut
             FROM raw_mtg.plan_production_rows WHERE snapshot_id = %s"""
    out = []
    for r in c.execute(sql, (snapshot,)).fetchall():
        of = text(r["production_order_no"])
        if not of:
            continue
        customer, work_type, _ = cpis.get(of, (text(r["customer_name"]), "", ""))
        cut = r["cut_date"].isoformat()[:10] if r["cut_date"] else text(r["x_cut"])[:10]
        machine = r["cutting_machine"] if area == "cantoneiras" and r["cutting_machine"] else r["x_machine"] or r["cutting_machine"]
        description = text(r["material_description"])
        grade = text(r["x_grade"]) if area == "perfis" else ""
        if not grade and area == "cantoneiras":
            found = _GRADE.search(description)
            grade = found.group(0).upper() if found else ""
        length = float(r["length_mm"]) if r["length_mm"] is not None else None
        out.append(Row(of=of, ref=text(r["component_ref"]), profile=profile_key(r["profile_type"]), profile_text=text(r["profile_type"]),
                       material=text(r["material_type"]), team=text(r["x_team"] or r["team"]), pav=pavilion(r["x_pav"] or r["pavilion"]),
                       machine=machine_of(machine), cut_date=cut, length=length,
                       op1=operation(r["x_op1"]) if area == "cantoneiras" else "", op2=operation(r["x_op2"]) if area == "cantoneiras" else "",
                       grade=grade, description=description, customer=customer or text(r["customer_name"]), work_type=work_type,
                       designation=text(r["designation"])))
    return out, cpis


def index(area: str, conn=None) -> Index:
    """Índice da importação atual do setor, em cache até à importação seguinte."""
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        info = planning.snapshot(c, area)
        snapshot = info["snapshot_id"]
        with _lock:
            cached = _cache.get(area)
        if cached and cached[0] == snapshot:
            return cached[1]
        other_area = next((a for a in planning.AREAS if a != area), None)
        try:
            other = planning.snapshot(c, other_area)["snapshot_id"] if other_area else None
        except planning.PlanningError:
            other = None
        built = Index(area, *_rows(c, area, snapshot, other))
    with _lock:
        _cache[area] = (snapshot, built)
    return built


def _put(out, field, found, source):
    if found and found[0] not in (None, ""):
        out[field] = {"value": found[0], "source_pt": source, "confidence": round(found[1], 2)}


def dimensions(area: str, material: str, profile: str) -> dict:
    """Ø/Largura/Altura/Espessura a partir da Designação, como as colunas do Excel."""
    if not profile:
        return {}
    if area == "cantoneiras":
        from .gantt.machines import dimensions as angle
        found = angle(re.split(r"\s", profile.strip())[0])
        return dict(zip(("width_mm", "height_mm", "thickness_mm"), found)) if found else {}
    from .matching.geometry import parse_profile
    parsed = parse_profile(profile)
    if parsed.family or not parsed.dimensions:  # UPN, IPE, HEA, M20…: o perfil já diz tudo
        return {}
    d = [float(x) for x in parsed.dimensions]
    kind = re.sub(r"\s+", " ", (material or "").casefold().replace("rectangular", "retangular")).strip()
    if kind in ("tubo redondo",):
        return dict(zip(("outer_diameter_mm", "thickness_mm"), d[:2])) if len(d) >= 1 else {}
    if kind.startswith("varão") and kind.endswith(("redondo", "nervurado")):
        return {"outer_diameter_mm": d[0]}
    if kind in ("varão quadrado",):
        return {"width_mm": d[0]}
    if kind in ("tubo quadrado",):
        return {"width_mm": d[0], **({"thickness_mm": d[-1]} if len(d) >= 3 else {})}
    if kind in ("chapa",):
        return dict(zip(("width_mm", "thickness_mm"), d[:2]))
    if kind in ("cantoneira", "calha", "tubo retangular", "barra", "varão retangular"):
        return dict(zip(("width_mm", "height_mm", "thickness_mm"), d[:3]))
    return {}


def grade_of(*texts) -> str:
    for value in texts:
        found = _GRADE.search(str(value or ""))
        if found:
            return found.group(0).upper()
    return ""


def _learned_machine(area, of, reference, profile, conn):
    """Escolhas anteriores (filtradas pela ficha quando a linha já está na Carteira), depois o conjunto de famílias."""
    from .sector import machine_choice, machine_learning, portfolio
    from .raw import sku_families
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        rule = sku_families.head(c, area)
        family = sku_families.classify(reference, rule["config"]).get("family") if rule and reference else None
        line = None
        try:
            line = next((x for x in portfolio.load(area, conn=c)["lines"] if x["of"] == of and x["reference"] == reference), None)
        except planning.PlanningError:
            line = None
        learned = machine_learning.model(area, conn=c)
        checked = None
        if line is not None:
            try:
                checked = machine_learning.technical(area)
            except Exception:  # a ficha técnica é opcional
                checked = None
        found = machine_learning.for_line(learned, checked, line if line is not None else
                                          {"key": None, "sku_family": family, "profile": profile})
        if found and found.get("machine"):
            return {"value": found["machine"], "source_pt": "escolhas anteriores (" + found.get("label", "aprendido") + ")",
                    "confidence": found.get("share") or 0}
        chosen = machine_choice.effective(machine_choice.context(area, conn=c), [line["key"]] if line else [], family, "")
        if chosen.get("machine"):
            return {"value": chosen["machine"], "source_pt": "conjunto de famílias" + (" " + chosen["set"] if chosen.get("set") else ""),
                    "confidence": 1.0}
    return None


def suggest(area: str, of: str, reference: str | None = None, profile: str | None = None, values: dict | None = None,
            *, conn=None, idx: Index | None = None, exclude_of: str | None = None, learned: bool = True) -> dict:
    """{campo: {value, source_pt, confidence}} para a peça (área, OF, referência, perfil).

    `values` traz o que já está escrito no ecrã (equipa, tipo de material, cliente, designação da obra…): o que
    o utilizador escreveu orienta as sugestões seguintes (ex. o Pav. segue a Equipa escrita).
    `exclude_of` e `learned=False` servem para medir as regras sem a própria OF (ver tests/test_planning_suggestions.py).
    """
    area = planning.check_area(area)
    values = dict(values or {})
    of = text(of)
    reference = text(reference or values.get("component_ref"))
    profile = text(profile or values.get("profile"))
    idx = idx or index(area, conn)
    own = [] if exclude_of == of else idx.by_of.get(of, [])
    out: dict = {}

    # Linhas da mesma referência (primeiro nesta OF; senão noutras OF).
    same = [r for r in own if reference and r.ref == reference]
    for field, attr in (("material_type", "material"), ("profile", "profile_text"), ("length_mm", "length"),
                        ("operation", "op1"), ("operation_detail", "op2"), ("grade", "grade")):
        if attr in ("op1", "op2") and area != "cantoneiras":
            continue
        if same:
            _put(out, field, most(same, attr), "linha do Excel desta OF")
        elif reference:
            _put(out, field, idx.vote(attr, "ref", reference, exclude_of), "mesma referência noutras OF")

    # Equipa.
    customer = text(values.get("customer"))
    work_type = text(values.get("work_type_code"))
    designation = text(values.get("designation"))
    known = idx.cpis.get(of) or ((own[0].customer, own[0].work_type, own[0].designation) if own else ("", "", ""))
    customer, work_type, designation = customer or known[0], work_type or known[1], designation or known[2]
    team = most(own, "team")
    if team:
        _put(out, "team", team, "outras linhas da OF")
    else:
        labels = {"ref": "mesma referência noutras OF", "cust_wt": "cliente e tipo de obra", "cust": "cliente",
                  "desig": "designação da obra"}
        for level, key in Index.team_levels(reference, customer, work_type, designation):
            found = idx.vote("team", level, key, exclude_of)
            if found:
                _put(out, "team", found, labels[level])
                break
        else:
            if DEFAULT_TEAM[area]:
                out["team"] = {"value": DEFAULT_TEAM[area], "source_pt": "habitual nas cantoneiras", "confidence": 0.97}

    # Pav. segue a Equipa escrita; senão a sugerida.
    chosen_team = text(values.get("team")) or (out.get("team") or {}).get("value")
    if chosen_team:
        found = idx.vote("pav", "team", chosen_team, exclude_of, keep_empty=True)
        _put(out, "pavilion", found, "Pav. habitual da Equipa " + chosen_team)

    # Data Corte.
    _put(out, "cut_date", most(own, "cut_date"), "outras linhas da OF")

    # Máquina.
    wanted = profile_key(profile or (out.get("profile") or {}).get("value"))
    found = most([r for r in own if wanted and r.profile == wanted], "machine")
    if found:
        _put(out, "machine", found, "mesma OF e mesmo perfil")
    else:
        found = most(own, "machine")
        if found:
            _put(out, "machine", found, "outras linhas da OF")
        elif learned:
            try:
                machine = _learned_machine(area, of, reference, profile or (out.get("profile") or {}).get("value"), conn)
            except Exception:  # a sugestão aprendida é opcional: nunca impede as outras
                import logging
                logging.getLogger(__name__).exception("Sugestão de máquina aprendida indisponível")
                machine = None
            if machine:
                out["machine"] = machine

    # Dimensões e Qualidade a partir da Designação / Des. Material.
    shown_profile = profile or (out.get("profile") or {}).get("value") or ""
    material = text(values.get("material_type")) or (out.get("material_type") or {}).get("value") or ""
    for field, value in dimensions(area, material, shown_profile).items():
        out[field] = {"value": value, "source_pt": "Designação " + shown_profile, "confidence": 1.0}
    if area == "cantoneiras":
        grade = grade_of(profile, values.get("material_description"))
        if grade:
            out["grade"] = {"value": grade, "source_pt": "Des. Material", "confidence": 1.0}
    return out


def for_order(area: str, of: str, reference: str | None = None, profile: str | None = None, values: dict | None = None) -> dict:
    """Resposta do endpoint: as sugestões e a importação de onde vêm."""
    with planning.connect(readonly=True) as c:
        idx = index(area, c)
        result = suggest(area, of, reference, profile, values, conn=c, idx=idx)
        snapshot = planning.snapshot(c, area)["snapshot_id"]
    return {"area": area, "of": text(of), "snapshot": snapshot, "fields": result}
