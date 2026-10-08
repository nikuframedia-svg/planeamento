"""Carteira: todo o trabalho aberto de um setor, agrupado por tema.

Só leitura. Junta três fontes da mesma importação do Excel:
- a projeção RAW da aplicação: linhas ativas, produção MES associada, máquina, prazo e estado CPIS;
- a linha original do Excel (raw_mtg.plan_production_rows.row_data): notas «Descrição» e «P» (também nas peças
  registadas a partir de uma linha do Excel, pela linha de origem);
- a cópia do CPIS dentro do Excel (raw_mtg.cpis_rows): família e data de registo da OF.

Saldo por operação segundo a mesma política de reconciliação do Gantt e da carga.
Sobreposição desconhecida conserva a pendência e não soma fontes.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta

from .. import planning, planning_needs as needs, planning_population as population
from . import cache, decisions as resolution, planning_status
from .occurrences import NO_CPIS_FAMILY
from .references import UNRESOLVED, master_reference
from .week import lisbon_today

SECTORS = {"cantoneiras": "MTG3 Cantoneiras", "perfis": "MTG2 Perfis"}
OPEN_STATES = set(planning.OPEN_STATES)

WINDOWS = {  # ordem = urgência; prazo pela política do setor (MTG3: Data Corte; MTG2: Picking utilizável)
    "atrasado": "Prazo já passado",
    "3_semanas": "Até ao fim da semana ISO +2",
    "mais_tarde": "Mais tarde",
    "sem_data": "Sem prazo",
    "estacionada": "Estacionada no Excel (W 2026/53)",  # S53-1: fora do atraso e da carga das semanas
}
LEVELS = {
    "master": "Referência mestre",
    "reference": "Referência (SKU)",
    "of": "OF",
    "work": "OV",
    "profile": "Perfil",
    "family": "Família de Produto",
    "sku_family": "Família SKU",
    "customer": "Cliente",
}
VIEWS = {
    "referencia": ("master", "reference", "of"),
    "of": ("work", "of"),
    "perfil": ("profile", "of"),
    "of_perfil": ("of", "profile"),
    "familia": ("family", "of"),
    "familia_sku": ("sku_family", "reference", "of"),
    "cliente": ("customer", "of"),
}
VIEW_LABELS = {  # a primeira é a vista por defeito do ecrã (esboço do Luís: Perfil)
    "perfil": "Perfil → OF",
    "of_perfil": "OF → Perfil",
    "referencia": "Referência: modelo → SKU → OF",
    "of": "OV → OF",
    "familia": "Família de Produto → OF",
    "familia_sku": "Família SKU → referência → OF",
    "cliente": "Cliente → OF",
}
SIGNALS = {
    "prioridade": "Prioridade escrita",
    "anulada": "Marcada «anulada» no Excel",
    "eletrofer": "Feita na Eletrofer",
    "validacao": "Fabricar após validação",
    "estado_cpis": "Estado CPIS por confirmar",
}

# Ordem dos grupos (P6, 08/10/2026). As duas por data ordenam pela data mais antiga com saldo de cada grupo:
# primeiro as atrasadas (a mais antiga à frente), depois as futuras, sem data e só estacionadas. «picking» só na
# MTG2. Os rótulos estão no ecrã (carteira2.html/js); aqui só os códigos.
ORDERS = ("corte", "picking", "urgencia", "metros")
DATE_ORDERS = ("corte", "picking")


def orders(sector: str) -> tuple:
    return tuple(o for o in ORDERS if o != "picking" or sector == "perfis")


def default_order(sector: str) -> str:
    """Por defeito no ecrã: MTG3 pela Data Corte, MTG2 pelo Picking."""
    return "picking" if sector == "perfis" else "corte"


def check_order(sector: str, order: str) -> str:
    if order not in orders(sector):
        raise planning.PlanningError("Ordem inválida.")
    return order


STATES = {  # decisão Planear de cada linha (informação da linha; o filtro Estado usa STATUS)
    "proposta": "Proposta por decidir",
    "selecionado": "Marcado para planear",
    "excluido": "Excluído",
    "por_decidir": "Sem decisão",
}
STATUS = planning_status.STATUS  # filtro Estado (plano de 02/10/2026)
NO_WEEK = "sem"
PARKED_WEEK = "estacionada"  # filtro de semanas: linhas estacionadas no Excel (S53-1), à parte de «Sem semana definida»
# Sinais que tiram uma linha da proposta. «Estado CPIS por confirmar» saiu a 07/10/2026 (fica como etiqueta e
# filtro): tirava todas as linhas sem estado CPIS, incluindo cada OF manual nova.
BLOCKING = ("anulada", "eletrofer", "validacao")
WHOLE = resolution.WHOLE  # decisão antiga sobre a OF inteira

_PRIORITY = re.compile(r"(\d+)\s*[ªº]?\s*PRIORIDADE", re.I)
_CANCELLED = re.compile(r"anulad", re.I)
_ELETROFER = re.compile(r"ELE[C]?TROFER", re.I)
_VALIDATION = re.compile(r"AP[ÓO]S\s+(A\s+)?VALIDA", re.I)
_WRITTEN_WEEK = re.compile(r"ENTREGA\s*W\s*(\d{1,2})(?:\s*/\s*(\d{4}))?", re.I)

_SQL = """
WITH g AS (  -- a geração da chave da cache (não «a mais recente»: pode ter chegado outra entretanto)
    SELECT id, dataset, metadata->'snapshot'->>'snapshot_id' AS snapshot
    FROM planning_mtg.raw_generations WHERE dataset = %(dataset)s AND id = %(generation)s
)
SELECT m.row_key, c.values_json AS v, c.detail, g.id AS generation, g.snapshot,
       p.row_data->>'Descrição' AS notes, p.row_data->>'P' AS p_value,
       p.row_data->>'Observações' AS observations,
       p.row_data->>'Observações Galvanização' AS galvanising_notes,
       cp.work_type_code, cp.work_type_description, cp.record_date
FROM g
JOIN planning_mtg.raw_members m ON m.dataset = g.dataset AND m.first_generation <= g.id
     AND (m.last_generation IS NULL OR m.last_generation > g.id)
