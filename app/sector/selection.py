"""Seleção do trabalho a planear («Planear», «Limpar»), por membro (plano de 02/10/2026).

Um membro é uma linha técnica da Carteira (row_key da projeção, reencontrada entre importações pelos
selection_aliases). A ação grava exatamente os membros pedidos — nunca reconstrói a intenção a partir
dos filtros da lista. Antes de gravar, o servidor confere cada membro: ainda existe, a mesma variante
técnica, o mesmo saldo, a mesma máquina e a mesma revisão da decisão (o `token` da pré-visualização).

Conflitos (07/10/2026): um membro que mudou ou que já não está na carteira fica de fora, com o motivo em
`skipped`; os outros gravam-se. Um grupo que mudou desde que foi aberto (selo antigo) grava-se tal como
está agora e o resultado diz `group_changed`. Só quando nada se pode gravar por causa de conflitos é que o
pedido é recusado (409, com os membros afetados).

Planear numa linha sem máquina (decisão do Luís, 07/10/2026, substitui a regra de 02/10 «sem máquina não se
planeia»): grava a máquina sugerida — a mesma que a Carteira mostra, só máquinas do setor — como escolha da
Carteira (sector_member_machine, como «Atribuir máquina», com a origem «sugerida») e planeia. Só fica de fora,
com o motivo, a linha sem nenhuma sugestão possível (contada em `skipped_no_machine`); se nenhuma linha
puder ser planeada, a ação é recusada.

Excluir: o motivo é opcional desde 07/10/2026; o autor e a hora ficam sempre registados.

Precedência na leitura: membro → (OF, referência) → (OF, '*') (ver decisions.py). As decisões antigas
por OF/referência continuam a valer; novas ações só escrevem decisões por membro. Limpar um membro
coberto por uma decisão herdada grava uma desmarcação explícita ('cleared'), que vence a herança.

Cada ação fica numa transação: decisões, máquinas sugeridas, um evento por membro (antes/depois) em
planning_mtg.sector_decision_events e o pedido em sector_selection_requests. O mesmo request_id com o
mesmo conteúdo devolve o resultado já gravado; com outro conteúdo é recusado (409).
"""
from __future__ import annotations

import uuid
from contextlib import nullcontext

import psycopg
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs, planning_registration as registration
from . import decisions as resolution, portfolio

WHOLE = portfolio.WHOLE
ACTIONS = {"selecionar": "selected", "excluir": "excluded", "limpar": "cleared"}
MAX_MEMBERS = 50000
# Motivos de uma linha que fica de fora (07/10/2026): ditos no resultado, nunca escondidos.
CHANGED = "Mudou desde a pré-visualização (saldo, máquina, variante ou decisão)."
GONE = "Já não está na carteira aberta (concluído ou mudou na importação)."
NO_SUGGESTION = "Sem máquina sugerida: a ficha técnica e o histórico não indicam nenhuma máquina do setor."
SUGGESTION_UNAVAILABLE = "Máquina sugerida indisponível neste momento; tenta outra vez ou atribui a máquina."


def current(sector: str, conn=None) -> resolution.Decisions:
    """Decisões do setor: antigas por (OF, referência) e por membro em `.members`."""
    portfolio.check_sector(sector)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        rows = c.execute("SELECT production_order_no, reference, decision, reason, actor, decided_at, revision "
                         "FROM planning_mtg.sector_selection WHERE area = %s", (sector,)).fetchall()
        members = resolution.read_members(c, sector)
    return resolution.Decisions({(r["production_order_no"], r["reference"]): r for r in rows},
                                {r["member_key"]: r for r in members})


decision_for = portfolio.decision_of


def _seen(line: dict) -> dict:
    return {"of": line["of"], "reference": line["reference"], "profile": line["profile"], "length_mm": line["length_mm"],
            "pieces": line["pieces"], "metres": round(line["metres"], 1), "machine": line["machine"],
            "cut_date": line["cut_date"].isoformat() if line["cut_date"] else None, "signature": line["signature"]}


class Conflict(planning.PlanningError):
    def __init__(self, message: str, conflicts: list[dict]):
        super().__init__(message, 409)
        self.fields = {"conflicts": conflicts[:200], "conflict_count": len(conflicts)}


