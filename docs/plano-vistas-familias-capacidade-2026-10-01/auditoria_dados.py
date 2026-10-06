"""Auditoria só de leitura: os números das páginas batem certo entre si e com os registos?"""
import json, sys
from collections import Counter, defaultdict
from app.sector import occurrences, workbench, portfolio, selection, capacity
from app import planning_needs as needs

problems, notes = [], []
def check(ok, msg):
    (notes if ok else problems).append(("OK  " if ok else "FALHA ") + msg)

panel = workbench.overview(None, "mediana")
machines = {(m["area"], m["resource_id"]): m for m in panel["machines"]}
for area in ("perfis", "cantoneiras"):
    d = occurrences.load(area, allow_stale=True)
    facts = d["facts"]
    keys = Counter(f["key"] for f in facts)
    check(max(keys.values()) == 1, f"{area}: {len(facts)} ocorrências, chaves únicas")
    neg = [f for f in facts if (f.get("remaining") or 0) < 0 or (f.get("hours") or 0) < 0]
    check(not neg, f"{area}: sem saldos/horas negativos ({len(neg)})")
    over = [f for f in facts if f.get("remaining") is not None and f.get("quantity_required") is not None and f["remaining"] > f["quantity_required"] + 1e-9]
    check(not over, f"{area}: saldo nunca acima do pedido ({len(over)} casos)")
    badm = [f for f in facts if f.get("length_mm") and f.get("pieces") and f.get("metres") is not None
            and abs(f["metres"] - f["length_mm"] * f["pieces"] / 1000) > 0.01]
    check(not badm, f"{area}: metros = comprimento × peças ({len(badm)} diferenças)")
    # Carga por máquina (página Máquinas) = soma das horas das ocorrências dessa máquina
    load = defaultdict(float); n = Counter()
    for f in facts:
        rid = capacity._res(f)
        if rid and capacity._load(f):
            load[rid] += capacity._load(f); n[rid] += 1
    for (a, rid), m in machines.items():
        if a != area: continue
        diff = abs(m["load_hours"] - load.get(rid, 0))
        check(diff < 0.5, f"{area}: {m['name']}: painel {m['load_hours']:.1f} h vs ocorrências {load.get(rid,0):.1f} h")
        if m["weekly_capacity_hours"]:
            w = m["load_hours"] / m["weekly_capacity_hours"]
            check(abs(w - (m["weeks"] or 0)) < 0.11, f"{area}: {m['name']}: semanas {m['weeks']} = {m['load_hours']:.0f}/{m['weekly_capacity_hours']:.1f}")
    lost = {rid for rid in load if (area, rid) not in machines and load[rid] > 0.5}
    check(not lost, f"{area}: todas as máquinas com carga aparecem no painel (em falta: {[ (rid, round(load[rid],1)) for rid in lost]})")
    # Sugestões
    sugg = [f for f in facts if f.get("machine_basis") == "sugerida"]
    groups = [g for g in panel["suggestions"] if g["area"] == area]
    check(sum(g["occurrences"] for g in groups) == len(sugg), f"{area}: sugestões {len(sugg)} ocorrências = soma dos lotes")
    assigned = [f for f in sugg if f.get("assigned_resource_id")]
    check(not assigned, f"{area}: nenhuma sugestão em trabalho que já tem máquina no Excel ({len(assigned)})")
    by_key = {f["key"]: f for f in facts}
    # Equilíbrio: nunca move trabalho iniciado nem decisões «assign»
    for p in [p for p in panel["rebalance"] if p["area"] == area]:
        fs = [by_key.get(k) for k in p["keys"]]
        check(all(fs), f"{area}: proposta {p['of']} tem chaves válidas")
        fs = [f for f in fs if f]
        cur = {capacity._res(f) for f in fs}
        check(cur == {p["from_id"]}, f"{area}: proposta {p['of']} {p['from']}→{p['to']} sai da máquina atual")
        started = [f for f in fs if (f.get("remaining") or 0) < (f.get("quantity_required") or 0)]
        check(not started, f"{area}: proposta {p['of']} não mexe em trabalho iniciado ({len(started)})")
        dec = [f for f in fs if (f.get("decision") or {}).get("mode") == "assign"]
        check(not dec, f"{area}: proposta {p['of']} não mexe em decisões gravadas ({len(dec)})")
    # Carteira: total pendente da vista coincide com as ocorrências
    try:
        cart = needs.serial(portfolio.groups(area, "referencia", [], {}, "urgencia", decisions=selection.current(area)))
        notes.append(f"info {area}: carteira chaves {list(cart.keys())[:12]}")
        json.dump(cart.get("summary") or cart.get("totals") or {}, sys.stdout, default=str, ensure_ascii=False); print()
        metres = sum(f.get("metres") or 0 for f in facts if (f.get("remaining") or 0) > 0)
        nomac = sum(f.get("metres") or 0 for f in facts if (f.get("remaining") or 0) > 0 and not f.get("assigned_resource_id"))
        notes.append(f"info {area}: ocorrências pendentes {metres/1000:.1f} km, sem máquina no Excel {nomac/1000:.1f} km ({100*nomac/max(metres,1):.0f}%)")
    except Exception as e:
        problems.append(f"FALHA {area}: carteira rebentou: {e!r}")
print("\n".join(notes)); print("\n".join(problems) or "Sem falhas.")
print(f"\n{len(notes)} verificações/infos, {len(problems)} falhas")