JOIN planning_mtg.raw_resolved_contents c ON c.hash = m.content_hash
-- Linha do Excel de origem: pela chave «macro:<linha>»; numa peça registada (chave = UUID do registo) pela
-- linha do Excel de onde veio (detail.plan_key), para não perder Descrição, P e Observações (06/10/2026).
LEFT JOIN raw_mtg.plan_production_rows p ON p.snapshot_id = g.snapshot
     AND p.source_line_id = CASE WHEN m.row_key LIKE 'macro:%%' THEN substr(m.row_key, 7) ELSE c.detail->>'plan_key' END
LEFT JOIN raw_mtg.cpis_rows cp ON cp.snapshot_id = g.snapshot AND cp.production_order_no = c.values_json->>'of'
WHERE (c.values_json->>'planning_active')::boolean
"""

# Por setor: as linhas da última geração lida. As leituras podem receber a geração anterior (marcada «stale»)
# enquanto a nova se calcula em segundo plano (cache.py); as gravações leem sempre a atual. Fica sempre a geração
# mais recente (dia, geração): um cálculo sobre um retrato mais antigo da base (load com a ligação de quem chama)
# não a substitui.
_cache = cache.Cache("Carteira", mark=lambda value: {**value, "stale": True}, rank=lambda key: (key[1], key[0]))
_lock = threading.Lock()


def check_sector(sector: str) -> str:
    if sector not in SECTORS:
        raise planning.PlanningError("Seleciona MTG2 Perfis ou MTG3 Cantoneiras.")
    return sector


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def window_of(cut_date: date | None, today: date) -> str:
    if cut_date is None:
        return "sem_data"
    if cut_date < today:
        return "atrasado"
    end = today - timedelta(days=today.weekday()) + timedelta(weeks=2, days=6)  # domingo da semana ISO +2
    return "3_semanas" if cut_date <= end else "mais_tarde"


def cpis_open(status: str | None, status_values: list | None = None) -> bool:
    """Estado CPIS aberto para o planeamento, com a mesma lista da população (planning_population.CPIS_OPEN).

    «Em Aberto», «Em Produção» e «Pronta» são abertas: «Pronta» não fecha a OF na população, por isso
    a Carteira e «Sem peças nos planos» também não a tratam como fechada (auditoria 06/10/2026, A3-7).
    Desde 06/10/2026 o estado já vem resolvido pela cópia CPIS mais recente (planning_hub._order_summary),
    tal como vem. A lista de estados só serve gerações gravadas antes disso, sem estado único: aí a OF só
    conta como aberta se todas as cópias disserem um estado aberto (regra antiga A8-3).
    """
    values = [status] if status else [s for s in (status_values or []) if s]
    return bool(values) and all(population.token(s) in population.CPIS_OPEN for s in values)


def signals_of(designation: str, notes: str, observations: str, galvanising_notes: str, status: str | None,
               status_values: list | None = None) -> dict:
    text = " ".join(x for x in (designation, observations) if x)
    priority = _PRIORITY.search(designation or "")
    week = _WRITTEN_WEEK.search(designation or "")
    return {
        "prioridade": int(priority.group(1)) if priority else None,
        "anulada": bool(_CANCELLED.search(notes or "")),
        "eletrofer": bool(_ELETROFER.search(" ".join(x for x in (notes, galvanising_notes) if x))),
        "validacao": bool(_VALIDATION.search(text)),
        "estado_cpis": not cpis_open(status, status_values),
        "entrega_escrita": f"W{int(week.group(1))}" + (f"/{week.group(2)}" if week.group(2) else "") if week else None,
    }


def line_from_row(row: dict, today: date, *, policy: dict | None = None, overrides: dict | None = None,
                  keep_done: bool = False) -> dict | None:
    """One open plan line, or None when nothing is left to cut (`keep_done`: the line anyway, for the warnings)."""
    from . import priority
    v = row["v"]
    quantity = _number(v.get("quantity_required"))
    if quantity is None:
        return None
    from ..planning_estimates import select_balance
    detail = row.get('detail') or {}
    op = 'corte' if detail.get('area') == 'perfis' else str(v.get('operation') or '')
    b = select_balance({**detail, 'values':v},op)
    pieces = _number(v.get('planning_remaining')) if 'planning_remaining' in v else b['planning_remaining']
    # A single documentary counter is usable; an OCR overlap without a resolved
    # production source remains unknown rather than selecting a maximum.
    if pieces is None and 'planning_remaining' not in v and not detail.get('calculation') and v.get('ocr_quantity') is None and _number(v.get('made')) is not None:
        pieces = quantity - _number(v.get('made'))
    done = quantity - pieces if pieces is not None else None
    following=(detail.get('calculation') or {}).get('integrated_operations',[])
    pending_operations=[s for s in following if s.get('remaining') is None or s['remaining']>0]
    if pieces is not None and pieces <= 0 and not pending_operations and not keep_done:
        return None
    length = _number(v.get("length_mm"))
    weight_unit = _number(v.get("weight_unit"))
    # Desconhecido nunca vira 0 (08/10): sem saldo ou sem comprimento, os metros ficam por saber. O campo «metres»
    # continua a somar só o conhecido (0.0 aqui), porque o Planear e os conjuntos somam-no; o ecrã e os
    # subtotais usam «metres_unknown» («—» na lupa, contados à parte).
    metres_unknown = pieces is None or (pieces > 0 and not length)
    excess = _number(v.get("production_excess"))
    reference = (v.get("component_ref") or "").strip()
    cut_date = _day(v.get("cut_date"))
    status = v.get("status")
    designation = (v.get("designation") or "").strip()
    family_code = (row.get("work_type_code") or "").strip() or None
    family_name = (row.get("work_type_description") or "").strip()
    from . import machine_choice
    tabela_machine = (v.get("machine") or "").strip()
    machine = machine_choice.normalize(tabela_machine)  # «Por definir», «Sem máquina» … = sem máquina
    area = "perfis" if detail.get("area") == "perfis" else "cantoneiras"
    raw = detail.get("raw") or {}
    marks = priority.milestones_from_values(v, raw, assumed_year=(policy or {}).get("assume_picking_year"))
    status_values = detail.get("status_values") or []
    signals = signals_of(designation, row.get("notes"), row.get("observations"), row.get("galvanising_notes"), status,
                         status_values)
    due = priority.resolve(area, "principal", marks, policy=policy or priority.default(area),
                           override=priority.override_for(overrides or {}, area, v.get("of") or "", reference),
                           urgent=signals["prioridade"] is not None)
    window = priority.window(due, today)
    priority_day = _day(due["priority_day"])
    # Picking da linha (P6, 08/10): dia de Lisboa da segunda-feira da semana; provisório com o ano deduzido.
    picking = marks.get("picking")
    picking_day = datetime.fromisoformat(picking["at"]).astimezone(priority.LISBON).date() if picking else None
    return {
        "key": row["row_key"],
        "aliases": list(detail.get("selection_aliases") or []),
        "signature": needs.digest(needs.signature(v))[:16],
        "of": v.get("of") or "",
        "ov": v.get("ov") or "",
        "customer": (v.get("customer") or "").strip() or "Sem cliente",
        "designation": designation,
        "work": v.get("ov") or v.get("of") or "",
        "family_code": family_code,
        "family": f"{family_code} {family_name}".strip() if family_code else NO_CPIS_FAMILY,
        "sku_family": v.get("sku_family") or "Sem família SKU",
        "sku_family_status": v.get("sku_family_status") or ("Sem catálogo" if area == "perfis" else "Sem família identificada"),
        "registered": _day(row.get("record_date")),
        # Gerações anteriores a 06/10/2026 podem ter estados diferentes sem estado único (A3-3); as novas
        # já trazem o estado da cópia CPIS mais recente.
        "status": status or ("Estado em conflito" if len(status_values) > 1 else "Sem estado CPIS"),
        "reference": reference or "Sem referência",
        "master": master_reference(reference) or UNRESOLVED,
        "profile": (v.get("profile") or "").strip() or "Sem perfil",
        "length_mm": length,
        "quantity": quantity,
        "done": done,
        "pieces": pieces,
        "metres": pieces * length / 1000 if pieces is not None and length else 0.0,
        "metres_unknown": metres_unknown,
        # Toneladas = saldo de peças × peso unitário (coluna «Peso un. Kg» ou tabela de pesos); sem peso → desconhecido.
        # Sem saldo na operação principal (só falta a seguinte) são 0 kg por cortar, com ou sem peso: assim o «sem peso»
        # da Carteira conta a mesma população da Carga, que só tem ocorrências principais com saldo (08/10).
        "kg": 0.0 if pieces is not None and pieces <= 0 else pieces * weight_unit if pieces is not None and weight_unit is not None else None,
        "weight_unit": weight_unit,
        "balance_unknown": pieces is None,
        "pending_following_operations":len(pending_operations),
        # Só falta a operação seguinte: o saldo dela, para a lupa dizer «Abocardar: N» em vez de 0 peças (08/10).
        **({"following": following_balances(pending_operations)} if pieces is not None and pieces <= 0 and pending_operations else {}),
        # Produção acima da QTD (F07, 08/10): aviso na lupa; nada é corrigido.
        **({"production_excess": excess} if excess and excess > 0 else {}),
        "balance_origin": v.get('planning_balance_origin') or b['balance_origin'],
        "machine": machine,  # máquina efetiva depois de current(); aqui só a da Tabela
        "tabela_machine": tabela_machine,
        "machine_source": "tabela" if machine else None,
        "machine_resource_id": None,
        "week": _number(v.get("imported_week")),
        "p": _number(row.get("p_value")),
        "cut_date": cut_date,
        "priority_day": priority_day,
        "iso_week": iso_week(priority_day),
        "priority_source": due["priority_source"] or due["missing_reason"],
        "priority_field": due["priority_field"],
        "priority_provisional": bool(due.get("provisional")),
        "picking_day": picking_day,
        "picking_provisional": bool(picking and picking.get("provisional")),
        "parked": bool(due.get("parked")),
        "delivery_date": _day(v.get("delivery_date")),
        "window": window,
        "signals": signals,
        "proposal": proposal_of(signals, window),
    }


def following_balances(operations: list[dict]) -> list[dict]:
    """[{label, remaining}] das operações seguintes por fazer: «Abocardar» ou «2.ª op.», saldo somado por rótulo;
    None quando algum saldo é desconhecido."""
    out: dict[str, float | None] = {}
    for op in operations:
        label = "Abocardar" if str(op.get("operation")) == "LOCAL:ABOCARDAR" else "2.ª op."
        value = _number(op.get("remaining"))
        out[label] = None if value is None or (label in out and out[label] is None) else (out.get(label) or 0) + value
    return [{"label": k, "remaining": v} for k, v in out.items()]


def repeated_identity(line: dict, values: dict) -> tuple:
    """Linhas iguais em OF, referência, perfil, comprimento, QTD, material e qualidade: possivelmente repetidas."""
    return (line["of"], line["reference"], line["profile"], line["length_mm"], line["quantity"],
            (values.get("material_type") or "").strip(), (values.get("grade") or "").strip())


def mark_repeated(lines: list[dict], identities: list[tuple]) -> None:
    """Marca as linhas repetidas (08/10, F06): `repeated` = n em cada uma; a partir da 2.ª (pela chave),
    `repeat_extra` diz que é a cópia que conta a mais. Nada é removido nem somado de outra forma."""
    groups = defaultdict(list)
    for line, identity in zip(lines, identities):
        groups[identity].append(line)
    for same in groups.values():
        if len(same) < 2:
            continue
        for i, line in enumerate(sorted(same, key=lambda x: x["key"])):
            line["repeated"] = len(same)
            if i:
                line["repeat_extra"] = True


def proposal_of(signals: dict, window: str) -> str | None:
    """Proposed tier: A prioridade escrita, B atrasado, C até ao fim da semana ISO +2; None fora da proposta."""
    if any(signals.get(name) for name in BLOCKING):
        return None
    if signals.get("prioridade") is not None:
        return "A"
    return {"atrasado": "B", "3_semanas": "C"}.get(window)


def iso_week(day: date | None) -> str | None:
    """2026-W40 from the sector's deadline day; ISO year, so 28/12/2026 and 01/01/2027 never mix."""
    if day is None:
        return None
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def effective(line: dict, decisions: dict | None) -> dict:
    """Decisão efetiva: membro (chave atual ou aliases) → (OF, referência) → (OF, '*')."""
    return resolution.resolve(decisions or {}, getattr(decisions, "members", {}),
                              [(line["of"], line["reference"]), (line["of"], WHOLE)],
                              [k for k in (line.get("key"), *line.get("aliases", ())) if k])


