"""Máquina por grupo (plano de 01/10/2026, secção 6).

O menu abre numa família, perfil, conjunto, referência ou operação. A escolha em grupo é resolvida
ocorrência a ocorrência: cada ocorrência conserva a sua elegibilidade técnica, as suas condições e,
se já começou, a máquina da execução.

Modos:
- assign: atribuição manual; mantém a escolha e expõe os impedimentos (o Gantt bloqueia se for
  incompatível, em vez de mudar silenciosamente para outra máquina);
- prefer: preferência; o Gantt usa-a se for utilizável, senão volta ao automático com explicação;
- automatic: retira as decisões do grupo (só as do mesmo nível ou menos específicas);
- future_preference: guarda o seletor (referência, conjunto congelado, família SKU, grupo de perfis)
  e a vigência, para trabalho que ainda não existe;
- undo: nova ação que repõe o estado anterior das ocorrências que ninguém mudou depois.

Precedência no Gantt: trabalho iniciado → escolha do cenário → decisão da ocorrência →
preferência por referência → conjunto → família SKU → grupo de perfis → automático.
Cada gravação é uma transação com `request_id` idempotente; a pré-visualização devolve um selo
que a gravação confere (409 se a carteira mudou entretanto).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timezone
import threading
import uuid

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs

MODES = ("assign", "prefer", "automatic", "future_preference", "accept_suggestions", "assign_each")
SELECTOR_KINDS = {"reference": 4, "set": 3, "sku_family": 2, "profile_group": 1}
SELECTOR_LABELS = {"reference": "referência", "set": "conjunto", "sku_family": "família SKU", "profile_group": "grupo de perfis"}
STATUS = {
    "admissivel": "Admissível",
    "condicional": "Condicional (condições por confirmar)",
    "incompativel": "Incompatível ou sem alternativa documental",
    "iniciada": "Já iniciada · conserva a máquina da execução",
    "excecao": "Decisão mais específica mantida",
    "atual": "Já com esta escolha",
    "sem_sugestao": "Sem máquina sugerida (já atribuída ou sem candidata)",
}
EXPLICIT_LEVEL = 9


def occurrence_key(row: dict) -> str:
    return "|".join(str(row.get(k) if row.get(k) is not None else "") for k in
                    ("ordem_codigo", "referencia_original", "operacao_codigo", "ocorrencia"))


def split_key(key: str):
    """(OF, reference, operation, occurrence); a reference may itself contain «|»."""
    of, rest = key.split("|", 1)
    reference, operation, occurrence = rest.rsplit("|", 2)
    return of, reference, operation, occurrence


def profile_group(material, profile) -> str:
    return f"{material or 'Sem tipo'} · {(str(profile or '').strip() or 'Sem perfil')}"


def _exists(c, table: str) -> bool:
    return bool(c.execute("SELECT to_regclass(%s) t", ("planning_mtg." + table,)).fetchone()["t"])


def digest(c) -> str:
    if not _exists(c, "sector_machine_decisions"):
        return needs.digest([])
    decisions = c.execute("SELECT area,occurrence_key,technical_signature,mode,resource_id,revision,action_id "
                          "FROM planning_mtg.sector_machine_decisions ORDER BY area,occurrence_key").fetchall()
    preferences = c.execute("SELECT id,selector,resource_id,valid_from,valid_until,archived "
                            "FROM planning_mtg.sector_machine_preferences ORDER BY id").fetchall()
    return needs.digest({"decisions": decisions, "preferences": preferences})


class Resolver:
    """In-memory view of the sector decisions used by the Gantt and by the needs view."""

    def __init__(self, decisions=(), preferences=(), families=None, sets=None, today=None):
        self.decisions = {(d["area"], d["occurrence_key"]): d for d in decisions}
        self.today = (today or date.today()).isoformat()
        self.preferences = [p for p in preferences if not p["archived"]
                            and (not p["valid_from"] or str(p["valid_from"]) <= self.today)
                            and (not p["valid_until"] or str(p["valid_until"]) >= self.today)]
        self.families = families or {}
        self.sets = sets or {}

    def lookup(self, area: str, row: dict, signature: str, candidates=None):
        d = self.decisions.get((area, occurrence_key(row)))
        if d:
            origin = ("Atribuição" if d["mode"] == "assign" else "Preferência") + f" do setor · {d['reason']}"
            base = {"resource_id": d["resource_id"], "origin": origin, "action_id": str(d["action_id"]),
                    "level": d["scope_level"], "revision": d["revision"], "source": "occurrence"}
            if d["technical_signature"] != signature:
                # Never transferred to another technical variant by resemblance of the code.
                return {**base, "mode": "stale",
                        "conflict": "Decisão de máquina gravada para outra variante técnica; rever no setor." if d["mode"] == "assign" else None,
                        "note": "Preferência gravada para outra variante técnica; não aplicada."}
            return {**base, "mode": d["mode"]}
        if not self.preferences:
            return None
        context = {"reference": row.get("referencia_original"),
                   "sku_family": self.families.get((area, row.get("referencia_original"))),
                   "profile_group": profile_group(row.get("material_type"), row.get("perfil"))}
        found = []
        for p in self.preferences:
            s = p["selector"]
            if p["area"] != area or (s.get("operation") and s["operation"] != row.get("operacao_codigo")):
                continue
            if s["kind"] == "set":
                if row.get("referencia_original") in self.sets.get(s["value"], ()):
                    found.append(p)
            elif context.get(s["kind"]) is not None and context[s["kind"]] == s["value"]:
                found.append(p)
        if not found:
            return None
        best = max(p["specificity"] + (0.5 if p["selector"].get("operation") else 0) for p in found)
        top = [p for p in found if p["specificity"] + (0.5 if p["selector"].get("operation") else 0) == best]
        if len({p["resource_id"] for p in top}) > 1:
            return {"mode": "conflict", "resource_id": None, "source": "preference",
                    "note": "Preferências com a mesma especificidade indicam máquinas diferentes; resolver no setor.",
                    "origin": "Conflito de preferências"}
        p = top[0]
        return {"mode": "prefer", "resource_id": p["resource_id"], "source": "preference", "preference_id": str(p["id"]),
                "origin": f"Preferência futura · {SELECTOR_LABELS[p['selector']['kind']]} {p['selector'].get('label') or p['selector']['value']} · {p['reason']}"}


def resolver(c, today=None) -> Resolver:
    if not _exists(c, "sector_machine_decisions"):
        return Resolver(today=today)
    decisions = c.execute("SELECT * FROM planning_mtg.sector_machine_decisions").fetchall()
    preferences = c.execute("SELECT * FROM planning_mtg.sector_machine_preferences WHERE NOT archived").fetchall()
    families, sets = {}, {}
    kinds = {p["selector"]["kind"] for p in preferences}
    if "sku_family" in kinds and _exists(c, "sku_family_mappings"):
        families = {(r["area"], r["sku"]): r["family"] for r in
                    c.execute("SELECT area,sku,family FROM planning_mtg.sku_family_mappings WHERE family IS NOT NULL").fetchall()}
    if "set" in kinds:
        ids = [uuid.UUID(p["selector"]["value"]) for p in preferences if p["selector"]["kind"] == "set"]
        for r in c.execute("""SELECT m.set_id,m.sku_literal FROM planning_mtg.sector_reference_set_members m
                JOIN planning_mtg.sector_reference_sets s ON s.id=m.set_id AND s.revision=m.revision
                WHERE s.id=ANY(%s) AND s.mode='frozen' AND NOT s.archived""", (ids,)).fetchall():
            sets.setdefault(str(r["set_id"]), set()).add(r["sku_literal"])
    return Resolver(decisions, preferences, families, sets, today)


# ------------------------------------------------------------------ alternatives

_index_cache: dict = {}
_index_lock = threading.Lock()


def _timing(c, data):
    from ..raw.productivity import sector_timing
    return sector_timing(c).get(data.get("area"))


def _evidence(c, data):
    """Candidate machines with the same rules as the Gantt (cached per research version)."""
    from ..gantt import machines, integrated
    from . import occurrences
    codes, by_id, _, configs, package = occurrences.resources_context(c)
    if not package:
        return None
    version = package["head"]["version_id"]
    local = [r for r in data["_rows"].values() if r.get("application_row_key")]
    key = (version, data["stamp"])
    with _index_lock:
        cached = _index_cache.get("index")
    if cached and cached[0] == key:
        index, templates = cached[1]
    else:
        index = machines.EvidenceIndex(package["metadata"], package["rows"] + local)
        templates = integrated._templates(package)
        with _index_lock:
            _index_cache["index"] = (key, (index, templates))
    from . import estimates, throughput
    # Horas pela mesma regra da Carteira e da Carga (estimates.hours_on), não pelo motor do Gantt (PROP-4).
    extra = data.get("_estimate_inputs") or {}
    hours = {"by_id": by_id, "names": throughput.aliases_to_names(by_id), "study": throughput.load(c),
             "rates": estimates.area_rates(package["metadata"]),
             "table": extra.get("table", [cfg for cfg in configs if cfg["kind"] == "rate"]), "timing": extra["timing"] if "timing" in extra else _timing(c, data)}
    return {"codes": codes, "by_id": by_id, "configs": configs, "index": index, "templates": templates, "hours": hours}


def alternatives(c, data, fact, evidence=None) -> list[dict]:
    """Every documentary alternative of one occurrence, with eligibility, conditions and hours.

    Auditoria 06/10 (PROP-4): as horas de cada máquina são as que a Carteira e a Carga mostrariam com essa
    máquina (horas documentais do saldo, senão a estimativa de estimates.py), para a previsão não prometer
    outras horas.
    """
    from . import estimates
    evidence = evidence or _evidence(c, data)
    row = data["_rows"].get(fact["key"])
    if not evidence or not row:
        return []
    result = []
    for candidate in evidence["index"].candidates(row, evidence["codes"]):
        rid = candidate.get("resource_id")
        resource = evidence["by_id"].get(rid) if rid else None
        hours, origin, reason = None, None, candidate.get("reasons") and "; ".join(candidate["reasons"]) or None
        if resource and (candidate["eligibility"] != "excluded" or rid in (fact["resource_id"], fact.get("planning_resource_id"))):
            hours, _, origin = estimates.hours_on(fact, rid, **evidence["hours"])
            if hours is None:
                excluded = candidate["eligibility"] == "excluded" and reason
                reason, origin = reason if excluded else origin or reason or "Duração por confirmar.", None
        result.append({"resource_id": rid, "resource_code": candidate["resource_code"],
                       "name": resource["name"] if resource else candidate["resource_code"],
                       "eligibility": candidate["eligibility"], "conditions": candidate.get("conditions", []),
                       "proposed_code": candidate["proposed_code"], "code_change": candidate.get("code_change", False),
                       "origin": candidate.get("origin"), "other_orders": candidate.get("other_orders"),
                       "hours": hours, "hours_origin": origin, "reason": reason})
    return result


# ------------------------------------------------------------------ group actions


def _scope(payload, data, sets):
    from . import tree
    scope = payload.get("scope") or {}
    keys = scope.get("keys")
    filters = tree.clean_filters(scope.get("filters"))
    if keys:
        if not isinstance(keys, list) or len(keys) > 50000 or any(not isinstance(k, str) for k in keys):
            raise planning.PlanningError("Seleção de ocorrências inválida.")
        wanted = set(keys)
        chosen = [f for f in data["facts"] if f["key"] in wanted]
        return chosen, EXPLICIT_LEVEL, {"keys": sorted(wanted), "filters": filters}
    dims = tree.dims_for(scope.get("preset"), scope.get("dims"))
    path = [str(p) for p in scope.get("path") or []]
    if not path and not filters:
        raise planning.PlanningError("Escolhe um grupo (família, perfil, conjunto, referência ou operação).")
    chosen = tree.select(data["facts"], dims, path, filters, sets)
    return chosen, max(1, min(8, len(path))), {"dims": dims, "path": path, "filters": filters}


def _current(c, area):
    return {r["occurrence_key"]: r for r in c.execute(
        "SELECT * FROM planning_mtg.sector_machine_decisions WHERE area=%s", (area,)).fetchall()}


def evaluate(c, area, payload, *, data=None):
    """Resolve the group on the server, with the versions the user saw."""
    from . import occurrences, sets as reference_sets
    data = data or occurrences.load(area, conn=c)
    memberships, names = reference_sets.memberships(c, area, data["facts"])
    facts, level, scope = _scope(payload, data, memberships)
    if not facts:
        raise planning.PlanningError("Este grupo já não tem trabalho aberto. Atualiza a vista.", 409)
    target = payload.get("resource_id")
    evidence = _evidence(c, data)
    current = _current(c, area) if _exists(c, "sector_machine_decisions") else {}
    by_machine = defaultdict(lambda: Counter())
    hours_by_machine = defaultdict(float)
    members = []
    for fact in facts:
        options = alternatives(c, data, fact, evidence)
        for o in options:
            if o["resource_id"]:
                by_machine[o["resource_id"]][o["eligibility"]] += 1
                if o["hours"] is not None:
                    hours_by_machine[o["resource_id"]] += o["hours"]
        status, option = None, None
        existing = current.get(fact["occurrence_key"])
        own = target
        if payload.get("mode") == "assign_each":
            # One action, a machine per occurrence (bulk acceptance or load-balancing moves).
            own = (payload.get("targets") or {}).get(fact["key"])
        elif payload.get("mode") == "accept_suggestions":
            # Each occurrence receives its own suggested machine, with its own eligibility.
            own = (fact.get("suggestion") or {}).get("resource_id") if fact.get("machine_basis") == "sugerida" else None
            if not own:
                status = "sem_sugestao"
        if own:
            option = next((o for o in options if o["resource_id"] == own), None)
            if fact["started"] and own != fact["resource_id"]:
                status = "iniciada"
            elif existing and existing["scope_level"] > level:
                status = "excecao"
            elif existing and existing["resource_id"] == own and existing["mode"] in (payload.get("mode"), "assign" if payload.get("mode") in ("accept_suggestions", "assign_each") else None):
                status = "atual"
            elif option and option["eligibility"] == "admissible":
                status = "admissivel"
            elif option and option["eligibility"] == "conditional":
                status = "condicional"
            else:
                status = "incompativel"
        elif existing and existing["scope_level"] > level and status is None:
            status = "excecao"
        members.append({"key": fact["key"], "of": fact["of"], "reference": fact["reference"], "target": own,
                        "operation": fact["operation_label"], "occurrence": fact["occurrence"],
                        "current": fact["assigned_machine"], "decision": fact["decision"], "status": status,
                        "hours": option["hours"] if option else fact["hours"] if not own else None,
                        "conditions": option["conditions"] if option else [],
                        "reason": (option or {}).get("reason") if status == "incompativel" else None,
                        "occurrence_key": fact["occurrence_key"], "signature": fact["technical_signature"],
                        "started": fact["started"], "remaining": fact["remaining"]})
    statuses = Counter(m["status"] for m in members if m["status"])
    resources = data["resources"]
    return {
        "area": area, "stamp": data["stamp"], "level": level, "scope": scope,
        "occurrences": len(facts), "ofs": len({f["of"] for f in facts}),
        "references": len({f["reference"] for f in facts}),
        "unknown_balances": sum(not f["balance_known"] for f in facts),
        "current": dict(Counter(f["assigned_machine"] for f in facts)),
        "machines": sorted(({"resource_id": rid, "name": (resources.get(rid) or {}).get("name", rid),
                             "admissible": n["admissible"], "conditional": n["conditional"], "excluded": n["excluded"],
                             "not_candidate": len(facts) - sum(n.values()), "hours": round(hours_by_machine[rid], 2)}
                            for rid, n in by_machine.items()), key=lambda m: (-m["admissible"] - m["conditional"], m["name"])),
        "target": {"resource_id": target, "name": (resources.get(target) or {}).get("name")} if target else None,
        "statuses": {k: {"label": STATUS[k], "count": statuses.get(k, 0),
                         "hours": round(sum(m["hours"] or 0 for m in members if m["status"] == k), 2),
                         "unknown_hours": sum(m["hours"] is None for m in members if m["status"] == k)} for k in STATUS},
        "members": members,
    }


def _request(payload):
    try:
        return uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None


def preview(payload: dict) -> dict:
    area = planning.check_area(str(payload.get("setor") or ""))
    mode = payload.get("mode")
    if mode not in MODES:
        raise planning.PlanningError("Escolhe: atribuir, preferir, automático ou preferência futura.")
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        result = evaluate(c, area, payload)
    result["members"] = result["members"][:300]
    result["members_truncated"] = result["occurrences"] > 300
    return needs.serial(result)


def _record(c, action_id, area, key, before, after):
    c.execute("""INSERT INTO planning_mtg.sector_machine_decision_history(action_id,area,occurrence_key,before,after)
        VALUES (%s,%s,%s,%s,%s)""", (action_id, area, key, Jsonb(needs.serial(before)) if before else None,
                                       Jsonb(needs.serial(after)) if after else None))


def apply(payload: dict, conn=None) -> dict:
    """One transaction: the action, its decisions and their history, or nothing."""
    from .. import planning_registration as registration
    area = planning.check_area(str(payload.get("setor") or ""))
    mode = payload.get("mode")
    if mode not in MODES:
        raise planning.PlanningError("Escolhe: atribuir, preferir, automático ou preferência futura.")
    request_id = _request(payload)
    reason = str(payload.get("reason") or payload.get("motivo") or "").strip()
    if mode != "automatic" and (not reason or len(reason) > 1000):
        raise planning.PlanningError("Indica o motivo da escolha de máquina.")
    target = str(payload.get("resource_id") or "") or None
    if mode in ("assign", "prefer", "future_preference") and not target:
        raise planning.PlanningError("Escolhe a máquina.")
    if mode == "assign_each":
        targets = payload.get("targets")
        if not isinstance(targets, dict) or not targets or len(targets) > 50000 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in targets.items()):
            raise planning.PlanningError("Indica a máquina de cada ocorrência.")
        payload = {**payload, "scope": {"keys": sorted(targets)}}
    include = payload.get("include", "eligible")
    if include not in ("eligible", "admissible", "all"):
        raise planning.PlanningError("Indica que ocorrências recebem a escolha.")
    exceptions = set(payload.get("exceptions") or [])
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector-machine-decisions'))")
        old = c.execute("SELECT * FROM planning_mtg.sector_machine_actions WHERE request_id=%s", (request_id,)).fetchone()
        if old:
            if old["versions"].get("payload") != needs.digest(payload):
                raise planning.PlanningError("Este pedido já foi usado para outros valores.", 409)
            return {**needs.serial(old["summary"]), "repeated": True, "action_id": str(old["id"])}
        if mode == "future_preference":
            return _future(c, area, payload, target, reason, actor, request_id)
        from . import occurrences
        data = occurrences.load(area, conn=c)
        if payload.get("stamp") != data["stamp"]:
            raise planning.PlanningError("A carteira ou as decisões mudaram desde a pré-visualização. Revê o grupo antes de gravar.", 409)
        result = evaluate(c, area, {**payload, "resource_id": target if mode != "automatic" else None}, data=data)
        if target and target not in data["resources"]:
            raise planning.PlanningError("Máquina desconhecida.", 422)
        if mode == "assign_each" and set(payload["targets"].values()) - set(data["resources"]):
            raise planning.PlanningError("Máquina desconhecida.", 422)
        accepted = {"admissible": {"admissivel"}, "eligible": {"admissivel", "condicional"},
                    "all": {"admissivel", "condicional", "incompativel"}}[include]
        current = _current(c, area)
        action_id = uuid.uuid4()
        changed, kept = [], Counter()
        for m in result["members"]:
            if m["key"] in exceptions:
                kept["excecao_individual"] += 1
                continue
            existing = current.get(m["occurrence_key"])
            if mode == "automatic":
                if existing and existing["scope_level"] <= result["level"]:
                    changed.append((m, existing, None))
                elif existing:
                    kept["excecao"] += 1
                continue
            if m["status"] not in accepted:
                kept[m["status"]] += 1
                continue
            stored = "assign" if mode in ("accept_suggestions", "assign_each") else mode
            after = {"mode": stored, "resource_id": m["target"], "reason": reason, "scope_level": result["level"],
                     "technical_signature": m["signature"]}
            changed.append((m, existing, after))
        summary = {"mode": mode, "target": result["target"], "changed": len(changed), "kept": dict(kept),
                   "occurrences": result["occurrences"], "statuses": result["statuses"], "level": result["level"]}
        c.execute("""INSERT INTO planning_mtg.sector_machine_actions
            (id,request_id,area,mode,resource_id,reason,actor,scope,versions,summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (action_id, request_id, area, mode, target, reason or None, actor, Jsonb(needs.serial(result["scope"])),
                   Jsonb({"stamp": data["stamp"], "payload": needs.digest(payload)}), Jsonb(needs.serial(summary))))
        for m, existing, after in changed:
            key = m["occurrence_key"]
            before = existing and {k: existing[k] for k in ("mode", "resource_id", "reason", "scope_level", "technical_signature", "action_id", "revision")}
            if after is None:
                c.execute("DELETE FROM planning_mtg.sector_machine_decisions WHERE area=%s AND occurrence_key=%s", (area, key))
            else:
                of, reference, operation, occurrence = split_key(key)
                c.execute("""INSERT INTO planning_mtg.sector_machine_decisions
                    (area,occurrence_key,production_order_no,reference,operation_code,occurrence,technical_signature,
                     mode,resource_id,reason,scope_level,action_id,actor) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (area,occurrence_key) DO UPDATE SET technical_signature=excluded.technical_signature,
                    mode=excluded.mode, resource_id=excluded.resource_id, reason=excluded.reason,
                    scope_level=excluded.scope_level, action_id=excluded.action_id, actor=excluded.actor,
                    decided_at=now(), revision=sector_machine_decisions.revision+1""",
                          (area, key, of, reference, operation, int(occurrence), m["signature"], after["mode"], after["resource_id"], reason,
                           result["level"], action_id, actor))
            _record(c, action_id, area, key, before, after)
        return {**needs.serial(summary), "repeated": False, "action_id": str(action_id)}