def _skipped(line: dict | None, reason: str, key: str | None = None) -> dict:
    if line is None:
        return {"key": key, "reason": reason}
    return {"key": line["key"], "of": line["of"], "reference": line["reference"], "reason": reason}


def _alias_index(lines: list[dict]) -> dict:
    """Chave antiga (selection_aliases) → linha atual, só quando a chave antiga é de uma única linha."""
    found, repeated = {}, set()
    for line in lines:
        for alias in line.get("aliases") or ():
            if alias in found and found[alias] is not line:
                repeated.add(alias)
            found[alias] = line
    return {alias: line for alias, line in found.items() if alias not in repeated}


def _requested(payload: dict, data: dict, decisions, *, partial: bool = False) -> tuple[list[tuple[dict, str | None]], dict, list[dict]]:
    """([(line, token sent)], what the request referred to, [members left out with the reason]).

    Um membro marcado antes de uma importação é reencontrado pela chave antiga (selection_aliases). Sem
    `partial` (Atribuir máquina) um membro que já não está na carteira ou um grupo que mudou recusam o pedido
    (409); com `partial` (Planear, Excluir, Limpar — 07/10/2026) o membro fica de fora com o motivo e o grupo
    vale tal como está agora (`grupo_mudou` no âmbito). Sem nada para gravar, recusa na mesma.
    """
    by_key = {}
    for line in data["lines"]:
        by_key[line["key"]] = line
    if payload.get("membros") is not None:
        members = payload["membros"]
        if not isinstance(members, list) or not members or len(members) > MAX_MEMBERS:
            raise planning.PlanningError("Escolhe pelo menos um membro.")
        aliases = _alias_index(data["lines"])
        result, missing, seen = [], [], set()
        for item in members:
            if not isinstance(item, dict) or not isinstance(item.get("chave"), str):
                raise planning.PlanningError("Membro inválido.")
            line = by_key.get(item["chave"]) or aliases.get(item["chave"])
            if line is None:
                missing.append(_skipped(None, GONE, item["chave"]))
                continue
            if line["key"] in seen:
                if not partial:
                    raise planning.PlanningError("Membro repetido no pedido.")
                continue  # a mesma linha marcada pela chave antiga e pela atual
            seen.add(line["key"])
            result.append((line, item.get("token")))
        if missing and (not partial or not result):
            raise Conflict("Alguns membros já não estão na carteira. Atualiza a seleção.", missing)
        return result, {"membros": len(result)}, missing
    group = payload.get("grupo")
    if isinstance(group, dict):
        view, path = str(group.get("vista") or ""), group.get("caminho")
        exceto = group.get("exceto") or []
        if not isinstance(exceto, list) or not all(isinstance(k, str) for k in exceto):
            raise planning.PlanningError("Exceções inválidas.")
        portfolio.check_path(view, path if isinstance(path, list) else None)
        if not path:
            raise planning.PlanningError("Escolhe um grupo da Carteira.")
        lines = portfolio.group_lines(data, view, path)
        if not lines:
            raise planning.PlanningError("Esse grupo já não tem trabalho aberto. Atualiza a Carteira.", 409)
        changed = bool(group.get("selo")) and group["selo"] != portfolio.group_seal(lines, decisions)
        if changed and not partial:
            raise Conflict("O grupo mudou desde que foi aberto. Abre a lupa outra vez.", [{"group": path, "reason": "Membros, saldos ou decisões mudaram."}])
        excluded = set(exceto)
        # Uma exceção marcada antes de uma importação vale pela chave antiga da mesma linha.
        chosen = [(x, None) for x in lines if x["key"] not in excluded and not excluded.intersection(x.get("aliases") or ())]
        if not chosen:
            raise planning.PlanningError("Escolhe pelo menos um membro.")
        scope = {"vista": view, "caminho": path, "exceto": len(excluded)}
        if changed:
            scope["grupo_mudou"] = True
        return chosen, scope, []
    return _legacy(payload, data), {"contrato": "antigo"}, []


