"""Independent original-sheet time reader for H03/H09/H10 acceptance.

Reads immutable source payloads and human decisions directly. It does not use
the application adapter, association validator or time resolver as an oracle.
"""
from datetime import date
from scripts.audit_planning_actual_hours import number

AREAS={'perfis','cantoneiras'}
VOLATILE={'id','validated_at','sheet_hours','sheet_date','sheet_iso_date','captured_at',
          'sheet_total_qty','sheet_status','human_fields'}


def declared_area(payload):
    return payload.get('area') or ((payload.get('data') or {}).get('header') or {}).get('area')


def valid_decision(sheet,line,decision,revisions):
    if not decision:return False
    evidence=decision['evidence'];payload=sheet['payload']
    # The source facts that identify production must still be the reviewed ones.
    if {k:v for k,v in line.items() if k not in VOLATILE}!={k:v for k,v in evidence.get('original',{}).items() if k not in VOLATILE}:return False
    if evidence.get('declared_area')!=declared_area(payload):return False
    if evidence.get('machine')!=(line.get('machine') or payload.get('machine')):return False
    return all(revisions.get(a['need_id'])==a['technical_revision'] for a in decision['allocations'])


def read(sheets,decisions,revisions):
    decisions={d['production_record_id']:d for d in decisions}
    observed=[];projections={}
    for sheet in sheets:
        payload=sheet['payload'];lines=payload.get('production',[])
        declared=declared_area(payload);areas=set();unknown=False
        key='original:'+str(sheet['instance_id'])+':'+str(sheet['sheet_id'])
        for line in lines:
            d=decisions.get(key+':'+str(line['row_index']))
            assigned={a['area'] for a in d['allocations']} if d and d['status']=='associated' and valid_decision(sheet,line,d,revisions) else set()
            known=assigned or ({declared} if declared in AREAS else set())
            areas.update(known);unknown=unknown or not known
        if unknown or not areas:areas.update({declared} if declared in AREAS else AREAS)
        raw=[line['sheet_hours'] for line in lines if line.get('sheet_hours') is not None]
        if not raw:
            footer=(payload.get('data') or {}).get('footer') or {}
            raw=[footer['horas_trabalhadas']] if footer.get('horas_trabalhadas') not in (None,'') else []
        values={number(h) for h in raw};hours=next(iter(values)) if len(values)==1 and None not in values else None
        machines=sorted({line.get('machine') or payload.get('machine') for line in lines}-{None,''})
        if not machines and payload.get('machine'):machines=[payload['machine']]
        dates=set()
        for line in lines:
            try:dates.add(str(date.fromisoformat(str(line['sheet_iso_date'])[:10])))
            except (ValueError,TypeError,KeyError):pass
        day=next(iter(dates)) if len(dates)==1 else None
        areas=sorted(areas);machine=machines[0] if len(machines)==1 else None
        projected={'sheet':sheet['sheet_id'],'source':'ocr_original','machine':machine,'hours_worked':hours,'production_date':day}
        observation={'key':key,'sheet_uid':key,'sheet':sheet['sheet_id'],'area':areas[0] if len(areas)==1 else None,
                     'areas':areas,'date':day,'machine':machine,'hours':hours,'origin':'OCR original',
                     'machines':machines or [machine],'original_hours':raw,'revision':sheet['source_revision'],
                     'source_content_hash':sheet['content_hash'],'instance_id':str(sheet['instance_id'])}
        if hours is not None and not 0<=hours<=24:
            observation['hours']=None;observation['hours_reason']='Horas da folha inválidas: exige um valor entre 0 e 24 h.'
        observed.append(observation)
        for area in areas:
            projections[area+':'+key]={'values':projected,'original_hours':raw,'original_machines':machines,
                'source_revision':sheet['source_revision'],'source_content_hash':sheet['content_hash'],
                'record_count':len(lines)}
    return observed,projections