def decision_of(line: dict, decisions: dict | None) -> str | None:
    """A decisão mais específica ganha: membro, depois (OF, referência), depois (OF, '*')."""
    if not decisions and not getattr(decisions, "members", None):
        return None
    return effective(line, decisions)["decision"]


def status_of(line: dict, decisions: dict | None) -> dict:
    return planning_status.classify(effective(line, decisions), line["machine"])


def state_of(line: dict, decisions: dict | None) -> str:
    decision = decision_of(line, decisions)
    if decision == "selected":
        return "selecionado"
    if decision == "excluded":
        return "excluido"
    return "proposta" if line["proposal"] else "por_decidir"


def _stamp(c, sector: str, today: date) -> tuple[tuple, dict]:
    """(chave, geração): tudo aquilo de que as linhas dependem — geração da projeção do setor, dia, versão da
    camada de pesquisa e prioridades. As exportações do OCR original (original:*) não entram: a Carteira não as lê."""
    head = c.execute("SELECT id, metadata->'snapshot'->>'snapshot_id' AS snapshot, created_at "
                     "FROM planning_mtg.raw_generations WHERE dataset = %s ORDER BY id DESC LIMIT 1", (f"planning:{sector}",)).fetchone()
    if not head:
        raise planning.PlanningError("A preparar a consulta deste setor. Tenta dentro de alguns segundos.", 503)
    from ..gantt import research
    from . import priority
    return (head["id"], today, research.head(c)['version_id'] if research.enabled() else None, priority.digest(c)), head