def _legacy(payload: dict, data: dict) -> list[tuple[dict, None]]:
    """Contrato anterior (vista + caminho, por exemplo o botão Planear do quadro do plano).

    Resolve os membros exatos do grupo e grava-os um a um: já não grava (OF, '*'), que alargava a ação a
    linhas escondidas e a trabalho que chegue depois.
    """
    view = str(payload.get("vista") or "referencia")
    path = payload.get("caminho") or []
    filters = payload.get("filtros") or {}
    if view not in portfolio.VIEWS or not isinstance(path, list) or not path or not all(isinstance(p, str) for p in path):
        raise planning.PlanningError("Escolhe um grupo da Carteira.")
    if not isinstance(filters, dict):
        raise planning.PlanningError("Filtros inválidos.")
    if any(v for k, v in filters.items() if k != "estado"):
        raise planning.PlanningError("Escolhe os membros na lupa: a ação já não usa os filtros da lista.")
    portfolio.check_path(view, path)
    chosen = portfolio.group_lines(data, view, path)
    if not chosen:
        raise planning.PlanningError("Esse grupo já não tem trabalho aberto. Atualiza a Carteira.", 409)
    return [(x, None) for x in chosen]


def request_hash(payload: dict, action: str) -> str:
    """O pedido tal como foi enviado (não o grupo recalculado): uma repetição devolve o resultado gravado."""
    keep = ("setor", "acao", "motivo", "membros", "grupo", "vista", "caminho", "filtros", "maquina")
    whole = {"todo_o_grupo": True} if payload.get("todo_o_grupo") else {}  # só quando vem: os pedidos antigos mantêm o resumo
    return needs.digest({"action": action, **{k: payload.get(k) for k in keep}, **whole})


def previous_request(c, request_id, content):
    found = c.execute("SELECT content_hash, result FROM planning_mtg.sector_selection_requests WHERE request_id = %s",
                      (request_id,)).fetchone()
    if not found:
        return None
    if found["content_hash"] != content:
        raise planning.PlanningError("Este pedido já foi usado com outro conteúdo. Recarrega a página.", 409)
    return {**found["result"], "repeated": True, "changed": 0}


# Coluna Máquina da Tabela: só «vazia» ou «Por definir» quer dizer «por decidir». Os outros textos sem máquina
# física (Subcontrato, Serrote MTG3, Abocardar…) são uma decisão: nunca recebem a máquina sugerida.
UNDECIDED = {"", "por definir"}
NO_MEMBER_MACHINE = "A máquina por linha ainda não está instalada (migração 048)."


def tabela_note(line: dict) -> str | None:
    """«Na Tabela: …» quando a coluna Máquina diz que a linha não leva máquina interna; None se está por decidir."""
    text = str(line.get("tabela_machine") or "").strip()
    return None if text.casefold() in UNDECIDED else f"Na Tabela: {text}"


def suggested_machines(sector: str, lines: list[dict], *, allow_stale: bool = False) -> dict[str, dict]:
    """{chave: {resource_id, machine, origin, label}} — a máquina que o Planear grava numa linha sem máquina.

    Uma só fonte (revisão de 07/10/2026): é também a «— sugerida» da lupa e a pré-escolha de «Atribuir máquina».
    Só máquinas do setor (members.py) e só linhas sem máquina efetiva e por decidir na Tabela:
    1. a preferência aprendida com as escolhas dos planeadores, já filtrada pela ficha técnica
       (machine_learning.for_line com machine_learning.technical);
    2. senão a máquina sugerida da previsão (estimates.apply): a das outras linhas da OF com o mesmo perfil e
       operação (estimates.peer_machine), o processo da regra das séries, o precedente da peça e o equilíbrio
       de carga — também só entre as candidatas da ficha técnica.
    Uma linha sem nenhuma das duas não tem sugestão. As gravações leem as ocorrências atuais; as leituras da
    lupa podem passar `allow_stale` e mostrar a versão anterior enquanto se refazem.
    """
    from . import machine_learning, members, occurrences
    lines = [x for x in lines if not x["machine"] and tabela_note(x) is None]
    if not lines:
        return {}
    with planning.connect(readonly=True) as c:
        own = members.members(c, sector)
    if not own:
        return {}
    data = occurrences.load(sector, allow_stale=allow_stale)
    checked = machine_learning.technical(sector, data=data)
    learned = machine_learning.model(sector) if checked is None else None
    estimated = {}
    for f in data["facts"]:
        if f["phase"] == "principal" and f.get("machine_basis") == "sugerida" and f.get("suggestion"):
            estimated.setdefault(f["line_key"], f["suggestion"])
    out = {}
    for line in lines:
        keys = [line["key"], *line.get("aliases", ())]  # as ocorrências podem ser de antes da última importação
        learned_choice = next((x for x in (machine_learning.for_line(learned, checked, {**line, "key": k}) for k in keys) if x), None)
        estimate = next((estimated[k] for k in keys if k in estimated), None)
        for found, origin, label in ((learned_choice, "aprendida", "label"), (estimate, "previsao", "reason")):
            if found and found["resource_id"] in own:
                out[line["key"]] = {"resource_id": found["resource_id"], "origin": origin, "label": found.get(label),
                                    "machine": own[found["resource_id"]].get("name") or found["machine"]}
                break
    return out


