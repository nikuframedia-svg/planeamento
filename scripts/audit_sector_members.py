"""Medição só de leitura (06/10/2026): máquinas de cada setor pela regra antiga e pela nova.

Antiga (settings.machine_rows até 06/10): catálogo (unidade + tipo) OU qualquer calendário gravado com a
área do setor. Nova (app/sector/members.py): só o catálogo de recursos (unidade MTG2/MTG3 e tipo
máquina/posto). Para cada máquina que muda mostra calendários por área e se tem trabalho no setor.
Uso: .venv/bin/python scripts/audit_sector_members.py
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_readonly import planning_db  # noqa: E402


def main():
    from app.sector.occurrences import resources_context, load
    from app.sector.portfolio_kpis import catalog
    from app.sector.settings import UNIT
    with planning_db() as c:
        codes, by_id, _, configs, _ = resources_context(c)
        cal_area = Counter((str(cfg["definition"].get("resource_id")), cfg.get("area")) for cfg in configs if cfg["kind"] == "calendar")
        for sector in ("perfis", "cantoneiras"):
            info = catalog(c, sector)
            new = {rid for rid, r in by_id.items()
                   if (info.get(r.get("code")) or {}).get("unit") == UNIT[sector] and (info.get(r.get("code")) or {}).get("type") in ("maquina", "posto")}
            old = new | {rid for (rid, area) in cal_area if area == sector and rid in by_id}
            facts = Counter(f["planning_resource_id"] for f in load(sector, allow_stale=True)["facts"] if f.get("planning_resource_id"))
            print(f"\n== {sector}: antiga {len(old)} · nova {len(new)}")
            for rid in sorted(old | new, key=lambda x: by_id[x].get("name") or x):
                r = by_id[rid]
                meta = info.get(r.get("code")) or {}
                tag = "fica" if rid in old and rid in new else "SAI" if rid in old else "ENTRA"
                cals = {a: n for (x, a), n in cal_area.items() if x == rid}
                print(f"  {tag:5} {r.get('name')!s:42} código={r.get('code')!s:16} unidade={meta.get('unit')} tipo={meta.get('type')} "
                      f"calendários={cals} operações_do_setor={facts.get(rid, 0)}")
            outside = {rid: n for rid, n in facts.items() if rid not in new}
            if outside:
                print("  Operações deste setor em máquinas fora do setor:",
                      {(by_id.get(rid) or {}).get("name", rid): n for rid, n in outside.items()})


if __name__ == "__main__":
    main()