def _future(c, area, payload, target, reason, actor, request_id):
    selector = payload.get("selector") or {}
    kind, value = selector.get("kind"), str(selector.get("value") or "").strip()
    if kind not in SELECTOR_KINDS or not value or len(value) > 300:
        raise planning.PlanningError("Indica o seletor: referência, conjunto congelado, família SKU ou grupo de perfis.")
    operation = str(selector.get("operation") or "").strip() or None
    if kind == "set":
        found = c.execute("SELECT mode,archived FROM planning_mtg.sector_reference_sets WHERE id=%s AND area=%s",
                          (needs.uid(value), area)).fetchone()
        if not found or found["archived"] or found["mode"] != "frozen":
            raise planning.PlanningError("A preferência por conjunto exige um conjunto congelado deste setor.")
    valid_from, valid_until = payload.get("valid_from") or date.today().isoformat(), payload.get("valid_until") or None
    try:
        valid_from = date.fromisoformat(valid_from)
        valid_until = date.fromisoformat(valid_until) if valid_until else None
    except ValueError:
        raise planning.PlanningError("Vigência inválida.") from None
    if valid_until and valid_until < valid_from:
        raise planning.PlanningError("A vigência termina antes de começar.")
    action_id, preference_id = uuid.uuid4(), uuid.uuid4()
    clean = {"kind": kind, "value": value, "operation": operation, "label": selector.get("label")}
    summary = {"mode": "future_preference", "selector": clean, "resource_id": target, "preference_id": str(preference_id),
               "valid_from": valid_from.isoformat(), "valid_until": valid_until.isoformat() if valid_until else None}
    c.execute("""INSERT INTO planning_mtg.sector_machine_actions
        (id,request_id,area,mode,resource_id,reason,actor,scope,versions,summary) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (action_id, request_id, area, "future_preference", target, reason, actor, Jsonb({"selector": clean}),
               Jsonb({"payload": needs.digest(payload)}), Jsonb(summary)))
    c.execute("""INSERT INTO planning_mtg.sector_machine_preferences
        (id,area,selector,specificity,resource_id,valid_from,valid_until,reason,action_id,actor)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (preference_id, area, Jsonb(clean), SELECTOR_KINDS[kind], target, valid_from, valid_until, reason, action_id, actor))
    return {**summary, "repeated": False, "action_id": str(action_id)}