def _to_suggest(payload: dict, data: dict) -> list[dict]:
    """Linhas do pedido sem máquina e por decidir, resolvidas sem bloqueio, só para calcular as sugestões antes."""
    try:
        chosen, _, _ = _requested(payload, data, resolution.Decisions(), partial=True)
    except planning.PlanningError:
        return []  # o pedido volta a ser conferido sob o bloqueio, com as decisões gravadas
    return [line for line, _ in chosen if not line["machine"] and tabela_note(line) is None]


def _suggestions(sector: str, lines: list[dict]) -> tuple[dict, str | None]:
    """Sugestões das linhas sem máquina e, se a previsão falhar, o motivo para as que ficam sem nenhuma."""
    if not lines:
        return {}, None
    try:
        return suggested_machines(sector, lines), None
    except Exception:  # a sugestão não pode impedir planear as linhas que já têm máquina
        import logging
        logging.getLogger(__name__).exception("Máquinas sugeridas indisponíveis ao Planear")
        return {}, SUGGESTION_UNAVAILABLE


def apply(payload: dict, *, data: dict | None = None, conn=None) -> dict:
    sector = portfolio.check_sector(str(payload.get("setor") or "cantoneiras"))
    action = ACTIONS.get(str(payload.get("acao")))
    reason = str(payload.get("motivo") or "").strip() or None  # opcional também em Excluir (07/10/2026)
    if not action:
        raise planning.PlanningError("Ação inválida: usa selecionar, excluir ou limpar.")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None

    data = data or portfolio.current(sector)
    actor = registration.human_actor(payload)
    # As sugestões calculam-se antes de qualquer bloqueio, com ligações próprias só de leitura e as ocorrências
    # atuais (uma gravação nunca usa allow_stale): nenhum outro pedido espera pela previsão.
    suggestions, unavailable = _suggestions(sector, _to_suggest(payload, data)) if action == "selected" else ({}, None)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        if not c.execute("SELECT to_regclass('planning_mtg.sector_member_selection') t").fetchone()["t"]:
            raise planning.PlanningError("A gravação por membro ainda não está instalada (migração 046).", 503)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_member_selection:' || %s))", (sector,))
        content = request_hash(payload, action)
        repeated = previous_request(c, request_id, content)
        if repeated:
            return repeated
        decisions = current(sector, conn=c)
        chosen, scope, skipped = _requested(payload, data, decisions, partial=True)
        if action == "selected" and (payload.get("membros") is None or payload.get("todo_o_grupo")):
            # Planear um grupo (também quando chega como membros com «todo_o_grupo») não anula exclusões: um membro
            # excluído só volta se for escolhido um a um.
            chosen = [(line, token) for line, token in chosen if portfolio.effective(line, decisions)["decision"] != "excluded"]
            if not chosen:
                raise planning.PlanningError("Todas estas linhas estão excluídas; escolhe-as uma a uma na lupa para as planear.")
        ready = []
        for line, token in chosen:
            before = portfolio.effective(line, decisions)
            if token is not None and token != portfolio.member_token(line, before["revision"]):
                skipped.append(_skipped(line, CHANGED))
            else:
                ready.append((line, before, token))
        machines, no_machine = [], 0  # (linha, sugestão): a máquina sugerida fica como escolha da Carteira
        if action == "selected" and any(not line["machine"] for line, _, _ in ready):
            ready, machines, no_machine = _with_machines(c, sector, ready, skipped, suggestions, unavailable)
        if not ready:
            if len(skipped) > no_machine:
                raise Conflict("Estas linhas mudaram entretanto ou já não estão na carteira. Nada foi gravado; atualiza a seleção.", skipped)
            raise planning.PlanningError("Nenhuma destas linhas tem máquina nem máquina sugerida. Dá-lhes máquina antes de Planear.")
        changes = []
        for line, before, _ in ready:
            after = _after(action, line, decisions)
            if after["decision"] == before["decision"]:
                continue  # a decisão efetiva já é esta: nada a gravar neste membro
            changes.append((line, before, after))
        # Planeadas neste pedido: as que passam a Planear e as já marcadas que só agora recebem a máquina sugerida.
        planned = {line["key"] for line, _, _ in changes} | {line["key"] for line, _ in machines} if action == "selected" else set()
        detail = {"ambito": scope, "geracao": data["generation"], "importacao": data["snapshot"]}
        result = {"changed": len(changes), "planned": len(planned), "members": len(ready), "skipped_no_machine": no_machine,
                  "suggested_machine": len(machines), "skipped": skipped[:200], "skipped_count": len(skipped),
                  "group_changed": bool(scope.get("grupo_mudou")), "action": action, "actor": actor,
                  "metres": round(sum(line["metres"] for line, _, _ in changes), 1), "repeated": False,
                  "keys": [line["key"] for line, _, _ in changes]}
        _write(c, sector, action, reason, actor, request_id, detail, changes, content, result, machines)
    return result


