"""Propostas auditáveis de saída XLSM para fichas manuais de Perfis."""
from __future__ import annotations

import hashlib
import json
import uuid

from psycopg.types.json import Jsonb

from . import planning, planning_hub, planning_needs as needs
from .dossiers import DossierError, cpis, macro
from .planning_registration import human_actor


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, separators=(",", ":")).encode()).hexdigest()


def _selection(payload):
    ids=list(payload.get('record_ids') or [])
    from . import planning_needs as needs
    with planning.connect(readonly=True) as conn:
        for nid in payload.get('need_ids') or []:
            ids.extend(str(r['id']) for r in conn.execute('SELECT id FROM planning_mtg.records WHERE need_id=%s',(needs.uid(nid),)).fetchall())
        for ref in payload.get('pdf_refs') or []:
            src=needs.source_data({'kind':'pdf','id':ref.get('id'),'version':ref.get('version')},'perfis',conn)
            rows=conn.execute("SELECT r.id FROM planning_mtg.need_sources s JOIN planning_mtg.records r ON r.need_id=s.need_id WHERE s.kind='pdf' AND s.source_id=%s",(src['id'],)).fetchall()
            if not rows:raise planning.PlanningError('Prepara a peça PDF no formulário comum antes da saída.',409)
            ids.extend(str(r['id']) for r in rows)
    return list(dict.fromkeys(ids))


def _validate_canonical(record):
    if not record.get('need_id'):return
    from . import planning_needs as needs, planning_associations as associations
    with planning.connect(readonly=True) as conn:
        need=needs.load(conn,record['need_id'])
        if any(record['values_json'].get(k)!=need['specification'].get(k) for k in needs.PIECE_FIELDS):
            raise planning.PlanningError('A especificação mudou. Reabre todas as operações selecionadas.',409)
        for src in needs.linked_sources(conn,need['id']):
            current=needs.source_data({'kind':src['kind'],'id':src['source_id']},src['payload'].get('area',record['area']),conn)
            if current['version']!=src['version']:raise planning.PlanningError('A origem PDF ou macro mudou. Reabre a preparação.',409)
        if conn.execute('SELECT 1 FROM planning_mtg.field_state WHERE need_id=%s AND requires_review LIMIT 1',(need['id'],)).fetchone():
            raise planning.PlanningError('Existem sugestões por rever.',409)
        op=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE id=%s',(record['operation_id'],)).fetchone()
        proof=associations.evidence(conn,need,op)
        if proof['warnings']:raise planning.PlanningError('Resolve as origens ou associações assinaladas antes da saída.',409)
        conference=associations.current_conference(conn,need,op,proof)
        balance=conference['accepted_remaining'] if conference else proof['macro_remaining']
        proposed=record['values_json'].get('quantity_to_plan')
        quantity_state=conn.execute("SELECT source FROM planning_mtg.field_state WHERE need_id=%s AND scope=%s AND field='quantity_to_plan'",(need['id'],str(op['id']))).fetchone()
        automatic=(quantity_state or {}).get('source') or {}
        if automatic.get('rule')=='full_confirmed_balance' and (automatic.get('evidence_hash')!=proof['evidence_hash'] or proposed!=balance):
            raise planning.PlanningError('A quantidade em falta mudou desde a conclusão. Reabre e conclui novamente a preparação.',409)
        if balance is None or proposed is None or proposed>balance:raise planning.PlanningError('Revê o saldo da operação antes da saída.',409)
        if record.get('source_plan_key') and proposed!=balance:raise planning.PlanningError('A macro existente representa o saldo completo desta linha. Mantém a preparação parcial local ou seleciona o saldo completo para esta saída.',409)


def _records(record_ids: list[str]):
    if not isinstance(record_ids, list) or not record_ids or len(record_ids) > 200:
        raise planning.PlanningError("Seleciona entre 1 e 200 fichas de Perfis para a saída.")
    try:
        ids = [uuid.UUID(str(value)) for value in record_ids]
    except (TypeError, ValueError):
        raise planning.PlanningError("A seleção de fichas para a saída é inválida.") from None
    if len(set(ids)) != len(ids):
        raise planning.PlanningError("A mesma ficha foi selecionada mais do que uma vez.")
    with planning.connect(readonly=True) as conn:
        rows = conn.execute("""SELECT * FROM planning_mtg.records
            WHERE id=ANY(%s) ORDER BY production_order_no,component_ref,id""", (ids,)).fetchall()
    if len(rows) != len(ids):
        raise planning.PlanningError("Uma das fichas selecionadas já não existe.", 409)
    if any(row["area"] != "perfis" for row in rows):
        raise planning.PlanningError("A saída XLSM está validada apenas para Perfis.", 409)
    if any(row["record_status"] != "ready" for row in rows):
        raise planning.PlanningError("Conclui as fichas selecionadas antes de preparar a saída.", 409)
    for row in rows:
        _validate_canonical(row)
    return rows