def _build(c, sector: str, head: dict, today: date) -> dict:
    from ..gantt.research import overlay_rows, enabled
    from . import priority
    rows = c.execute(_SQL, {"dataset": f"planning:{sector}", "generation": head["id"]}).fetchall()
    if enabled():
        overlays = [{**(r.get('detail') or {}), 'key':r['row_key'], 'values':dict(r['v'])} for r in rows]
        overlay_rows(c,sector,overlays)
        for r,o in zip(rows,overlays):
            r['v'] = o['values'];r['detail'] = o
    policies, overrides = priority.policies(c), priority.overrides(c)
    for r in rows:
        r.setdefault("detail", {})
        if isinstance(r["detail"], dict):
            r["detail"].setdefault("area", sector)
    lines, identities, excess_done = [], [], []
    for r in rows:
        line = line_from_row(r, today, policy=policies[sector], overrides=overrides)
        if line:
            lines.append(line)
            identities.append(repeated_identity(line, r["v"]))
        elif (_number(r["v"].get("production_excess")) or 0) > 0:
            # Produção acima da QTD (F07, 08/10): a linha sai da Carteira com saldo 0, mas o aviso conta-a.
            done = line_from_row(r, today, policy=policies[sector], overrides=overrides, keep_done=True)
            if done:
                excess_done.append(done)
    mark_repeated(lines, identities)
    return {"sector": sector, "generation": head["id"], "snapshot": head["snapshot"],
            "imported_at": head["created_at"], "today": today, "lines": lines, "excess_done": excess_done, "stale": False}


def load(sector: str, *, today: date | None = None, conn=None, allow_stale: bool = False) -> dict:
    """All open lines of the sector from the latest projection, cached per generation and day.

    `allow_stale` (só leituras): com uma geração nova, devolve logo as linhas da anterior do mesmo dia, com
    `stale: True`, e calcula a nova uma vez em segundo plano. As gravações nunca o passam.
    """
    check_sector(sector)
    today = today or lisbon_today()  # dia de Lisboa, como a Carga (08/10)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        if conn is None:  # a chave e as linhas do mesmo retrato da base
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        c.execute("SET LOCAL jit = off")
        key, head = _stamp(c, sector, today)
        return _cache.get(sector, key, lambda: _build(c, sector, head, today), allow_stale=allow_stale,
                          stale_if=lambda old: old[1] == today, refresh=lambda: load(sector, today=today))


def check_estado(value: str | None) -> None:
    if value and value not in STATUS and value not in STATES:
        raise planning.PlanningError("Estado inválido.")


# Por setor: (carimbo, base de load(), resultado). Guarda a própria base: compara-a por identidade (`is`) e, enquanto
# está aqui, o endereço dela não pode ser reutilizado por outra.
_current_cache: dict[str, tuple[tuple, dict, dict]] = {}


def current(sector: str, *, today: date | None = None, conn=None, allow_stale: bool = False) -> dict:
    """As linhas de load() com a máquina efetiva (Carteira → Tabela → conjunto de famílias).

    load() faz o trabalho pesado e fica em cache por importação; aqui só se aplica, por cima, a máquina
    escolhida na Carteira e a dos conjuntos — muda a cada «Atribuir máquina» sem refazer a carteira. A máquina
    escolhida é sempre a atual, mesmo quando `allow_stale` dá as linhas da geração anterior.
    """
    from . import machine_choice
    base = load(sector, today=today, conn=conn, allow_stale=allow_stale)
    ctx = machine_choice.context(sector, conn=conn)
    stamp = (base["generation"], base["today"], ctx["digest"])
    with _lock:
        cached = _current_cache.get(sector)
    if cached and cached[0] == stamp and cached[1] is base:
        return cached[2]
    lines = []
    for x in base["lines"]:
        family = x["sku_family"] if x["sku_family"] != "Sem família SKU" else None
        found = machine_choice.effective(ctx, [x["key"], *x["aliases"]], family, x["tabela_machine"])
        if found["source"] in (None, "tabela"):
            lines.append(x)
        else:
            lines.append({**x, "machine": found["machine"], "machine_source": found["source"], "machine_resource_id": found["resource_id"]})
    result = {**base, "lines": lines, "machine_digest": ctx["digest"]}
    with _lock:
        _current_cache[sector] = (stamp, base, result)
    return result