def _with_machines(c, sector, ready, skipped, suggestions, unavailable):
    """Máquina das linhas sem máquina, lida sob o bloqueio de «Atribuir máquina» (revisão de 07/10/2026).

    Uma escolha da Carteira ou um conjunto de famílias gravados entretanto ganham sempre à sugestão: a linha
    planeia-se com essa máquina, ou fica de fora como mudada se foi marcada (token) quando não tinha máquina.
    Só a linha ainda sem máquina e por decidir na Tabela recebe a sugestão calculada antes; as outras ficam de
    fora com o motivo. Devolve (linhas a gravar, máquinas sugeridas, quantas ficaram sem máquina).
    """
    from . import machine_choice
    ctx = None
    if c.execute("SELECT to_regclass('planning_mtg.sector_member_machine') t").fetchone()["t"]:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_member_machine:' || %s))", (sector,))
        ctx = machine_choice.context(sector, conn=c)
    out, machines, no_machine = [], [], 0
    for line, before, token in ready:
        if not line["machine"]:
            family = line.get("sku_family") if line.get("sku_family") not in (None, "Sem família SKU") else None
            now = machine_choice.effective(ctx, [line["key"], *line.get("aliases", ())], family, line.get("tabela_machine"))
            if now["machine"]:
                if token is not None:
                    skipped.append(_skipped(line, CHANGED))
                    continue
                line = {**line, "machine": now["machine"], "machine_source": now["source"], "machine_resource_id": now["resource_id"]}
            else:
                note = tabela_note(line)
                found = None if note or ctx is None else suggestions.get(line["key"])
                if not found:
                    no_machine += 1
                    skipped.append(_skipped(line, note or (NO_MEMBER_MACHINE if ctx is None else unavailable or NO_SUGGESTION)))
                    continue
                machines.append((line, found))
                line = {**line, "machine": found["machine"], "machine_source": "carteira", "machine_resource_id": found["resource_id"]}
        out.append((line, before, token))
    return out, machines, no_machine


def _after(action, line, decisions) -> dict:
    """Decisão gravada: selected/excluded; Limpar = sem decisão do membro, ou desmarcação explícita se herdar."""
    if action != "cleared":
        return {"decision": action}
    inherited = resolution.resolve(decisions, {}, [(line["of"], line["reference"]), (line["of"], WHOLE)], [])
    return {"decision": None, "explicit": inherited["decision"] is not None}


def _cleared(cur, table: str, sector: str, lines: list[dict]) -> dict[str, int]:
    """Apaga numa só instrução o que estava gravado para estes membros (chave atual e antigas) e devolve a revisão
    nova de cada um."""
    assert table in ("sector_member_selection", "sector_member_machine")
    owner = {}
    for line in lines:
        for key in (line["key"], *line.get("aliases", ())):
            owner.setdefault(key, line["key"])
    revisions = {line["key"]: 1 for line in lines}
    for r in cur.execute(f"DELETE FROM planning_mtg.{table} WHERE area = %s AND member_key = ANY(%s) RETURNING member_key, revision",
                         (sector, list(owner))).fetchall():
        key = owner[r["member_key"]]
        revisions[key] = max(revisions[key], r["revision"] + 1)
    return revisions


