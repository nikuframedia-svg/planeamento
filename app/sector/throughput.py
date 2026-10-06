"""Débito observado e velocidades por máquina, a partir do Excel e do MES (estudo de 01/10/2026).

Três medidas diferentes, nunca misturadas:

1. **Débito semanal MTG3 (Excel):** cada linha de `Plan_ produção` com o `dia` de produção, a máquina,
   os metros produzidos e as horas teóricas trabalhadas (`h teor. Trab` = metros ÷ `Mt\\h`). Soma por
   máquina e semana ISO completa. É o trabalho **executado**, na mesma unidade das horas da carteira
   (horas teóricas à velocidade do Excel), já com as perdas habituais. Não é capacidade nominal: uma
   semana com pouca procura executa menos do que a máquina permitiria.
2. **Horas e metros declarados no MES** por folha (máquina × dia), normalizados na camada v2. Medem o
   rendimento real (metros por hora trabalhada) e as horas trabalhadas por dia, com poucos meses.
3. **Velocidades do Excel** (`Mt\\h`) por máquina e perfil, para estimar a carga de linhas sem máquina
   ou sem velocidade, depois de escolhida uma máquina.

Datas múltiplas («20+21/08») ou ilegíveis ficam fora e contadas; semanas sem registo dentro do período
ativo contam como zero observado, não como paragem comprovada.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import nullcontext
from datetime import date, timedelta
import math
import re
import threading

from .. import planning

WEEKS = 16
_cache: dict = {}
_lock = threading.Lock()
_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")


def number(value):
    try:
        n = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def production_day(value):
    """One explicit production day, or (None, reason). Never guesses among several days."""
    if value in (None, ""):
        return None, "sem_data"
    text = str(value).strip()
    if "+" in text:
        return None, "varias_datas"
    try:
        day = date.fromisoformat(text[:10])
    except ValueError:
        match = _DMY.match(text)
        if not match:
            return None, "data_ilegivel"
        d, m, y = (int(x) for x in match.groups())
        try:
            day = date(y + 2000 if y < 100 else y, m, d)
        except ValueError:
            return None, "data_ilegivel"
    if day.year < 2000:
        return None, "data_zero_excel"
    return day, None


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    at = (len(values) - 1) * p
    lo, hi = math.floor(at), math.ceil(at)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def weighted_median(pairs):
    """Median of values weighted by counts (pairs value → count)."""
    items = sorted(pairs.items())
    total = sum(n for _, n in items)
    if not total:
        return None
    seen = 0
    for value, n in items:
        seen += n
        if seen * 2 >= total:
            return value
    return items[-1][0]


def weekly_mtg3(rows, *, until: date, weeks: int = WEEKS):
    """Executed metres and theoretical hours per machine and complete ISO week."""
    last_monday = until - timedelta(days=until.weekday()) - timedelta(days=7)  # last complete week
    first_monday = last_monday - timedelta(weeks=weeks - 1)
    cells = defaultdict(lambda: {"metres": 0.0, "hours": 0.0, "lines": 0, "orders": set()})
    excluded = Counter()
    for r in rows:
        machine = str(r.get("Máquina Corte") or "").strip()
        metres = number(r.get("m prod."))
        if not machine or not metres or metres <= 0:
            continue
        day, reason = production_day(r.get("dia"))
        if reason:
            excluded[reason] += 1
            continue
        monday = day - timedelta(days=day.weekday())
        if not first_monday <= monday <= last_monday:
            continue
        hours = number(r.get("h teor. Trab"))
        speed = number(r.get("Mt\\h"))
        if hours is None and speed and speed > 0:
            hours = metres / speed
        cell = cells[(machine, monday)]
        cell["metres"] += metres
        cell["lines"] += 1
        cell["orders"].add(str(r.get("OF") or ""))
        if hours is None or hours < 0:
            excluded["horas_teoricas_desconhecidas"] += 1
        else:
            cell["hours"] += hours
    mondays = [first_monday + timedelta(weeks=i) for i in range(weeks)]
    machines = sorted({m for m, _ in cells})
    series = {}
    for machine in machines:
        active = [w for w in mondays if (machine, w) in cells]
        span = [w for w in mondays if active and active[0] <= w <= active[-1]]
        series[machine] = [{"week": w.isoformat(), "iso": f"{w.isocalendar()[0]}-W{w.isocalendar()[1]:02d}",
                            "metres": round(cells[(machine, w)]["metres"], 3) if (machine, w) in cells else 0.0,
                            "hours": round(cells[(machine, w)]["hours"], 3) if (machine, w) in cells else 0.0,
                            "lines": cells[(machine, w)]["lines"] if (machine, w) in cells else 0,
                            "orders": len(cells[(machine, w)]["orders"]) if (machine, w) in cells else 0,
                            "observed_zero": (machine, w) not in cells} for w in span]
    return {"window": {"from": first_monday.isoformat(), "to": (last_monday + timedelta(days=6)).isoformat(), "weeks": weeks},
            "series": series, "excluded": dict(excluded)}


def summarise(series):
    result = {}
    for machine, weeks in series.items():
        hours = [w["hours"] for w in weeks]
        metres = [w["metres"] for w in weeks]
        result[machine] = {"weeks": len(weeks), "zero_weeks": sum(w["observed_zero"] for w in weeks),
                           "hours_p25": quantile(hours, .25), "hours_median": quantile(hours, .5), "hours_p75": quantile(hours, .75),
                           "metres_p25": quantile(metres, .25), "metres_median": quantile(metres, .5), "metres_p75": quantile(metres, .75)}
        for k, v in result[machine].items():
            if isinstance(v, float):
                result[machine][k] = round(v, 2)
    return result


def speeds(rows):
    """Excel speed (m/h) by machine and by machine × profile, as weighted medians with sample size."""
    by_machine = defaultdict(Counter)
    by_profile = defaultdict(Counter)
    for r in rows:
        machine = str(r.get("Máquina Corte") or "").strip()
        speed = number(r.get("Mt\\h"))
        if not machine or not speed or speed <= 0:
            continue
        by_machine[machine][speed] += 1
        profile = re.sub(r"\s", "", str(r.get("Tipo de perfil") or "").upper())
        if profile:
            by_profile[(machine, profile)][speed] += 1
    return ({m: {"value": weighted_median(c), "lines": sum(c.values()), "values": dict(c.most_common(4))} for m, c in by_machine.items()},
            {k: {"value": weighted_median(c), "lines": sum(c.values())} for k, c in by_profile.items()})


def mes_rates(events):
    """Hours and metres declared per MES sheet (machine × day); one value per sheet, never per row."""
    sheets = {}
    for e in events:
        uid = e.get("folha_uid")
        if not uid:
            continue
        sheet = sheets.setdefault(uid, {"machine": e.get("recurso_codigo"), "sector": e.get("setor"), "day": e.get("data_producao"),
                                        "hours": set(), "metres": set()})
        if number(e.get("horas_reportadas")) is not None:
            sheet["hours"].add(number(e["horas_reportadas"]))
        if number(e.get("metros_reportados")) is not None:
            sheet["metres"].add(number(e["metros_reportados"]))
    per_machine = defaultdict(lambda: {"sheets": 0, "hours": [], "rates": [], "ambiguous": 0})
    for s in sheets.values():
        m = per_machine[(s["sector"], s["machine"])]
        m["sheets"] += 1
        if len(s["hours"]) > 1 or len(s["metres"]) > 1:
            m["ambiguous"] += 1
            continue
        hours = next(iter(s["hours"]), None)
        metres = next(iter(s["metres"]), None)
        # A shift is at most 24 h; larger values are misread text such as «7.30hs» → 730.
        if hours is not None and 0 < hours <= 24:
            m["hours"].append(hours)
            if metres and metres > 0:
                m["rates"].append(metres / hours)
    return {key: {"sheets": v["sheets"], "sheets_with_hours": len(v["hours"]), "ambiguous": v["ambiguous"],
                  "hours_per_sheet_median": round(quantile(v["hours"], .5), 2) if v["hours"] else None,
                  "metres_per_hour_median": round(quantile(v["rates"], .5), 1) if v["rates"] else None,
                  "metres_per_hour_p25": round(quantile(v["rates"], .25), 1) if v["rates"] else None,
                  "metres_per_hour_p75": round(quantile(v["rates"], .75), 1) if v["rates"] else None,
                  "rate_samples": len(v["rates"])} for key, v in per_machine.items()}


def load(conn=None) -> dict:
    """Current study, cached per workbook snapshot and research version."""
    from ..gantt import research
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        snap = planning.snapshot(c, "cantoneiras")
        version = research.head(c)["version_id"] if research.enabled() else None
        key = (snap["snapshot_id"], version)
        with _lock:
            cached = _cache.get("study")
        if cached and cached[0] == key:
            return cached[1]
        rows = [r["row_data"] for r in c.execute(
            "SELECT row_data FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s", (snap["snapshot_id"],)).fetchall()]
        loaded = snap.get("loaded_at")
        until = date.fromisoformat(str(loaded)[:10]) if loaded else date.today()
        weekly = weekly_mtg3(rows, until=until)
        by_machine, by_profile = speeds(rows)
        events = research.load(c)["metadata"]["events"] if research.enabled() else []
    result = {"source": {"snapshot": snap["snapshot_id"], "loaded_at": str(loaded), "research_version": version},
              "weekly": weekly, "summary": summarise(weekly["series"]), "speeds": by_machine,
              "profile_speeds": by_profile, "mes": mes_rates(events)}
    with _lock:
        _cache["study"] = (key, result)
    return result


def aliases_to_names(resources):
    """Resource id → Excel machine names that refer to it (aliases of the cantoneiras area)."""
    result = defaultdict(set)
    for rid, r in resources.items():
        result[rid].add(r.get("name"))
        for a in r.get("aliases") or []:
            if a.get("area") == "cantoneiras":
                result[rid].add(a.get("name"))
    return result