def _macro_rows(records):
    contexts = {}
    result = []
    grouped = {}
    for record in records:
        key=str(record.get('need_id') or record['id'])
        grouped.setdefault(key,[]).append(record)
    combined=[]
    for group in grouped.values():
        cut=next((r for r in group if r['values_json'].get('operation')=='corte'),None)
        selected=dict(cut or group[0]);selected['values_json']=dict(selected['values_json'])
        if selected.get('need_id'):
            with planning.connect(readonly=True) as conn:
                historical=conn.execute("SELECT 1 FROM planning_mtg.records WHERE need_id=%s AND values_json->>'operation'='abocardar' LIMIT 1",(selected['need_id'],)).fetchone()
            if cut and historical and selected['values_json'].get('abocardar')!='X':
                raise planning.PlanningError('A indicação de abocardar difere de uma ficha anterior. Revê as duas preparações antes da saída.',409)
        if any(r['values_json'].get('operation')=='abocardar' for r in group) and not cut:
            selected['values_json']['abocardar']='X'
        if not cut and selected['values_json'].get('operation')=='abocardar':
            if not selected.get('source_plan_key'):raise planning.PlanningError('Prepara o corte desta peça antes de exportar uma operação de abocardar sem linha na macro.',409)
            selected['values_json']['machine']=''
        combined.append(selected)
    for record in combined:
        if record['values_json'].get('quantity_to_plan')==0:continue
        of = record["production_order_no"]
        if of not in contexts:
            try:
                contexts[of] = cpis.read_context(of)
            except DossierError as exc:
                raise planning.PlanningError(str(exc), exc.status) from None
        context = contexts[of]
        values = dict(record["values_json"] or {})
        values["component_ref"] = record["component_ref"]
        plan_key = record.get("source_plan_key")
        if plan_key and record.get('need_id'):
            with planning.connect(readonly=True) as source_conn:
                current_source=needs.source_data({'kind':'plan_line','id':plan_key},'perfis',source_conn)
                plan_key=current_source['id']
        source_row = next((row for row in context["plan_rows"]
                           if row.get("source_line_id") == plan_key), None) if plan_key else None
        member = next((m for m in context.get('planning_members',[])
                       if record.get('need_id') and m['need_id']==str(record['need_id'])), None)
        population = (member or source_row or {}).get('population') or context.get('population')
        if population and not population['active']:
            raise planning.PlanningError(
                f"A peça {record['component_ref']} está fechada ({' + '.join(population['closed_sources'])}). "
                'Mantém-se no histórico e não pode entrar na saída ativa.', 409)
        if plan_key and not source_row:
            raise planning.PlanningError(
                f"A linha de origem da ficha {record['component_ref']} mudou. Reabre a ficha antes da saída.", 409)
        if source_row:
            match = {
                "kind": "changed",
                "excel_row": source_row["excel_row"],
                "source_plan_key": source_row["source_line_id"],
                "effective_values": values,
                "differences": [{"field": field} for field in set(macro.INPUT_MAP.values())],
            }
        else:
            if record.get('need_id'):
                planned=values.get('quantity_to_plan')
                if planned is None or planned<=0:raise planning.PlanningError('Indica uma quantidade positiva a planear para criar uma nova linha na macro.',409)
                if planned!=values.get('quantity_required'):
                    values['notes']=(values.get('notes') or '')+f" · Necessidade total: {values.get('quantity_required')}; nesta preparação: {planned}."
                values['quantity_required']=planned
            match = {"kind": "new", "effective_values": values, "differences": []}
        machine = str(values.get("machine") or "").strip()
        if machine:
            match["machine_update"] = machine
        # Removed controls never generate new writes to those macro cells.
        match["chanfro_export"] = False
        group = "Vanguard" if "vanguard" in machine.casefold() else "Serrote"
        result.append({
            "document_id": "record:" + str(record["id"]),
            "record_id": str(record["id"]),
            "production_order": of,
            "context": context,
            "filename": f"Ficha {record['component_ref']}",
            "index_page": None,
            "drawing_pages": [],
            "machine_group": group,
            "values": values,
            "match": match,
            "selection": {"source": "preparação manual"},
            "technical_origin": "manual",
            "actor": record["actor"],
        })
    snapshots = {row["context"]["snapshot"]["snapshot_id"] for row in result}
    if result and len(snapshots) != 1:
        raise planning.PlanningError("As fichas selecionadas não usam a mesma versão da macro.", 409)
    return result


