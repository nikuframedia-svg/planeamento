"""Preferências de máquina aprendidas com as escolhas dos planeadores (pedido do Luís, 05/10/2026).

Nunca atribui: só sugere (a sugestão vem pré-escolhida ao «Atribuir máquina» e entra como primeiro critério
da máquina sugerida em estimates.py). Fontes, todas na operação principal:
- escolhas feitas na Carteira («Atribuir máquina», eventos kind='machine') — peso 5, as mais recentes contam
  como as outras: são a vontade explícita do planeador. A máquina sugerida que o Planear grava numa linha sem
  máquina (origem «sugerida», 07/10/2026) não conta;
- máquinas escritas na coluna Máquina da Tabela nas linhas abertas — peso 1;
- histórico do Excel (planeamento_v2, `history`: variante × operação × máquina de OF anteriores) — peso 1.
Contextos, do mais específico para o mais geral: família SKU + perfil, família SKU + espessura, perfil,
família SKU. Ganha o contexto mais específico com pelo menos 3 escolhas e 60% numa só máquina.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict

from .. import planning, planning_needs as needs

WEIGHTS = {"carteira": 5.0, "tabela": 1.0, "historico": 1.0}
MIN_CHOICES = 3
MIN_SHARE = 0.6
CONTEXT_LABELS = {"familia_perfil": "{f} {p}", "familia_espessura": "{f} com {t} mm", "perfil": "perfil {p}", "familia": "família {f}"}
SETOR = {"cantoneiras": "MTG3", "perfis": "MTG2"}
NO_PROFILE = "Sem perfil"

_cache: dict = {}
_lock = threading.Lock()


def _profile(value) -> str:
    return re.sub(r"\s", "", str(value or "").upper())


def _thickness(profile):
    from ..gantt.machines import dimensions
    found = dimensions(profile) if profile else None
    return found[2] if found else None


def contexts(family, profile):
    """[(kind, key)] from most to least specific; family/profile missing → those contexts are skipped."""
    family = family if family and family != "Sem família SKU" else None
    # «Sem perfil» é o marcador da Carteira/ocorrências para perfil vazio, não um perfil (auditoria 06/10, PROP-8).
    profile = None if str(profile or "").strip() == NO_PROFILE else profile
    p = _profile(profile) or None
    t = _thickness(profile)
    out = []
    if family and p:
        out.append(("familia_perfil", (family, p)))
    if family and t is not None:
        out.append(("familia_espessura", (family, t)))
    if p:
        out.append(("perfil", (p,)))
    if family:
        out.append(("familia", (family,)))
    return out


def _names(c):
    """Every machine spelling (code, catalogue name, aliases) → (resource_id, catalogue name)."""
    from .occurrences import resources_context
    codes, by_id, _, _, _ = resources_context(c)
    names = {}
    for code, r in codes.items():
        ident = (r.get("id"), r.get("name"))
        names[code] = ident
        names[str(r.get("name") or "").casefold()] = ident
        for alias in r.get("aliases") or []:
            names[str(alias.get("name") or "").casefold()] = ident
    return names


def build(c, area: str, lines: list[dict]) -> dict:
    from ..gantt import research
    from ..raw import sku_families
    from . import machine_choice
    names = _names(c)
    weighted = defaultdict(Counter)
    raw = defaultdict(Counter)

    def add(family, profile, machine, source):
        ident = names.get(machine) or names.get(str(machine or "").casefold())
        if not ident or not ident[0]:
            return
        for kind, key in contexts(family, profile):
            weighted[(kind, key)][ident] += WEIGHTS[source]
            raw[(kind, key)][ident] += 1

    for x in lines:  # Tabela, linhas abertas
        if machine_choice.normalize(x.get("tabela_machine")):
            add(x.get("sku_family"), x.get("profile"), x["tabela_machine"], "tabela")
    # A máquina sugerida gravada ao Planear (07/10/2026) não é uma escolha do planeador: não ensina, senão a
    # sugestão reforçava-se a si própria.
    for e in c.execute("SELECT detail FROM planning_mtg.sector_decision_events WHERE area = %s AND kind = 'machine' AND action = 'machine' "
                       "AND coalesce(detail->>'origem', '') <> 'sugerida'", (area,)).fetchall():
        d = e["detail"] or {}
        add((d.get("before") or {}).get("familia"), (d.get("before") or {}).get("perfil") or (d.get("seen") or {}).get("profile"),
            (d.get("after") or {}).get("carteira"), "carteira")
    if research.enabled():
        package = research.load(c)
        rule = sku_families.head(c, area)
        family_of = {}
        principal = {}
        for r in package["rows"]:
            if r.get("setor") == SETOR[area] and r.get("fase") == "principal" and r.get("variante_id"):
                principal.setdefault(r["variante_id"], r)
        for h in package["metadata"].get("history") or []:
            r = principal.get(h.get("variante_id"))
            if not r or h.get("operacao_codigo") != r.get("operacao_codigo"):
                continue
            ref = r.get("referencia_original")
            if rule and ref not in family_of:
                family_of[ref] = sku_families.classify(ref, rule["config"]).get("family")
            add(family_of.get(ref), r.get("perfil"), h.get("recurso_atual"), "historico")
    return {"weighted": dict(weighted), "raw": dict(raw)}


def model(area: str, *, conn=None, lines: list[dict] | None = None) -> dict:
    """Preferências do setor, em cache pela importação, pela versão do histórico e pelas escolhas da Carteira."""
    from contextlib import nullcontext
    from . import portfolio
    from ..gantt import research
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        events = c.execute("SELECT count(*) n, max(id) m FROM planning_mtg.sector_decision_events WHERE area = %s AND kind = 'machine'",
                           (area,)).fetchone()
        data = None
        if lines is None:
            data = portfolio.load(area, conn=c)
            lines = data["lines"]
        key = (area, data["generation"] if data else needs.digest([x.get("key") for x in lines]),
               research.head(c)["version_id"] if research.enabled() else None, events["n"], events["m"])
        with _lock:
            cached = _cache.get(area)
        if cached and cached[0] == key:
            return cached[1]
        result = build(c, area, lines)
    with _lock:
        _cache[area] = (key, result)
    return result


def suggest(learned: dict | None, family, profile) -> dict | None:
    """{resource_id, machine, share, choices, context, label} from the most specific context with enough evidence."""
    if not learned:
        return None
    for kind, key in contexts(family, profile):
        counts = learned["weighted"].get((kind, key))
        if not counts:
            continue
        total = sum(counts.values())
        (ident, weight), = counts.most_common(1)
        share = weight / total
        choices = sum(learned["raw"][(kind, key)].values())
        if choices >= MIN_CHOICES and share >= MIN_SHARE:
            values = dict(zip(("f", "p") if kind == "familia_perfil" else ("f", "t") if kind == "familia_espessura" else
                              ("p",) if kind == "perfil" else ("f",), key))
            return {"resource_id": ident[0], "machine": ident[1], "share": round(share, 2), "choices": choices, "context": kind,
                    "label": f"{round(100 * share)}% de {choices} escolhas em " + CONTEXT_LABELS[kind].format(**values)}
    return None


def technical(area: str) -> dict | None:
    """{chave da linha: preferência aprendida já filtrada pelas candidatas técnicas da operação principal}.

    Auditoria 06/10 (PROP-2): a Carteira pré-escolhia a máquina aprendida sem olhar à ficha técnica, que a
    pode excluir (ex. Ficep Rapid 25T para L200X200X24) ou nem a ter como candidata. Esta é a mesma
    preferência que a previsão e a Carga usam (estimates.apply). None quando não há ficha técnica (sem
    camada de pesquisa): fica a sugestão aprendida tal como está.
    """
    from . import occurrences
    data = occurrences.load(area, allow_stale=True)
    if not data.get("research_version"):
        return None
    return {f["line_key"]: f["learned_preference"] for f in data["facts"]
            if f["phase"] == "principal" and "learned_preference" in f}


def for_line(learned: dict | None, checked: dict | None, line: dict) -> dict | None:
    """Sugestão aprendida de uma linha da Carteira: filtrada pela ficha técnica quando `checked` existe."""
    if checked is None:
        return suggest(learned, line.get("sku_family"), line.get("profile"))
    return checked.get(line["key"])