def undo(payload: dict, conn=None) -> dict:
    """A new revision restores what the action changed, except occurrences changed later."""
    from .. import planning_registration as registration
    area = planning.check_area(str(payload.get("setor") or ""))
    request_id = _request(payload)
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector-machine-decisions'))")
        old = c.execute("SELECT * FROM planning_mtg.sector_machine_actions WHERE request_id=%s", (request_id,)).fetchone()
        if old:
            return {**needs.serial(old["summary"]), "repeated": True, "action_id": str(old["id"])}
        action = c.execute("SELECT * FROM planning_mtg.sector_machine_actions WHERE id=%s AND area=%s",
                           (needs.uid(payload.get("action_id")), area)).fetchone()
        if not action:
            raise planning.PlanningError("Ação não encontrada.", 404)
        if c.execute("SELECT 1 FROM planning_mtg.sector_machine_actions WHERE undoes=%s", (action["id"],)).fetchone():
            raise planning.PlanningError("Esta ação já foi desfeita.", 409)
        new_id = uuid.uuid4()
        restored, skipped = 0, 0
        rows = c.execute("SELECT * FROM planning_mtg.sector_machine_decision_history WHERE action_id=%s ORDER BY id", (action["id"],)).fetchall()
        changes = []
        for h in rows:
            latest = c.execute("""SELECT action_id FROM planning_mtg.sector_machine_decision_history
                WHERE area=%s AND occurrence_key=%s ORDER BY id DESC LIMIT 1""", (area, h["occurrence_key"])).fetchone()
            if latest["action_id"] != action["id"]:
                skipped += 1
                continue
            changes.append(h)
        if action["mode"] == "future_preference":
            changes = []
        summary = {"mode": "undo", "undoes": str(action["id"]), "restored": len(changes), "skipped_changed_later": skipped}
        c.execute("""INSERT INTO planning_mtg.sector_machine_actions
            (id,request_id,area,mode,resource_id,reason,actor,scope,versions,summary,undoes)
            VALUES (%s,%s,%s,'undo',NULL,%s,%s,%s,%s,%s,%s)""",
                  (new_id, request_id, area, payload.get("reason") or None, actor, Jsonb({"undoes": str(action["id"])}),
                   Jsonb({"payload": needs.digest(payload)}), Jsonb(summary), action["id"]))
        if action["mode"] == "future_preference":
            c.execute("UPDATE planning_mtg.sector_machine_preferences SET archived=true WHERE action_id=%s", (action["id"],))
            summary["archived_preferences"] = 1
        for h in changes:
            current = c.execute("SELECT * FROM planning_mtg.sector_machine_decisions WHERE area=%s AND occurrence_key=%s",
                                (area, h["occurrence_key"])).fetchone()
            before = h["before"]
            if before is None:
                c.execute("DELETE FROM planning_mtg.sector_machine_decisions WHERE area=%s AND occurrence_key=%s", (area, h["occurrence_key"]))
            else:
                of, reference, operation, occurrence = split_key(h["occurrence_key"])
                c.execute("""INSERT INTO planning_mtg.sector_machine_decisions
                    (area,occurrence_key,production_order_no,reference,operation_code,occurrence,technical_signature,
                     mode,resource_id,reason,scope_level,action_id,actor) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (area,occurrence_key) DO UPDATE SET technical_signature=excluded.technical_signature,
                    mode=excluded.mode, resource_id=excluded.resource_id, reason=excluded.reason,
                    scope_level=excluded.scope_level, action_id=excluded.action_id, actor=excluded.actor,
                    decided_at=now(), revision=sector_machine_decisions.revision+1""",
                          (area, h["occurrence_key"], of, reference, operation, int(occurrence), before["technical_signature"],
                           before["mode"], before["resource_id"], before["reason"], before["scope_level"], new_id, actor))
            restored += 1
            _record(c, new_id, area, h["occurrence_key"],
                    current and {k: current[k] for k in ("mode", "resource_id", "reason", "scope_level", "technical_signature", "action_id", "revision")},
                    before and {k: before[k] for k in ("mode", "resource_id", "reason", "scope_level", "technical_signature")})
        c.execute("UPDATE planning_mtg.sector_machine_actions SET summary=%s WHERE id=%s", (Jsonb(needs.serial(summary)), new_id))
        return {**summary, "repeated": False, "action_id": str(new_id)}


def actions(area: str, limit: int = 50) -> dict:
    area = planning.check_area(area)
    with planning.connect(readonly=True) as c:
        if not _exists(c, "sector_machine_actions"):
            return {"actions": [], "preferences": []}
        rows = c.execute("""SELECT a.*, EXISTS(SELECT 1 FROM planning_mtg.sector_machine_actions u WHERE u.undoes=a.id) undone
            FROM planning_mtg.sector_machine_actions a WHERE area=%s ORDER BY created_at DESC LIMIT %s""", (area, limit)).fetchall()
        prefs = c.execute("SELECT * FROM planning_mtg.sector_machine_preferences WHERE area=%s AND NOT archived ORDER BY created_at DESC",
                          (area,)).fetchall()
        return needs.serial({"actions": rows, "preferences": prefs})