def matches(line: dict, filters: dict, decisions: dict | None = None) -> bool:
    """Filtros da lista. Os mesmos filtros servem a lista e qualquer ação que ainda dependa deles."""
    if filters.get("familia") and line["family_code"] != filters["familia"]:
        return False
    if filters.get("familia_sku") and line["sku_family"] != filters["familia_sku"]:
        return False
    if filters.get("janela") and line["window"] != filters["janela"]:
        return False
    weeks = filters.get("semanas") or []
    if not isinstance(weeks, list):
        raise planning.PlanningError("Prazo inválido.")
    weeks = [w for w in weeks if isinstance(w, str) and w]
    if weeks and week_code(line) not in weeks:
        return False
    machine = filters.get("maquina")
    if machine == "sem" and line["machine"]:
        return False
    if machine == "com" and not line["machine"]:
        return False
    if machine and machine not in ("sem", "com") and line["machine"] != machine:
        return False
    signal = filters.get("sinal")
    if signal and not line["signals"].get(signal):
        return False
    query = filters.get("q") or ""
    if not isinstance(query, str):
        raise planning.PlanningError("Pesquisa inválida.")
    query = query.strip().upper()
    if query:
        haystack = " ".join((line["of"], line["ov"], line["reference"], line["master"], line["customer"],
                             line["designation"], line["profile"])).upper()
        if query not in haystack:
            return False
    wanted = filters.get("estado")
    if wanted:
        check_estado(wanted)
        if wanted in STATUS:
            return planning_status.matches(status_of(line, decisions), wanted)
        return state_of(line, decisions) == wanted
    return True


def _summary(lines: list[dict], decisions: dict | None = None) -> dict:
    metres = sum(x["metres"] for x in lines)
    by_state = defaultdict(float)
    state_counts=defaultdict(int)
    status = {code: {"lines": 0, "metres": 0.0, "pieces": 0.0, "kg": 0.0, "kg_unknown": 0, "ofs": set()} for code in STATUS}
    for x in lines:
        by_state[state_of(x, decisions)] += x["metres"]
        state_counts[state_of(x,decisions)]+=1
        for code, value in status_of(x, decisions).items():
            if value:
                s = status[code]
                s["lines"] += 1
                s["metres"] += x["metres"]
                s["pieces"] += x["pieces"] or 0
                if x.get("kg") is None:
                    s["kg_unknown"] += 1
                else:
                    s["kg"] += x["kg"]
                s["ofs"].add(x["of"])
    by_machine = defaultdict(float)
    windows = defaultdict(float)
    window_lines = defaultdict(int)
    signals = defaultdict(int)
    for x in lines:
        by_machine[x["machine"] or "Sem máquina"] += x["metres"]
        windows[x["window"]] += x["metres"]
        window_lines[x["window"]] += 1
        for name, value in x["signals"].items():
            if value and name != "entrega_escrita":
                signals[name] += 1
    cut_dates = [x["cut_date"] for x in lines if x["cut_date"]]
    priority_days = [x["priority_day"] for x in lines if x.get("priority_day")]
    priorities = [x["signals"]["prioridade"] for x in lines if x["signals"]["prioridade"] is not None]
    # Datas das ordens por data (P6, 08/10): só as linhas com saldo (ou por confirmar) e não estacionadas. Um grupo
    # já todo cortado, só com a operação seguinte por fazer (ex.: OF2629695, L100X50X8), usa as datas das suas linhas
    # não estacionadas: senão ia para «sem data», no fim, com trabalho atrasado.
    pending = [x for x in lines if open_line(x)] or [x for x in lines if not x.get("parked")]
    picking = _earliest(pending, "picking_day", "picking_provisional")
    due = _earliest(pending, "priority_day", "priority_provisional")
    return {
        "lines": len(lines),
        "ofs": len({x["of"] for x in lines}),
        "pieces": round(sum(x["pieces"] or 0 for x in lines)),
        "unknown_balances": sum(x.get('balance_unknown', False) for x in lines),
        "metres": round(metres, 1),
        # Linhas cujos metros não se sabem (sem saldo ou sem comprimento): não somam e contam-se aqui (08/10).
        "metres_unknown": sum(bool(x.get("metres_unknown", x.get("balance_unknown"))) for x in lines),
        # Linhas possivelmente repetidas (F06, 08/10): as cópias a mais e os metros que somam a mais.
        "repeated": {"lines": sum(1 for x in lines if x.get("repeat_extra")),
                     "metres": round(sum(x["metres"] for x in lines if x.get("repeat_extra")), 1)},
        "metres_without_machine": round(sum(x["metres"] for x in lines if not x["machine"]), 1),
        "pieces_without_machine": round(sum(x["pieces"] or 0 for x in lines if not x["machine"])),
        "tonnes": round(sum(x["kg"] for x in lines if x.get("kg") is not None) / 1000, 2),
        "weight_unknown": sum(x.get("kg") is None for x in lines),
        "status": {code: {"lines": s["lines"], "metres": round(s["metres"], 1), "pieces": round(s["pieces"]), "ofs": len(s["ofs"]),
                          "tonnes": round(s["kg"] / 1000, 2), "weight_unknown": s["kg_unknown"]}
                   for code, s in status.items()},
        "earliest_cut_date": min(cut_dates) if cut_dates else None,
        "earliest_priority_day": min(priority_days) if priority_days else None,
        "earliest_open_cut": min((x["cut_date"] for x in pending if x["cut_date"]), default=None),
        "earliest_open_picking": picking["day"], "earliest_open_picking_provisional": picking["provisional"],
        # Prazo da política das linhas com saldo (MTG2 sem Picking: Semana escolhida → Galvanização → Data Corte).
        "earliest_open_due": due["day"], "earliest_open_due_field": due["field"], "earliest_open_due_provisional": due["provisional"],
        "only_parked": bool(lines) and all(x.get("parked") for x in lines),
        "windows": {k: round(windows.get(k, 0.0), 1) for k in WINDOWS},
        "window_lines": {k: window_lines.get(k, 0) for k in WINDOWS},
        "machines": [{"machine": m, "metres": round(v, 1)} for m, v in sorted(by_machine.items(), key=lambda kv: -kv[1])[:4]],
        "signals": dict(signals),
        "priority": min(priorities) if priorities else None,
        "written_weeks": sorted({x["signals"]["entrega_escrita"] for x in lines if x["signals"]["entrega_escrita"]}),
        "customers": sorted({x["customer"] for x in lines})[:3],
        "designation": next((x["designation"] for x in lines if x["designation"]), ""),
        "states": {k: round(by_state.get(k, 0.0), 1) for k in STATES},
        "state_counts":dict(state_counts),
        "pending_following_operations":sum(x.get('pending_following_operations',0) for x in lines),
        "proposed_metres": round(sum(x["metres"] for x in lines if x["proposal"]), 1),
    }


