"""Canonical physical needs, audited choices and PDF/plan source adapters.

Only planning_mtg is written. Source values are fetched server-side; request
payloads cannot impersonate a PDF or a validated production record.
"""
from __future__ import annotations
import hashlib
from contextlib import nullcontext
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from psycopg.types.json import Jsonb
from . import planning, planning_catalogs as catalogs
from .dossiers.models import order_number
from . import planning_registration as registration

PIECE_FIELDS=tuple(f['id'] for f in catalogs.fields() if f['scope']=='piece')
TECH_FIELDS=tuple(k for k in PIECE_FIELDS if k not in ('quantity_required',))
# Campos da preparação que nunca seguem a origem: a operação liga a ficha, a quantidade a planear é calculada,
# a «Qtd em falta» só existe escrita e o Picking é da OF (decide-o planning_dates.picking_values).
OPERATION_OWN=('operation','quantity_to_plan','remaining_declared','picking_week','picking_year')
# Todos os outros campos da preparação seguem a origem quando ninguém os escreveu (08/10, F20), como os da peça:
# antes eram só 7, e uma edição na Tabela, que grava a linha inteira, congelava os restantes (Chanfro, Requisição…).
OPERATION_FOLLOW=tuple(f['id'] for f in catalogs.fields() if f['scope']!='piece' and f['id'] not in OPERATION_OWN)


def serial(value):
    return json.loads(json.dumps(value,ensure_ascii=False,default=lambda v:float(v) if isinstance(v,Decimal) else str(v) if isinstance(v,uuid.UUID) else v.isoformat(),allow_nan=False))