def _write(c, sector, action, reason, actor, request_id, detail, changes, content, result, machines=()) -> None:
    """Uma transação: pedido, máquinas sugeridas, decisões e eventos, em lotes (uma instrução por tabela)."""
    with c.cursor() as cur:
        try:
            cur.execute("INSERT INTO planning_mtg.sector_selection_requests (request_id, area, action, content_hash, actor, result) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", (request_id, sector, action, content, actor, Jsonb(result)))
        except psycopg.errors.UniqueViolation:
            raise planning.PlanningError("O mesmo pedido foi gravado entretanto. Atualiza a Carteira.", 409) from None
        if machines:
            _suggested_machines(cur, sector, actor, request_id, detail, machines)
        if not changes:
            return
        revisions = _cleared(cur, "sector_member_selection", sector, [line for line, _, _ in changes])
        rows, events = [], []
        for line, before, after in changes:
            revision = revisions[line["key"]]
            stored = after["decision"] if after["decision"] else ("cleared" if after.get("explicit") else None)
            if stored:
                rows.append((sector, line["key"], line["of"], line["reference"], stored,
                             resolution.reason_or_default(reason) if stored == "excluded" else None, actor, revision, request_id,
                             Jsonb(_seen(line))))
            events.append((sector, line["of"], line["reference"], line["key"], action, reason, actor, request_id,
                           Jsonb({**detail, "seen": _seen(line), "revision": revision,
                                  "before": {k: before[k] for k in ("decision", "source", "revision")},
                                  "after": {"decision": after["decision"], "stored": stored}})))
        if rows:
            cur.executemany("""INSERT INTO planning_mtg.sector_member_selection
                                   (area, member_key, production_order_no, reference, decision, reason, actor, revision, request_id, seen)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", rows)
        cur.executemany("""INSERT INTO planning_mtg.sector_decision_events
                               (area, kind, production_order_no, reference, member_key, action, reason, actor, request_id, detail)
                           VALUES (%s, 'member', %s, %s, %s, %s, %s, %s, %s, %s)""", events)


def _suggested_machines(cur, sector, actor, request_id, detail, machines) -> None:
    """A máquina sugerida fica como escolha da Carteira (a mesma de «Atribuir máquina»), com a origem «sugerida».

    A origem fica em `seen` e no evento; machine_learning não aprende com estes eventos, para a sugestão não se
    reforçar a si própria. Muda-se como qualquer escolha da Carteira. Os eventos levam um identificador derivado
    do pedido (um só evento por membro e pedido), com o pedido do Planear em `pedido`.
    """
    machine_request = uuid.uuid5(request_id, "maquina-sugerida")
    revisions = _cleared(cur, "sector_member_machine", sector, [line for line, _ in machines])
    rows, events = [], []
    for line, found in machines:
        suggestion = {"origem": found.get("origin"), "motivo": found.get("label")}
        revision = revisions[line["key"]]
        rows.append((sector, line["key"], line["of"], line["reference"], found["resource_id"], found["machine"], actor, revision,
                     machine_request, Jsonb({**_seen(line), "origem": "sugerida", "sugestao": suggestion, "pedido": str(request_id)})))
        events.append((sector, line["of"], line["reference"], line["key"], actor, machine_request,
                       Jsonb({**detail, "origem": "sugerida", "sugestao": suggestion, "pedido": str(request_id), "seen": _seen(line),
                              "revision": revision,
                              "before": {"carteira": None, "tabela": line.get("tabela_machine"), "efetiva": line["machine"],
                                         "origem": line.get("machine_source"), "familia": line.get("sku_family"),
                                         "perfil": line.get("profile")},
                              "after": {"carteira": found["machine"]}})))
    cur.executemany("""INSERT INTO planning_mtg.sector_member_machine
                           (area, member_key, production_order_no, reference, resource_id, machine_name, actor, revision, request_id, seen)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", rows)
    cur.executemany("""INSERT INTO planning_mtg.sector_decision_events
                           (area, kind, production_order_no, reference, member_key, action, actor, request_id, detail)
                       VALUES (%s, 'machine', %s, %s, %s, 'machine', %s, %s, %s)""", events)