def open_line(line: dict) -> bool:
    """Linha com saldo de corte (> 0 ou por confirmar) e não estacionada: a que conta para a data do grupo."""
    return not line.get("parked") and (line["pieces"] is None or line["pieces"] > 0)


def _earliest(lines: list[dict], field: str, provisional: str) -> dict:
    """{day, field, provisional} da data mais antiga em `field`. Provisória só quando todas as linhas desse dia
    o são (uma com o ano confirmado confirma a data)."""
    days = [x[field] for x in lines if x.get(field)]
    if not days:
        return {"day": None, "field": None, "provisional": False}
    day = min(days)
    first = [x for x in lines if x.get(field) == day]
    source = first[0].get("priority_field") if field == "priority_day" else "picking"
    return {"day": day, "field": source, "provisional": all(x.get(provisional) for x in first)}


def _urgency(group: dict):
    # Janela pelas linhas e não pelos metros (F10, 08/10): um grupo de 0 m (sem comprimento, saldo por confirmar)
    # ia para o fim da lista. `window_lines` falta em resumos antigos guardados: aí ficam os metros.
    counts = group.get("window_lines") or group["windows"]
    rank = min((list(WINDOWS).index(w) for w, n in counts.items() if n > 0), default=len(WINDOWS))
    priority = group["priority"] if group["priority"] is not None else 99
    return (priority, rank, group.get("earliest_priority_day") or group["earliest_cut_date"] or date.max, -group["metres"], group["key"])


def by_date(group: dict, order: str, today: date) -> tuple[tuple, dict]:
    """(chave, etiqueta) de um grupo nas ordens por data (P6, 08/10).

    corte:   (0, Data Corte) | (2) sem data | (3) só estacionadas
    picking: (0, Picking) | (1, prazo da política) sem Picking | (2) sem data | (3) só estacionadas
    Desempate: mais metros primeiro, depois a chave. Crescente: as atrasadas à frente, a mais antiga primeiro.
    A etiqueta diz o dia (ou a semana, no Picking e na Semana escolhida), se está atrasada e se é provisória.
    """
    if order == "corte" and group["earliest_open_cut"]:
        rank, day, field, provisional = 0, group["earliest_open_cut"], "cut_date", False
    elif order == "picking" and group["earliest_open_picking"]:
        rank, day, field, provisional = 0, group["earliest_open_picking"], "picking", group["earliest_open_picking_provisional"]
    elif order == "picking" and group["earliest_open_due"]:
        rank, day = 1, group["earliest_open_due"]
        field, provisional = group["earliest_open_due_field"], group["earliest_open_due_provisional"]
    else:
        rank = 3 if group["only_parked"] else 2
        return (rank, date.max, -group["metres"], group["key"]), {"none": "estacionada" if rank == 3 else "sem data"}
    if field in ("picking", "planned_period"):
        # Campo de semana (E2-02): atrasado = semana anterior à atual, contado a partir do domingo dessa semana.
        late = (today - (day + timedelta(days=6 - day.weekday()))).days
    else:
        late = (today - day).days
    tag = {"day": day, "field": field, "late": late > 0, "late_days": max(late, 0), "provisional": bool(provisional)}
    if field in ("picking", "planned_period"):
        tag["week"] = iso_week(day)
    return (rank, day, -group["metres"], group["key"]), tag


def line_date_key(line: dict, order: str) -> tuple:
    """Ordem das linhas da lupa nas ordens por data, pelas mesmas regras do grupo."""
    if line.get("parked"):
        return (3, date.max)
    pending = open_line(line)
    if order == "picking" and pending and line.get("picking_day"):
        return (0, line["picking_day"])
    if order == "picking" and pending and line.get("priority_day"):
        return (1, line["priority_day"])
    if order == "corte" and pending and line["cut_date"]:
        return (0, line["cut_date"])
    return (2, line["cut_date"] or date.max)


def check_path(view: str, path) -> tuple:
    if view not in VIEWS:
        raise planning.PlanningError("Vista inválida.")
    levels = VIEWS[view]
    if not isinstance(path, list) or not all(isinstance(p, str) for p in path) or len(path) > len(levels):
        raise planning.PlanningError("Grupo inválido.")
    return levels


def group_lines(data: dict, view: str, path: list[str]) -> list[dict]:
    """Todo o grupo identificado pelo setor, vista e caminho — sem filtros da lista (o universo da lupa)."""
    lines = data["lines"]
    for level, key in zip(check_path(view, path), path):
        lines = [x for x in lines if x[level] == key]
    return lines