def create_proposal(payload: dict):
    if not isinstance(payload, dict):
        raise planning.PlanningError("A proposta de saída é inválida.")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except (TypeError, ValueError):
        raise planning.PlanningError("A proposta não tem um identificador válido.") from None
    actor = human_actor(payload)
    request_hash = _hash(payload)
    with planning.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(request_id),))
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
        previous = conn.execute("SELECT * FROM planning_mtg.output_proposals WHERE request_id=%s",
                                (request_id,)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise planning.PlanningError("Este pedido já foi usado para outra proposta.", 409)
            return planning.serializable({"id": str(previous["id"]), "replayed": True,
                                          **previous["summary_json"]})
        status = planning_hub.source_status()
        if not status["completion_allowed"]:
            raise planning.PlanningError(
                "O CPIS não tem uma confirmação direta recente. A proposta operacional está bloqueada.", 409)
        records = _records(_selection(payload))
        current_version = status["cpis"]["version"]
        planning_hub.require_operational_orders([row['production_order_no'] for row in records],
                                               expected_version=current_version, conn=conn)
        if any(row.get("source_version") != current_version for row in records):
            raise planning.PlanningError("O CPIS mudou desde a preparação. Reabre as fichas e confirma as alterações.", 409)
        rows = _macro_rows(records)
        if not rows:
            raise planning.PlanningError('A quantidade em falta é zero. Não há uma nova linha a gerar para estas peças.',409)
        try:
            summary = macro.preview_macro(rows)
        except DossierError as exc:
            raise planning.PlanningError(str(exc), exc.status) from None
        refs = [{"id": str(row["id"]), "revision": row["revision"]} for row in records]
        summary["proposal_fingerprint"] = _hash({"summary": summary, "records": refs,
                                                   "cpis_version": current_version})
        proposal_id = uuid.uuid4()
        macro_snapshot = rows[0]["context"]["snapshot"]["snapshot_id"]
        conn.execute("""INSERT INTO planning_mtg.output_proposals
            (id,request_id,request_hash,record_refs,cpis_version,macro_snapshot_id,
             macro_sha256,proposal_fingerprint,summary_json,actor)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (proposal_id, request_id, request_hash, Jsonb(refs), current_version, macro_snapshot,
             summary["source_sha256"], summary["proposal_fingerprint"], Jsonb(summary), actor))
        return planning.serializable({"id": str(proposal_id), "replayed": False, **summary})


def _generate(proposal_id: str, fingerprint: str) -> bytes:
    try:
        proposal_uuid = uuid.UUID(str(proposal_id))
    except (TypeError, ValueError):
        raise planning.PlanningError("A proposta de saída não existe.", 404) from None
    with planning.connect(readonly=True) as conn:
        proposal = conn.execute("SELECT * FROM planning_mtg.output_proposals WHERE id=%s",
                                (proposal_uuid,)).fetchone()
    if not proposal:
        raise planning.PlanningError("A proposta de saída não existe.", 404)
    if not fingerprint or fingerprint != proposal["proposal_fingerprint"]:
        raise planning.PlanningError("Revê a comparação atual antes de descarregar a saída.", 409)
    status = planning_hub.source_status()
    if not status["completion_allowed"] or status["cpis"]["version"] != proposal["cpis_version"]:
        raise planning.PlanningError("A confirmação CPIS mudou. Prepara uma nova comparação.", 409)
    refs = proposal["record_refs"]
    records = _records([row["id"] for row in refs])
    planning_hub.require_operational_orders([row['production_order_no'] for row in records],
                                           expected_version=proposal['cpis_version'])
    current = {str(row["id"]): row["revision"] for row in records}
    if any(current.get(row["id"]) != row["revision"] for row in refs):
        raise planning.PlanningError("Uma ficha mudou desde a comparação. Prepara uma nova proposta.", 409)
    rows = _macro_rows(records)
    try:
        data, summary = macro.fill_macro(rows)
    except DossierError as exc:
        raise planning.PlanningError(str(exc), exc.status) from None
    expected = _hash({"summary": summary, "records": refs,
                      "cpis_version": proposal["cpis_version"]})
    if (summary["source_sha256"] != proposal["macro_sha256"]
            or expected != proposal["proposal_fingerprint"]):
        raise planning.PlanningError("A macro ou a proposta mudou. Revê a nova comparação.", 409)
    with planning.connect() as conn:
        conn.execute("UPDATE planning_mtg.output_proposals SET exported_at=now() WHERE id=%s",
                     (proposal_uuid,))
    return data


def generate(proposal_id: str, fingerprint: str) -> bytes:
    with planning.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
        return _generate(proposal_id,fingerprint)


def generate_csv(proposal_id: str, fingerprint: str) -> bytes:
    with planning.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
        _generate(proposal_id,fingerprint)
        proposal=conn.execute('SELECT record_refs FROM planning_mtg.output_proposals WHERE id=%s',(uuid.UUID(proposal_id),)).fetchone()
        return macro.csv_bytes(_macro_rows(_records([r['id'] for r in proposal['record_refs']])))