def digest(value):
    return hashlib.sha256(json.dumps(serial(value),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def uid(value):
    try:return uuid.UUID(str(value))
    except (ValueError,TypeError):raise planning.PlanningError('Identificador inválido.') from None


def command(conn,payload):
    request=uid(payload.get('request_id'));actor=registration.human_actor(payload)
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
    old=conn.execute('SELECT * FROM planning_mtg.need_commands WHERE request_id=%s',(request,)).fetchone()
    if old and old['request_hash']!=digest(payload):raise planning.PlanningError('Este pedido já foi usado para outros valores.',409)
    return request,actor,old['result'] if old else None


def finish(conn,payload,result):
    result=serial(result)
    conn.execute('INSERT INTO planning_mtg.need_commands(request_id,request_hash,result) VALUES (%s,%s,%s)',(uid(payload['request_id']),digest(payload),Jsonb(result)))
    from .raw.projection import signal
    signal(conn)
    return result


def event(conn,need,action,actor,detail):
    conn.execute('INSERT INTO planning_mtg.need_events(need_id,revision,action,actor,detail) VALUES (%s,%s,%s,%s,%s)',(need['id'],need['revision'],action,actor,Jsonb(serial(detail))))
    for link in conn.execute("SELECT payload FROM planning_mtg.need_sources WHERE need_id=%s AND kind='pdf'",(need['id'],)).fetchall():
        p=link['payload']; eid=uuid.uuid4()
        conn.execute('INSERT INTO planning_mtg.audit_outbox(id,document_id,piece_id,event) VALUES (%s,%s,%s,%s)',
                     (eid,p['document_id'],p['piece_id'],Jsonb(serial({'action':action,'actor':actor,'need_id':need['id'],'detail':detail}))))


def load(conn,need_id,expected=None):
    row=conn.execute('SELECT * FROM planning_mtg.needs WHERE id=%s',(uid(need_id),)).fetchone()
    if not row:raise planning.PlanningError('Necessidade não encontrada.',404)
    if expected is not None and row['revision']!=expected:raise planning.PlanningError('A necessidade mudou. Reabre a ficha para comparar a revisão atual.',409)
    return row


def source_data(source,area,conn):
    if not source:return None
    kind=source.get('kind');sid=str(source.get('id') or '')
    if kind=='pdf':
        from .dossiers import store
        doc=store.get_document(str(source.get('document_id') or sid.split('/')[0]))
        piece_id=str(source.get('piece_id') or sid.split('/')[-1])
        piece=next((p for p in doc['pieces'] if p['id']==piece_id),None)
        if not piece or piece['state'] in ('excluded','superseded'):raise planning.PlanningError('A peça PDF não está disponível.',409)
        if doc['status'] in ('queued','indexing','extracting','matching'):raise planning.PlanningError('Aguarda a leitura do documento.',409)
        version=f"{doc['revision']}:{piece['revision']}"
        result={'kind':kind,'id':doc['id']+'/'+piece['id'],'version':version,'of':doc['production_order'],
                'document_id':doc['id'],'piece_id':piece['id'],'values':piece['values'],
                'pages':piece.get('drawing_pages',[]),'raw_evidence':piece['values'].get('evidence',{})}
    elif kind=='plan_line':
        info=planning.snapshot(conn,area)
        rows=planning._source_rows(conn,info['snapshot_id'],plan_key=sid)
        equivalent_version=None
        if not rows:
            # A new file hash changes every imported ID. A retained RAW row is
            # editable only if its complete source row is still identical at
            # the same Excel position; matching OF/ref alone is insufficient.
            matches=conn.execute('''SELECT n.source_line_id,o.snapshot_id previous_snapshot
                FROM raw_mtg.plan_production_rows o
                JOIN audit_mtg.snapshots s ON s.snapshot_id=o.snapshot_id
                JOIN raw_mtg.plan_production_rows n ON n.snapshot_id=%s AND n.excel_row=o.excel_row
                AND (to_jsonb(n)-'snapshot_id'-'source_line_id')=(to_jsonb(o)-'snapshot_id'-'source_line_id')
                WHERE o.source_line_id=%s AND s.dataset_id=%s''',
                (info['snapshot_id'],sid,planning.AREAS[area][0])).fetchall()
            if len(matches)==1:
                equivalent_version=matches[0]['previous_snapshot']
                rows=planning._source_rows(conn,info['snapshot_id'],plan_key=matches[0]['source_line_id'])
        if not rows:
            historical=conn.execute("SELECT payload FROM planning_mtg.need_sources WHERE kind='plan_line' AND source_id=%s",(sid,)).fetchone()
            if historical:
                frozen=historical['payload']
                from .raw.edits import macro_candidates
                candidates=macro_candidates(conn,area,order_number(frozen['of']),frozen['values'])
                exact=[r for r in candidates if r['exact']]
                if len(exact)==1:
                    rows=planning._source_rows(conn,info['snapshot_id'],plan_key=exact[0]['plan_key'])
        if len(rows)!=1:raise planning.PlanningError('A linha da macro mudou ou tem várias candidatas. Volta a selecioná-la.',409)
        line=planning.line_data(rows[0],area,{})
        result={'kind':kind,'id':rows[0]['source_line_id'],'version':info['snapshot_id'],'of':rows[0]['production_order_no'],'values':line['values'],'line':serial(rows[0])}
        if area=='cantoneiras':
            raw=rows[0].get('row_data') or {}
            result['values']['operation']=catalogs.clean(raw.get('1ª Oper.'))
            result['values']['operation_detail']=catalogs.clean(raw.get('2ª Oper.'))
    else:raise planning.PlanningError('Origem desconhecida.')
    if source.get('version') is not None and str(source['version'])!=result['version'] and not (kind=='plan_line' and str(source['version'])==equivalent_version):raise planning.PlanningError('A origem mudou. Atualiza as sugestões antes de guardar.',409)
    return serial(result)


def signature(values):
    # No aggressive punctuation stripping: meaningful reference variants survive.
    result={}
    for k in ('component_ref','identity_discriminator','material_type','profile','grade','length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg'):
        value=values.get(k)
        if value in (None,''):value=None
        elif k.endswith('_mm') or k=='angle_deg':value=planning._number(value)
        elif isinstance(value,str):value=catalogs.key(value)
        result[k]=value
    return result


def complete(values):
    return bool(values.get('component_ref') and values.get('profile') and values.get('length_mm'))


def equal_value(a,b):
    return (None if a=='' else a)==(None if b=='' else b)


def expected_revision(payload):
    value=payload.get('expected_revision')
    if type(value) is not int or value<1:raise planning.PlanningError('Indica a revisão da necessidade que estás a editar.',409)
    return value


def linked_sources(conn,need_id):
    return conn.execute('SELECT * FROM planning_mtg.need_sources WHERE need_id=%s ORDER BY kind,source_id',(need_id,)).fetchall()


def follow(conn,need,origin,values,previous=None):
    """A origem mudou (07/10/2026): o campo que ninguém escreveu passa sozinho para o valor novo.

    «Escrito» é uma decisão explícita (write/select/clear); a sugestão aceite e o valor recebido seguem a
    origem. O valor escrito à mão fica e o ecrã mostra o da origem como nota (requires_review) enquanto
    forem diferentes. Vale para os campos da peça e para todos os da preparação em OPERATION_FOLLOW (Data
    Corte, Máquina, Equipa, Pav., Observações, Chanfro, Requisição…), também os que não têm estado (a Tabela
    grava as células vazias sem estado; 08/10); um campo que a origem não traz fica como está. Só se segue
    quando o valor da origem mudou desde a revisão anterior (`previous`; sem ela, a sugestão guardada): uma
    importação nova com o mesmo conteúdo não apaga a sugestão que ficou onde o Excel não tem nada. Devolve os
    campos que seguiram; a revisão da peça fica a cargo de quem chama.
    """
    def moved(suggestion,name,new):
        if previous is None:return not equal_value(suggestion,new)
        if name not in previous:return True
        old=catalogs.abocardar_mark(previous[name]) if name=='abocardar' else previous[name]
        return not equal_value(old,new)
    taken={}
    for state in conn.execute("SELECT * FROM planning_mtg.field_state WHERE need_id=%s AND scope='piece' AND field=ANY(%s)",(need['id'],[k for k in PIECE_FIELDS if k in values])).fetchall():
        name=state['field'];new=values.get(name)
        untouched=state['human_decision'] in (None,'accept')
        take=untouched and moved(state['suggestion'],name,new) and not equal_value(state['value'],new)
        if take:taken[name]=new
        conn.execute("UPDATE planning_mtg.field_state SET value=%s,suggestion=%s,source=%s,requires_review=%s WHERE need_id=%s AND scope='piece' AND field=%s",
                     (Jsonb(new if take else state['value']),Jsonb(new),Jsonb(origin),not untouched and not equal_value(state['value'],new),need['id'],name))
    if taken:
        spec={**need['specification'],**taken};qty=planning._number(spec.get('quantity_required'))
        # Um campo técnico que segue a origem é uma revisão técnica: as associações de produção ficam por rever.
        technical=need['technical_revision']+(1 if any(name in TECH_FIELDS for name in taken) else 0)
        conn.execute('UPDATE planning_mtg.needs SET specification=%s,quantity_required=%s,component_ref=%s,discriminator=%s,input_values=input_values||%s,technical_revision=%s WHERE id=%s',
            (Jsonb(spec),qty if qty is not None and qty>=0 and qty.is_integer() else None,catalogs.clean(spec.get('component_ref')),
             catalogs.clean(spec.get('identity_discriminator')),Jsonb(serial(taken)),technical,need['id']))
        revision=need['revision'];need.update(load(conn,need['id']));need['revision']=revision
    followed=[k for k in OPERATION_FOLLOW if k in values]
    for record in conn.execute('SELECT id,operation_id,values_json FROM planning_mtg.records WHERE need_id=%s AND operation_id IS NOT NULL',(need['id'],)).fetchall():
        scope=str(record['operation_id']);patch={}
        states={s['field']:s for s in conn.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s AND scope=%s AND field=ANY(%s)',(need['id'],scope,followed)).fetchall()}
        for name in followed:
            new=catalogs.abocardar_mark(values[name]) if name=='abocardar' else values[name]
            state=states.get(name)
            if state is None:
                # Sem estado ninguém o escreveu: segue a origem e passa a ter estado, com ela como fonte (08/10).
                current=(record['values_json'] or {}).get(name)
                if moved(current,name,new) and not equal_value(current,new):
                    patch[name]=new
                    conn.execute('''INSERT INTO planning_mtg.field_state(need_id,scope,field,value,suggestion,source,revision)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(need_id,scope,field) DO NOTHING''',
                        (need['id'],scope,name,Jsonb(new),Jsonb(new),Jsonb(origin),need['revision']))
                continue
            untouched=state['human_decision'] in (None,'accept')
            take=untouched and moved(state['suggestion'],name,new) and not equal_value(state['value'],new)
            if take:patch[name]=new
            conn.execute('UPDATE planning_mtg.field_state SET value=%s,suggestion=%s,source=%s,requires_review=%s WHERE need_id=%s AND scope=%s AND field=%s',
                         (Jsonb(new if take else state['value']),Jsonb(new),Jsonb(origin),not untouched and not equal_value(state['value'],new),need['id'],scope,name))
        if patch:
            conn.execute('UPDATE planning_mtg.records SET values_json=values_json||%s,input_values=input_values||%s,updated_at=now() WHERE id=%s',
                         (Jsonb(serial(patch)),Jsonb(serial(patch)),record['id']))
            taken.update(patch)
    return taken


def refresh(conn,need,actor='sistema',*,kinds=None):
    """Follow a changed source (see follow). A human effective value is never overwritten."""
    for link in linked_sources(conn,need['id']):
        if kinds is not None and link['kind'] not in kinds:continue
        original=link['payload'];area=original.get('area','perfis')
        try:current=source_data({'kind':link['kind'],'id':link['source_id']},area,conn)
        except planning.PlanningError:continue
        current['area']=area
        if current['version']==link['version']:continue
        conn.execute('UPDATE planning_mtg.need_sources SET version=%s,payload=%s,updated_at=now() WHERE kind=%s AND source_id=%s',
                     (current['version'],Jsonb(current),link['kind'],link['source_id']))
        taken=follow(conn,need,{'kind':link['kind'],'id':link['source_id'],'version':current['version']},current['values'],original.get('values'))
        need['revision']+=1
        conn.execute('UPDATE planning_mtg.needs SET revision=%s,updated_at=now() WHERE id=%s',(need['revision'],need['id']))
        event(conn,need,'source_updated',actor,{'previous':original,'current':current,'followed':taken})
        from .raw.projection import signal
        signal(conn,'linked_sources')
    return need


def resolve(payload, conn=None):
    area=planning.check_area(payload.get('area','perfis'))
    with (planning.connect() if conn is None else nullcontext(conn)) as conn:
        _,actor,old=command(conn,payload)
        if old:return old
        src=source_data(payload.get('source'),area,conn)
        values=dict(src['values'] if src else payload.get('values') or {})
        if src and payload.get('create_distinct'):
            values['identity_discriminator']=(payload.get('values') or {}).get('identity_discriminator')
        of=order_number(src['of'] if src else payload.get('production_order_no'))
        if not of:raise planning.PlanningError('Confirma a OF. Sufixos documentais não são removidos automaticamente.')
        link=conn.execute('SELECT need_id FROM planning_mtg.need_sources WHERE kind=%s AND source_id=%s',(src['kind'],src['id'])).fetchone() if src else None
        if link:
            need=refresh(conn,load(conn,link['need_id']),actor)
            return finish(conn,payload,{'need_id':need['id'],'revision':need['revision'],'reused':True})
        candidates=conn.execute('SELECT * FROM planning_mtg.needs WHERE production_order_no=%s ORDER BY created_at',(of,)).fetchall()
        similar=[n for n in candidates if catalogs.key(n['component_ref'])==catalogs.key(values.get('component_ref'))]
        exact=[n for n in similar if complete(values) and signature(n['specification'])==signature(values)]
        if payload.get('need_id'):
            need=load(conn,payload['need_id'],payload.get('expected_revision'))
            if need['production_order_no']!=of:raise planning.PlanningError('A necessidade pertence a outra OF.',409)
        elif len(exact)==1 and exact[0]['quantity_required']==planning._number(values.get('quantity_required')):need=exact[0]
        elif similar and not payload.get('create_distinct') and not payload.get('_allow_unresolved'):
            return {'needs_decision':True,'candidates':serial(similar),'suggestion':values,'source':src,'production_order_no':of}
        else:
            # Uma peça semelhante conta como peça própria (07/10/2026): nunca fica «por associar».
            need_id=uuid.uuid4();spec={k:values.get(k) for k in PIECE_FIELDS}
            qty=planning._number(values.get('quantity_required'))
            if qty is not None and (qty<0 or not qty.is_integer()):qty=None
            conn.execute('INSERT INTO planning_mtg.needs(id,production_order_no,original_order,component_ref,discriminator,specification,quantity_required,actor) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (need_id,of,str(src['of'] if src else payload.get('production_order_no')),catalogs.clean(values.get('component_ref')),catalogs.clean(values.get('identity_discriminator')),Jsonb(spec),qty,actor))
            need=load(conn,need_id)
            event(conn,need,'created',actor,{'specification':spec,'source':src})
        if src:
            need['revision']+=1
            conn.execute('UPDATE planning_mtg.needs SET revision=%s,updated_at=now() WHERE id=%s',(need['revision'],need['id']))
            src['area']=area
            conn.execute('INSERT INTO planning_mtg.need_sources(kind,source_id,need_id,version,payload) VALUES (%s,%s,%s,%s,%s)',(src['kind'],src['id'],need['id'],src['version'],Jsonb(src)))
            for name in PIECE_FIELDS:
                if name not in values:continue
                origin={'kind':src['kind'],'id':src['id'],'version':src['version']}
                prior=conn.execute("SELECT value FROM planning_mtg.field_state WHERE need_id=%s AND scope='piece' AND field=%s",(need['id'],name)).fetchone()
                review=bool(prior and not equal_value(prior['value'],values.get(name)))
                conn.execute('''INSERT INTO planning_mtg.field_state(need_id,scope,field,value,suggestion,source,revision)
                    VALUES (%s,'piece',%s,%s,%s,%s,%s) ON CONFLICT(need_id,scope,field) DO UPDATE SET suggestion=excluded.suggestion,source=excluded.source''',
                    (need['id'],name,Jsonb(need['specification'].get(name)),Jsonb(values.get(name)),Jsonb(origin),need['revision']))
                if review:conn.execute("UPDATE planning_mtg.field_state SET requires_review=true WHERE need_id=%s AND scope='piece' AND field=%s",(need['id'],name))
            event(conn,need,'source_linked',actor,{'source':src,'reason':payload.get('reason')})
        return finish(conn,payload,{'need_id':need['id'],'revision':need['revision'],'reused':bool(exact or payload.get('need_id'))})


def list_needs(of=None, *, population='active', area=None):
    from . import planning_population, planning_order_population, planning_hub
    population=planning_population.scope(population)
    if area is not None:planning.check_area(area)
    with planning.connect(readonly=True) as conn:
        rows=conn.execute('SELECT * FROM planning_mtg.needs WHERE (%s::text IS NULL OR production_order_no=%s) ORDER BY updated_at DESC,id',(order_number(of) if of else None,order_number(of) if of else None)).fetchall()
        ofs=sorted({r['production_order_no'] for r in rows})
        members,_=planning_order_population.read(conn,planning_hub._latest_snapshots(conn),orders=ofs)
        copies={}
        for r in planning_hub._order_rows(conn,planning_hub._direct_version(conn),'',None,only_ofs=ofs):
            copies.setdefault(order_number(r['production_order_no']),[]).append(r)
        contexts={key:planning_hub._order_summary(value) for key,value in copies.items()}
        planning_order_population.summarize(members,contexts)
        grouped={}
        for m in members:
            if m['need_id'] and (area is None or m['area']==area):grouped.setdefault(m['need_id'],[]).append(m)
        selected=[]
        for r in rows:
            candidates=grouped.get(str(r['id']),[])
            if area is not None and not candidates:
                continue
            if any(planning_population.includes(m,population) for m in candidates) or (
                    not candidates and planning_population.includes(contexts.get(r['production_order_no'],{}),population)):
                selected.append(r)
        total=len(selected)
        rows=selected[:500]
    return serial({'population':population,'total':total,'needs':rows,'rows':[{'need_id':r['id'],'production_order':r['production_order_no'],'values':r['specification'],'context':{},'machine_group':'Por definir','filename':'Preparação comum','document_id':None,'state':'draft'} for r in rows]})


def need_for_pdf(document, piece):
    """Resolve a previously linked document without creating or changing a need."""
    with planning.connect(readonly=True) as conn:
        row=conn.execute("SELECT need_id FROM planning_mtg.need_sources WHERE kind='pdf' AND source_id=%s",
                         (str(document)+'/'+str(piece),)).fetchone()
    return serial({'need_id':row['need_id'] if row else None})


def detail(need_id):
    from . import planning_local_orders
    with planning.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
        need=refresh(conn,load(conn,need_id))
        operations=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE need_id=%s ORDER BY sequence,code',(need['id'],)).fetchall()
        records=conn.execute('SELECT * FROM planning_mtg.records WHERE need_id=%s ORDER BY updated_at',(need['id'],)).fetchall()
        states=conn.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s ORDER BY scope,field',(need['id'],)).fetchall()
        sources=linked_sources(conn,need['id'])
        return serial({'need':need,'operations':operations,'records':records,'fields':states,'sources':sources,
                       'local_order':planning_local_orders.read(conn,need['production_order_no']),
                       'registration':registration.read(need['production_order_no'],conn)})


def save(payload, conn=None, source_defaults=None):
    """Grava a preparação. Desde 07/10/2026 grava sempre: sem validação do catálogo, sem conclusão
    dependente do CPIS direto e sem «por associar»; os avisos essenciais vêm em registration_warnings."""
    from .raw import registration as free
    area=planning.check_area(payload.get('area'))
    with (planning.connect() if conn is None else nullcontext(conn)) as conn:
        request,actor,old=command(conn,payload)
        if old:return old
        need=refresh(conn,load(conn,payload.get('need_id')))
        load(conn,need['id'],expected_revision(payload))
        cat=catalogs.catalog(area,conn)
        status=payload.get('record_status','draft')
        if status not in ('draft','ready'):raise planning.PlanningError('Estado de preparação inválido.')
        raw=dict(payload.get('values') or {})
        # Sem operação no pedido: a da preparação que a peça já tem, só depois o valor por defeito.
        existing=conn.execute('SELECT o.code FROM planning_mtg.records r JOIN planning_mtg.need_operations o ON o.id=r.operation_id WHERE r.need_id=%s AND r.area=%s ORDER BY r.updated_at DESC LIMIT 1',(need['id'],area)).fetchone()
        code=str(raw.get('operation') or (source_defaults or {}).get('operation') or (existing or {}).get('code') or free.DEFAULTS[area]['operation'])
        raw['operation']=code
        op=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE need_id=%s AND area=%s AND code=%s',(need['id'],area,code)).fetchone()
        oldrecord=conn.execute('SELECT * FROM planning_mtg.records WHERE operation_id=%s',(op['id'],)).fetchone() if op else None
        previous={**(source_defaults or {}),**(oldrecord['values_json'] if oldrecord else {}),**need['specification']}
        entered={**previous,**((oldrecord or {}).get('input_values') or {}),**(need.get('input_values') or {}),**raw}
        from .raw.calculations import sections
        vals,registration_warnings=free.normalize(entered,cat,previous,sections=sections(conn,cat['version']) if area=='perfis' else None)
        decisions=payload.get('decisions') or {}
        # Só é decisão humana o que o utilizador mudou (changed_fields); sem essa lista, o que o pedido trouxe.
        listed=payload.get('changed_fields')
        typed=set(decisions)|(set(listed) if isinstance(listed,list) else set(payload.get('values') or {}))
        typed-={k for k,a in decisions.items() if a=='clear' and k in free.DEFAULTS[area]}
        unknown=set(decisions)-{f['id'] for f in cat['fields']}
        if unknown:raise planning.PlanningError('O pedido inclui campos desconhecidos.')
        before=dict(need['specification']); spec={k:vals.get(k) for k in PIECE_FIELDS}
        technical_changed=any(before.get(k)!=spec.get(k) for k in TECH_FIELDS)
        need['revision']+=1
        if technical_changed:need['technical_revision']+=1
        conn.execute('UPDATE planning_mtg.needs SET component_ref=%s,discriminator=%s,specification=%s,quantity_required=%s,revision=%s,technical_revision=%s,actor=%s,updated_at=now() WHERE id=%s',
                     (vals['component_ref'],vals['identity_discriminator'],Jsonb(spec),vals['quantity_required'],need['revision'],need['technical_revision'],actor,need['id']))
        need=load(conn,need['id'])
        if not op:
            op={'id':uuid.uuid4(),'need_id':need['id'],'area':area,'code':code,'sequence':next((x['sequence'] for x in cat['operations']+cat['additional_operations'] if x['value']==code),1)}
            conn.execute('INSERT INTO planning_mtg.need_operations(id,need_id,area,code,sequence) VALUES (%s,%s,%s,%s,%s)',tuple(op[k] for k in ('id','need_id','area','code','sequence')))
        extra=next((x for x in cat['additional_operations'] if x['value']==vals['operation_detail'] and x['countable']),None)
        if extra and extra['value']!=code:
            conn.execute('INSERT INTO planning_mtg.need_operations(id,need_id,area,code,sequence) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(need_id,area,code) DO NOTHING',
                         (uuid.uuid4(),need['id'],area,extra['value'],extra['sequence']))
        if area=='perfis' and vals['abocardar']=='X':
            # Separate evidence scope, not a second physical need or production event.
            conn.execute("INSERT INTO planning_mtg.need_operations(id,need_id,area,code,sequence) VALUES (%s,%s,'perfis','abocardar',2) ON CONFLICT(need_id,area,code) DO NOTHING",(uuid.uuid4(),need['id']))
        changes=[]
        for f in cat['fields']:
            name=f['id']; scope='piece' if f['scope']=='piece' else str(op['id'])
            if name in catalogs.RETIRED_FIELDS and name not in raw and source_defaults is None:continue
            state=conn.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s AND scope=%s AND field=%s',(need['id'],scope,name)).fetchone()
            action=decisions.get(name)
            if action not in (None,'accept','write','select','clear'):raise planning.PlanningError('Decisão de campo desconhecida.')
            if status=='ready' and state and not action and not state['human_decision'] and equal_value(vals[name],state['suggestion']):action='accept'
            # Limpar um campo com valor por defeito (1.ª/2.ª Oper., Operação) é voltar ao valor por defeito, sem decisão.
            if action=='clear' and name in free.DEFAULTS[area]:action=None
            if action=='clear' and vals[name] not in ('',None,False):raise planning.PlanningError('Limpar exige um valor vazio.')
            # A RAW cell edit is not acceptance of every other imported cell.
            # Defaults are supplied by the server, never by HTTP provenance claims.
            if state is None and source_defaults is not None and name not in raw:
                if vals[name] not in (None,''):
                    origins=[s for s in linked_sources(conn,need['id']) if s['kind']=='plan_line' and s['payload'].get('area')==area]
                    origin={'kind':'plan_line','id':origins[0]['source_id'],'version':origins[0]['version']} if len(origins)==1 else {'kind':'historical','detail':'Origem detalhada não disponível'}
                    conn.execute('''INSERT INTO planning_mtg.field_state(need_id,scope,field,value,suggestion,source,revision)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)''',(need['id'],scope,name,Jsonb(vals[name]),Jsonb(vals[name]),Jsonb(origin),need['revision']))
                continue
            changed=not state or state['value']!=vals[name]
            if changed and not action and name in typed:action='select' if f['type']=='select' else 'write'
            if action or changed:
                origin=state['source'] if state else {'kind':'manual'}
                # Uma mudança que o utilizador não fez (valor por defeito, linha do Excel) não passa a decisão humana.
                human=action or (state['human_decision'] if state else None)
                decision_origin={'kind':'catalog' if action=='select' else 'accepted_suggestion' if action=='accept' else 'human' if action else 'implicit','source_seen':origin,'catalog_version':cat['version'] if f['type']=='select' else None}
                conn.execute('''INSERT INTO planning_mtg.field_state(need_id,scope,field,value,suggestion,source,human_decision,actor,decided_at,revision,decision_source)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s) ON CONFLICT(need_id,scope,field) DO UPDATE SET value=excluded.value,human_decision=excluded.human_decision,actor=excluded.actor,decided_at=excluded.decided_at,revision=excluded.revision,requires_review=false,decision_source=excluded.decision_source''',
                    (need['id'],scope,name,Jsonb(vals[name]),Jsonb(state['suggestion'] if state else None),Jsonb(origin),human,actor,need['revision'],Jsonb(decision_origin)))
                changes.append({'field':name,'scope':scope,'before':state['value'] if state else None,'after':vals[name],'decision':action,'decision_source':decision_origin,'suggestion':state['suggestion'] if state else None,'source':origin})
        from .planning_hub import _direct_version
        direct=_direct_version(conn); version=str(direct['id']) if direct else None
        rid=oldrecord['id'] if oldrecord else uuid.uuid4(); revision=oldrecord['revision']+1 if oldrecord else 1
        fields=conn.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s',(need['id'],)).fetchall()
        provenance=serial({f["scope"]+':'+f['field']:f for f in fields})
        srcs=linked_sources(conn,need['id']); plan=next((s for s in srcs if s['kind']=='plan_line' and s['payload'].get('area')==area),None)
        # «Qtd em falta»: guarda a produção que o cálculo conhecia quando foi escrita; a produção registada
        # depois desconta-se do valor escrito (planning_calculations.calculate).
        # Voltar a escrever o mesmo valor (changed_fields) também recomeça a contagem.
        stored=(oldrecord or {}).get('values_json') or {}
        declared=vals.get('remaining_declared')
        retyped=isinstance(listed,list) and 'remaining_declared' in listed
        baseline=declared is not None and (retyped or declared!=stored.get('remaining_declared') or 'remaining_declared_produced' not in stored)
        if declared is not None and not baseline:
            vals.update(remaining_declared_produced=stored.get('remaining_declared_produced'),remaining_declared_origin=stored.get('remaining_declared_origin'))
        values_json=Jsonb(vals)
        if oldrecord:
            conn.execute('UPDATE planning_mtg.records SET values_json=%s,component_ref=%s,revision=%s,actor=%s,record_status=%s,source_version=%s,provenance_json=%s,updated_at=now() WHERE id=%s',
                         (values_json,vals['component_ref'],revision,actor,status,version,Jsonb(provenance),rid))
        else:
            conn.execute('''INSERT INTO planning_mtg.records(id,area,production_order_no,component_ref,source_payload,values_json,revision,actor,source_kind,source_id,source_version,record_status,provenance_json,need_id,operation_id,source_plan_key,source_snapshot_id)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'need',%s,%s,%s,%s,%s,%s,%s,%s)''',
             (rid,area,need['production_order_no'],vals['component_ref'],Jsonb({'need_id':str(need['id'])}),values_json,revision,actor,str(need['id']),version,status,Jsonb(provenance),need['id'],op['id'],plan['source_id'] if plan else None,plan['version'] if plan else None))
        if baseline:
            vals['remaining_declared_produced'],vals['remaining_declared_origin']=produced_now(conn,area,need,'corte' if area=='perfis' else code)
            values_json=Jsonb(vals)
            conn.execute('UPDATE planning_mtg.records SET values_json=%s WHERE id=%s',(values_json,rid))
        conn.execute('''INSERT INTO planning_mtg.record_versions(request_id,request_hash,record_id,revision,source_payload,values_json,actor,source_kind,source_id,source_version,record_status,provenance_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'need',%s,%s,%s,%s)''',
            (request,digest(payload),rid,revision,Jsonb({'need_id':str(need['id'])}),values_json,actor,str(need['id']),version,status,Jsonb(provenance)))
        inputs={**((oldrecord or {}).get('input_values') or {}),**(payload.get('values') or {})}
        piece_inputs={**(need.get('input_values') or {}),**{k:v for k,v in (payload.get('values') or {}).items() if k in PIECE_FIELDS}}
        conn.execute('UPDATE planning_mtg.needs SET input_values=%s WHERE id=%s',(Jsonb(piece_inputs),need['id']))
        conn.execute('UPDATE planning_mtg.records SET input_values=%s,registration_warnings=%s WHERE id=%s',
            (Jsonb(inputs),Jsonb(registration_warnings),rid))
        conn.execute('UPDATE planning_mtg.record_versions SET input_values=%s,registration_warnings=%s WHERE record_id=%s AND revision=%s',
            (Jsonb(inputs),Jsonb(registration_warnings),rid,revision))
        event(conn,need,'input_saved',actor,{'entered':payload.get('values') or {},'warnings':registration_warnings,
            'changes':[{'field':k,'scope':'piece' if k in PIECE_FIELDS else str(op['id']),
                'before':((oldrecord or {}).get('input_values') or {}).get(k),'after':v} for k,v in (payload.get('values') or {}).items()]})
        from .raw import sku_families
        sku_families.ensure(conn,area,[vals['component_ref']],source='manual_registration')
        event(conn,need,'preparation_saved',actor,{'changes':changes,'operation_id':str(op['id']),'technical_changed':technical_changed,'status':status})
        first=registration.read(need['production_order_no'],conn)
        registered=registration.register(conn,need['production_order_no'])
        if not first:event(conn,need,'material_request_forecast','Sistema',registered)
        return finish(conn,payload,{'need_id':need['id'],'revision':need['revision'],'record_id':rid,'record_revision':revision,'operation_id':op['id'],'record_status':status,'registration':registered,'registration_warnings':registration_warnings,'identity_pending':False,'quantity_to_plan':vals['quantity_to_plan'],'_compatibility_hash':payload.get('_compatibility_hash')})


def produced_now(conn,area,need,operation):
    """(produção, fonte) que o cálculo conhece agora para a operação principal da peça; produção None se desconhecida."""
    from .raw.projection import build_rows
    rows,_,_=build_rows(conn,area,orders=[need['production_order_no']])
    row=next((r for r in rows if r['need_id']==str(need['id'])),None)
    source=next((s for s in ((row or {}).get('calculation') or {}).get('production_sources',[]) if str(s.get('operation'))==str(operation)),None)
    return (source or {}).get('measured'),(source or {}).get('measured_origin')


def history(need_id):
    with planning.connect(readonly=True) as conn:
        need=load(conn,need_id)
        return serial({'need':need,'fields':conn.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s ORDER BY scope,field',(need['id'],)).fetchall(),
                       'events':conn.execute('SELECT * FROM planning_mtg.need_events WHERE need_id=%s ORDER BY id DESC',(need['id'],)).fetchall()})


def deliver_outbox(limit=100):
    from .dossiers import store
    delivered=0
    with planning.connect() as conn:
        rows=conn.execute('SELECT * FROM planning_mtg.audit_outbox WHERE delivered_at IS NULL ORDER BY created_at LIMIT %s FOR UPDATE SKIP LOCKED',(limit,)).fetchall()
        for row in rows:
            try:
                with store.connect() as local:
                    local.execute('CREATE TABLE IF NOT EXISTS planning_event_receipts(id TEXT PRIMARY KEY)')
                    if not local.execute('SELECT 1 FROM planning_event_receipts WHERE id=?',(str(row['id']),)).fetchone():
                        data=row['event']
                        store.event(local,row['document_id'],'planning:'+data['action'],data,piece_id=row['piece_id'],actor=data['actor'])
                        local.execute('INSERT INTO planning_event_receipts VALUES (?)',(str(row['id']),))
                conn.execute('UPDATE planning_mtg.audit_outbox SET delivered_at=now(),attempts=attempts+1,last_error=NULL WHERE id=%s',(row['id'],));delivered+=1
            except Exception as exc:
                conn.execute('UPDATE planning_mtg.audit_outbox SET attempts=attempts+1,last_error=%s WHERE id=%s',(type(exc).__name__,row['id']))
    return {'delivered':delivered}


def migrate_legacy_records():
    """Repeatable additive binding. Ambiguous rows remain historical and reported."""
    with planning.connect(readonly=True) as conn:
        rows=conn.execute('SELECT * FROM planning_mtg.records WHERE need_id IS NULL ORDER BY created_at,id').fetchall()
    report={'bound':0,'review':[]}
    for row in rows:
        payload={'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'legacy-need:'+str(row['id']))),
                 'actor':row['actor'],'area':row['area'],'production_order_no':row['production_order_no'],'values':row['values_json']}
        result=resolve(payload)
        if result.get('needs_decision'):
            report['review'].append({'record_id':str(row['id']),'reason':'Identidade ambígua','candidates':[r['id'] for r in result['candidates']]});continue
        with planning.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
            need=load(conn,result['need_id']);code=row['values_json'].get('operation') or 'por_confirmar'
            op=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE need_id=%s AND area=%s AND code=%s',(need['id'],row['area'],code)).fetchone()
            if op and conn.execute('SELECT 1 FROM planning_mtg.records WHERE operation_id=%s',(op['id'],)).fetchone():
                report['review'].append({'record_id':str(row['id']),'reason':'Outra ficha para a mesma operação','need_id':str(need['id'])});continue
            oid=op['id'] if op else uuid.uuid4()
            if not op:conn.execute('INSERT INTO planning_mtg.need_operations(id,need_id,area,code) VALUES (%s,%s,%s,%s)',(oid,need['id'],row['area'],code))
            conn.execute('UPDATE planning_mtg.records SET need_id=%s,operation_id=%s WHERE id=%s',(need['id'],oid,row['id']))
            for f in catalogs.fields():
                origin={'kind':'historical','record_id':str(row['id']),'label':'Valor histórico — origem detalhada não disponível'}
                conn.execute('''INSERT INTO planning_mtg.field_state(need_id,scope,field,value,source,revision,actor)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                    (need['id'],'piece' if f['scope']=='piece' else str(oid),f['id'],Jsonb(row['values_json'].get(f['id'])),Jsonb(origin),need['revision'],row['actor']))
            event(conn,need,'legacy_bound',row['actor'],{'record_id':str(row['id']),'historical_revision':row['revision']})
            report['bound']+=1
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--migrate-legacy',action='store_true');parser.add_argument('--deliver-outbox',action='store_true');args=parser.parse_args()
    print(json.dumps(migrate_legacy_records() if args.migrate_legacy else deliver_outbox(),ensure_ascii=False))


def save_legacy_payload(payload):
    """Compatibility entrypoint; legacy callers must not bypass need identity."""
    if payload.get('need_id'):return save(payload)
    with planning.connect(readonly=True) as conn:
        previous=conn.execute('SELECT request_hash,result FROM planning_mtg.need_commands WHERE request_id=%s',(uid(payload.get('request_id')),)).fetchone()
        if previous:
            if previous['result'].get('_compatibility_hash')==digest(payload):
                result=previous['result'];return {**result,'id':result['record_id'],'revision':result['record_revision'],'replayed':True}
            raise planning.PlanningError('Este pedido já foi usado para outros valores.',409)
        record=conn.execute('SELECT * FROM planning_mtg.records WHERE id=%s',(uid(payload['record_id']),)).fetchone() if payload.get('record_id') else None
    if record:
        if record['revision']!=payload.get('revision'):raise planning.PlanningError('A ficha mudou. Reabre a revisão atual.',409)
        if not record.get('need_id'):raise planning.PlanningError('Esta ficha histórica precisa de conferência da identidade no formulário comum.',409)
        detail_data=detail(record['need_id']);nid=record['need_id']
    else:
        source={'kind':'plan_line','id':payload['plan_key'],'version':payload.get('snapshot_id')} if payload.get('plan_key') else None
        result=resolve({'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'legacy-resolve:'+str(payload['request_id']))),
            'actor':payload.get('actor'),'area':payload.get('area'),'production_order_no':payload.get('production_order_no'),
            'source':source,'values':payload.get('values')})
        if result.get('needs_decision'):raise planning.PlanningError('Há uma necessidade semelhante. Usa o formulário comum para associar a origem.',409)
        nid=result['need_id'];detail_data=detail(nid)
    cat=catalogs.catalog(payload.get('area'))
    result=save({'request_id':payload['request_id'],'actor':payload.get('actor'),'area':payload.get('area'),'need_id':str(nid),
        'expected_revision':detail_data['need']['revision'],'catalog_version':cat['version'],'values':payload.get('values'),
        'record_status':payload.get('record_status','draft'),'_compatibility_hash':digest(payload)})
    result.update(id=result['record_id'],revision=result['record_revision'],replayed=False)

    return result


def start_outbox_worker():
    import threading
    import logging
    stop=threading.Event()
    def work():
        while not stop.is_set():
            try:deliver_outbox()
            except Exception:logging.getLogger(__name__).exception('Document audit delivery pending')
            stop.wait(30)
    threading.Thread(target=work,name='planning-document-audit',daemon=True).start()
    return stop