def groups(sector: str, view: str = "referencia", path: list[str] | None = None, filters: dict | None = None,
           sort: str = "urgencia", limit: int = 500, *, data: dict | None = None, decisions: dict | None = None) -> dict:
    """Groups at the level below `path` for the chosen view, with the list subtotal.

    `list_totals` (e o antigo `totals`, mantido igual por compatibilidade) descreve só a lista filtrada;
    o resumo do setor vem de portfolio_kpis e não depende destes filtros. `member_total` conta o grupo
    completo (sem filtros): é o denominador da contagem 17/18.
    """
    levels = check_path(view, list(path or []))
    path = list(path or [])
    if len(path) >= len(levels):
        raise planning.PlanningError("Não há mais níveis nesta vista.")
    check_order(sector, sort)
    data = data or current(sector)
    filters = filters or {}
    check_estado(filters.get("estado"))
    universe = group_lines(data, view, path)
    selected = [x for x in universe if matches(x, filters, decisions)]
    level = levels[len(path)]
    buckets = defaultdict(list)
    for x in selected:
        buckets[x[level]].append(x)
    totals = defaultdict(int)
    for x in universe:
        if x[level] in buckets:
            totals[x[level]] += 1
    result = [{"key": k, **_summary(v, decisions), "member_total": totals[k]} for k, v in buckets.items()]
    if sort in DATE_ORDERS:
        keyed = []
        for g in result:
            key, g["due_tag"] = by_date(g, sort, data["today"])
            keyed.append((key, g))
        result = [g for _, g in sorted(keyed, key=lambda kg: kg[0])]
    else:
        result.sort(key=_urgency if sort == "urgencia" else (lambda g: (-g["metres"], g["key"])))
    subtotal = _summary(selected, decisions)
    # Produção acima da QTD (F07, 08/10): as linhas da lista e as que já saíram da Carteira por isso, com os filtros.
    done = [x for x in group_lines({"lines": data.get("excess_done") or []}, view, path) if matches(x, filters, decisions)]
    excess = [x for x in selected if x.get("production_excess")] + done
    subtotal["production_excess"] = {"lines": len(excess), "pieces": round(sum(x["production_excess"] for x in excess)),
                                     "closed": len(done)}
    from . import drive_notice
    return {
        # Excel do setor no Drive mais recente do que o importado (F16, 08/10): uma linha de aviso, só no nível de cima.
        "source_notice": None if path else drive_notice.text(sector),
        "sector": sector, "sector_label": SECTORS[sector], "view": view, "levels": [{"id": l, "label": LEVELS[l]} for l in levels],
        "level": {"id": level, "label": LEVELS[level]}, "path": path, "has_children": len(path) + 1 < len(levels),
        "generation": data["generation"], "snapshot": data["snapshot"], "imported_at": data["imported_at"], "today": data["today"], "stale": bool(data.get("stale")),
        "list_totals": subtotal, "totals": subtotal, "groups": result[:limit], "truncated": len(result) > limit, "group_count": len(result),
        # Eco da ordem e o que esta versão sabe (P6, 08/10): o ecrã só mostra as datas quando vê isto.
        "order": sort, "capabilities": {"ordem_data": True},
        "windows": WINDOWS, "signals": SIGNALS, "states": STATES, "status": STATUS,
        "rules": {
            "saldo": "Saldo por operação segundo a reconciliação comum; sobreposições por resolver ficam desconhecidas. O saldo documental conserva a origem. Concluir a primeira operação não encerra as seguintes.",
            "modelo": "Referência mestre = código do modelo no início da referência (ED4T40 → ED4, DLT319 → DLT, 1283V053 → 1283).",
            "semana": "Semana ISO do prazo do setor: MTG3 pela Data Corte; MTG2 pelo Picking com ano confirmado, depois Galvanização e Data Corte. Sem prazo fica em «Sem semana definida».",
            "familias": "Família SKU vem do catálogo versionado de referências (por exemplo M1, M2); Família de Produto é o tipo de obra do CPIS. São dimensões diferentes.",
            "estado": "Planeado = Planear e Máquina; Planeado para nesting = tem Máquina, ainda sem Planear; Sem máquina atribuída = coluna Máquina vazia. Cada linha tem um só estado. Planear numa linha sem máquina usa a máquina sugerida (podes mudar).",
            "selecao": "As caixas de seleção são um rascunho desta sessão e deste setor; filtrar, pesquisar, ordenar ou mudar a vista não as altera. Planear e Limpar gravam só os membros marcados dessa linha (ou o grupo inteiro, se nenhum estiver marcado).",
        },
    }


def member_token(line: dict, revision: int) -> str:
    """Muda quando a variante técnica, o saldo, a máquina ou a decisão do membro mudam."""
    return needs.digest([line["signature"], line["pieces"], line["machine"], revision])[:16]


def member_view(line: dict, decisions: dict | None) -> dict:
    found = effective(line, decisions)
    status = planning_status.classify(found, line["machine"])
    return {
        "key": line["key"], "of": line["of"], "reference": line["reference"], "profile": line["profile"],
        "length_mm": line["length_mm"], "quantity": line["quantity"], "pieces": line["pieces"],
        # Metros desconhecidos vão como None (08/10): a lupa mostra «—», nunca «0 m».
        "metres": None if line.get("metres_unknown") else round(line["metres"], 2),
        "metres_unknown": bool(line.get("metres_unknown", line["balance_unknown"])),
        "balance_unknown": line["balance_unknown"], "machine": line["machine"],
        "machine_source": line.get("machine_source"), "tabela_machine": line.get("tabela_machine"),
        "sku_family": line.get("sku_family"),
        "kg": round(line["kg"], 1) if line.get("kg") is not None else None,
        "cut_date": line["cut_date"], "priority_day": line["priority_day"], "iso_week": line.get("iso_week"),
        "designation": line["designation"], "customer": line["customer"], "status": status,
        "decision": found["decision"], "decision_source": found["source"],
        "revision": found["revision"], "token": member_token(line, found["revision"]),
        "pending_following_operations": line.get("pending_following_operations", 0),
        # Avisos da lupa (08/10): «repetida n×», «produção acima da QTD», «Abocardar: N» quando só falta essa operação.
        "repeated": line.get("repeated"), "production_excess": line.get("production_excess"),
        "following": line.get("following"),
    }


def group_seal(lines: list[dict], decisions: dict | None) -> str:
    return needs.digest(sorted((x["key"], member_token(x, effective(x, decisions)["revision"])) for x in lines))[:24]


def members(sector: str, view: str, path: list[str], *, cursor: int = 0, limit: int = 200, q: str | None = None,
            filters: dict | None = None, data: dict | None = None, decisions: dict | None = None, learned: dict | None = None,
            checked: dict | None = None, suggest=None, sort: str | None = None) -> dict:
    """Membros exatos de um grupo, com o total integral e todas as chaves.

    `keys` traz sempre todas as chaves do grupo (para «selecionar todos» nunca ficar limitado à página);
    `items` é paginado. `q` pesquisa dentro do grupo sem mudar o total; `filters` só marca quais membros
    estão visíveis na lista. `suggest(linhas) -> {chave: sugestão}`: a máquina que o Planear gravaria
    (selection.suggested_machines, 07/10/2026); sem ele, a preferência aprendida (`learned`, `checked`).
    `sort`: nas ordens por data a lupa segue a data da lista (P6, 08/10); nas outras, por OF e referência.
    """
    if sort is not None:
        check_order(sector, sort)
    data = data or current(sector)
    if not path:
        raise planning.PlanningError("Escolhe um grupo da Carteira.")
    universe = group_lines(data, view, path)
    if not universe:
        raise planning.PlanningError("Esse grupo já não tem trabalho aberto. Atualiza a Carteira.", 409)
    by_line = (lambda x: line_date_key(x, sort)) if sort in DATE_ORDERS else (lambda x: ())
    universe = sorted(universe, key=lambda x: (*by_line(x), x["of"], x["reference"], x["profile"], x["length_mm"] or 0, x["key"]))
    shown = universe
    text = (q or "").strip().upper()
    if text:
        shown = [x for x in universe if text in " ".join((x["of"], x["reference"], x["profile"], x["designation"])).upper()]
    try:
        cursor, limit = max(0, int(cursor)), min(max(1, int(limit)), 1000)
    except (TypeError, ValueError):
        raise planning.PlanningError("Página inválida.") from None
    visible = {x["key"] for x in universe if matches(x, filters or {}, decisions)} if filters else None
    from .machine_learning import for_line
    page = shown[cursor:cursor + limit]
    found = suggest([x for x in page if not x["machine"]]) if suggest else None
    # `checked`: preferência já filtrada pela ficha técnica (machine_learning.technical, PROP-2).
    items = [{**member_view(x, decisions), "visible": visible is None or x["key"] in visible,
              "suggested": None if x["machine"] else found.get(x["key"]) if found is not None else for_line(learned, checked, x)}
             for x in page]
    statuses = [planning_status.classify(effective(x, decisions), x["machine"]) for x in universe]
    return {
        "sector": sector, "view": view, "path": path, "order": sort, "total": len(universe), "matching": len(shown),
        "keys": [x["key"] for x in universe],
        "tokens": [member_token(x, effective(x, decisions)["revision"]) for x in universe], "items": items,
        "next_cursor": cursor + limit if cursor + limit < len(shown) else None,
        "generation": data["generation"], "stale": bool(data.get("stale")), "seal": group_seal(universe, decisions),
        **{code: sum(s[code] for s in statuses) for code in STATUS},
        "hidden_by_filters": len(universe) - len(visible) if visible is not None else 0,
        # O servidor aceita o grupo inteiro como membros com token («todo_o_grupo», 07/10/2026): a Carteira só o
        # manda assim quando vê isto, para nunca o mandar a uma versão que não respeite as exclusões do grupo.
        "todo_o_grupo": True,
    }


def counts(sector: str, view: str, path: list[str], keys, filters: dict | None = None, *,
           data: dict | None = None, decisions: dict | None = None) -> dict:
    """Quantos membros de cada grupo deste nível estão na seleção (rascunho), sobre o grupo completo."""
    if path is not None and not isinstance(path, list):
        raise planning.PlanningError("Grupo inválido.")
    levels = check_path(view, list(path or []))
    path = list(path or [])
    if len(path) >= len(levels):
        raise planning.PlanningError("Não há mais níveis nesta vista.")
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise planning.PlanningError("Seleção inválida.")
    data = data or current(sector)
    chosen = set(keys)
    level = levels[len(path)]
    result = defaultdict(lambda: {"selected": 0, "total": 0, "hidden_selected": 0})
    for x in group_lines(data, view, path):
        group = result[x[level]]
        group["total"] += 1
        if x["key"] in chosen:
            group["selected"] += 1
            if filters and not matches(x, filters, decisions):
                group["hidden_selected"] += 1
    known = {x["key"] for x in data["lines"]}
    return {"groups": dict(result), "unknown_keys": sorted(chosen - known)[:50], "unknown_count": len(chosen - known)}


def keys_from(payload: dict) -> list[str]:
    """Chaves de uma consulta: lista simples ou compacta por prefixo comum ({prefixo: [sufixos]}).

    As chaves de uma importação partilham o prefixo (macro:<importação>:plan:); a forma compacta deixa
    consultar milhares de membros dentro do limite de tamanho dos pedidos.
    """
    keys = payload.get("chaves")
    compact = payload.get("chaves_compactas")
    if keys is None and compact is None:
        return []
    if keys is not None and (not isinstance(keys, list) or not all(isinstance(k, str) for k in keys)):
        raise planning.PlanningError("Seleção inválida.")
    if compact is not None and (not isinstance(compact, dict) or not all(
            isinstance(v, list) and all(isinstance(x, str) for x in v) for v in compact.values())):
        raise planning.PlanningError("Seleção inválida.")
    return list(keys or []) + [prefix + suffix for prefix, suffixes in (compact or {}).items() for suffix in suffixes]


def weeks(sector: str, *, data: dict | None = None) -> list[dict]:
    """Semanas ISO com trabalho aberto do setor, por ano e semana; «Sem semana definida» no fim."""
    data = data or current(sector)
    found = defaultdict(lambda: {"lines": 0, "metres": 0.0})
    for x in data["lines"]:
        w = found[week_code(x)]
        w["lines"] += 1
        w["metres"] += x["metres"]
    result = []
    for code in sorted(k for k in found if k not in (NO_WEEK, PARKED_WEEK)):
        year, week = int(code[:4]), int(code[6:])
        start = date.fromisocalendar(year, week, 1)
        end = start + timedelta(days=6)
        result.append({"code": code, "year": year, "week": week, "start": start, "end": end,
                       "label": f"{year} · S{week:02d} · {start:%d/%m}–{end:%d/%m}",
                       "lines": found[code]["lines"], "metres": round(found[code]["metres"], 1)})
    if NO_WEEK in found:
        result.append({"code": NO_WEEK, "year": None, "week": None, "start": None, "end": None, "label": "Sem semana definida",
                       "lines": found[NO_WEEK]["lines"], "metres": round(found[NO_WEEK]["metres"], 1)})
    if PARKED_WEEK in found:
        result.append({"code": PARKED_WEEK, "year": None, "week": None, "start": None, "end": None,
                       "label": WINDOWS["estacionada"], "lines": found[PARKED_WEEK]["lines"],
                       "metres": round(found[PARKED_WEEK]["metres"], 1)})
    return result


def week_code(line: dict) -> str:
    """Código da semana do filtro: a semana ISO do prazo, «estacionada» ou «sem»."""
    return line.get("iso_week") or (PARKED_WEEK if line.get("parked") else NO_WEEK)


def families(sector: str, *, data: dict | None = None) -> list[dict]:
    data = data or current(sector)
    seen = {}
    for x in data["lines"]:
        if x["family_code"]:
            seen[x["family_code"]] = x["family"]
    return [{"code": k, "label": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1])]


def sku_families(sector: str, *, data: dict | None = None) -> list[dict]:
    data = data or current(sector)
    counts = defaultdict(int)
    states = {}
    for x in data["lines"]:
        counts[x["sku_family"]] += 1
        states[x["sku_family"]] = x["sku_family_status"]
    return [{"code": k, "label": k, "status": states[k], "lines": n} for k, n in sorted(counts.items())]


def machines(sector: str, *, data: dict | None = None) -> list[str]:
    data = data or current(sector)
    return sorted({x["machine"] for x in data["lines"] if x["machine"]})
