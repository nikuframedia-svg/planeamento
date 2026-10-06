"""Read-only HTTP evidence. Never manufacture native sheet identities or counters."""
from collections import Counter
from datetime import date, datetime, timezone
import io
import os
from urllib.request import urlopen

import openpyxl
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs

SOURCE = 'ocr-original-http-validado'
LIMIT = 32 * 1024 * 1024
NOTE = 'Exportação validada guardada. Associação às folhas por confirmar; não somada aos saldos de produção.'
HEADERS = {'OF','Modelo','QTD','Data','Setor / Máquina Desc.','Comprimento (mm)'}


def parse(content):
    book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = book.active
        records = iter(sheet.values)
        header = next(records)
        if not HEADERS.issubset(header) or len(set(header)) != len(header):
            raise ValueError('unexpected_export_columns')
        rows = []; occurrences = Counter(); dates = []
        for ordinal, cells in enumerate(records, 2):
            if not any(v is not None for v in cells):
                continue
            raw = needs.serial(dict(zip(header, cells)))
            content_hash = needs.digest(raw); occurrences[content_hash] += 1
            rawdate = raw.get('Data'); iso = None; flags = []
            if rawdate:
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        iso = datetime.strptime(str(rawdate), fmt).date().isoformat(); break
                    except ValueError:
                        pass
                if not iso:flags.append('invalid_production_date')
                elif iso > date.today().isoformat():flags.append('future_production_date')
                else:dates.append(iso)
            rows.append({'key':content_hash + ':' + str(occurrences[content_hash]),
                'export_line':ordinal, 'raw':raw, 'quality_flags':flags,
                'machine':raw.get('Setor / Máquina Desc.'),
                'data':{'of':raw.get('OF'), 'modelo':raw.get('Modelo'), 'qtd':raw.get('QTD'),
                        'comp_mm':raw.get('Comprimento (mm)'), 'sheet_iso_date':iso}})
        if not rows:raise ValueError('empty_validated_export')
        # Preserve duplicate occurrences INSIDE one export. Do not add versions.
        content_hash = needs.digest(sorted(occurrences.items()))
        return {'hash':content_hash, 'rows':rows,
                'metadata':{'latest_production_date':max(dates) if dates else None,
                            'flagged_rows':sum(bool(r['quality_flags']) for r in rows),
                            'native_identifiers_available':False}}
    finally:
        book.close()


def publish(c, package, url):
    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (SOURCE,))
    c.execute('INSERT INTO ocr_original.export_sources(id,source_url) VALUES(%s,%s) ON CONFLICT DO NOTHING', (SOURCE,url))
    version = needs.digest([SOURCE,package['hash']])
    exists = c.execute('SELECT id FROM ocr_original.export_versions WHERE id=%s', (version,)).fetchone()
    if not exists:
        if not package['rows']:raise ValueError('empty_validated_export')
        c.execute('INSERT INTO ocr_original.export_versions(id,source_id,content_hash,row_count,metadata) VALUES(%s,%s,%s,%s,%s)',
                  (version,SOURCE,package['hash'],len(package['rows']),Jsonb(package['metadata'])))
        with c.cursor().copy('COPY ocr_original.export_rows(version_id,row_key,payload) FROM STDIN') as copy:
            for row in package['rows']:copy.write_row((version,row['key'],Jsonb(row)))
    c.execute('UPDATE ocr_original.export_sources SET source_url=%s,current_version=%s,attempted_at=now(),confirmed_at=now(),last_error=NULL WHERE id=%s', (url,version,SOURCE))
    return {'rows':len(package['rows']), 'version':version, 'unchanged':bool(exists)}


def refresh():
    url = os.getenv('ORIGINAL_OCR_EXPORT_URL')
    dsn = os.getenv('ORIGINAL_OCR_PUBLISH_DSN')
    if not url or not dsn:return None
    try:
        with urlopen(url,timeout=90) as response:
            body = response.read(LIMIT+1)
        if len(body)>LIMIT:raise ValueError('export_too_large')
        package = parse(body)
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as c:
            return publish(c,package,url)
    except Exception as exc:
        # Retain the last complete version. Never expose connection secrets.
        with psycopg.connect(dsn,connect_timeout=5) as c:
            c.execute('INSERT INTO ocr_original.export_sources(id,source_url,attempted_at,last_error) VALUES(%s,%s,now(),%s) ON CONFLICT(id) DO UPDATE SET attempted_at=now(),last_error=excluded.last_error', (SOURCE,url,type(exc).__name__))
        raise


def status(c):
    if not c.execute("SELECT to_regclass('ocr_original.export_sources') t").fetchone()['t']:return None
    row = c.execute('SELECT s.*,v.row_count,v.metadata,v.captured_at FROM ocr_original.export_sources s LEFT JOIN ocr_original.export_versions v ON v.id=s.current_version WHERE s.id=%s', (SOURCE,)).fetchone()
    if not row or not row['current_version']:return None
    return needs.serial({'state':'available','mode':'validated_export','instances':[],
        'export':row,'included_in_planning_balances':False,'human_association_supported':False,
        'planning_publications':{},'note':NOTE})


def query(c, state, *, of='', model='', machine='', date_from='', date_to='', page=1):
    conditions = ['r.version_id=%s']; args = [state['export']['current_version']]
    if of:
        from ..dossiers.models import order_number
        normalized = order_number(of)
        if not normalized:raise planning.PlanningError('Indica uma OF válida.')
        conditions.append("regexp_replace(upper(r.payload->'data'->>'of'),'^OF[ ._-]*','')=%s");args.append(normalized[2:])
    for value,field in ((model,"r.payload->'data'->>'modelo'"),(machine,"r.payload->>'machine'")):
        if value:conditions.append(field+' ILIKE %s');args.append('%'+value+'%')
    for value,operator in ((date_from,'>='),(date_to,'<=')):
        if value:
            try:date.fromisoformat(value)
            except ValueError:raise planning.PlanningError('Indica datas válidas.') from None
            conditions.append("r.payload->'data'->>'sheet_iso_date' "+operator+' %s');args.append(value)
    base = ' FROM ocr_original.export_rows r WHERE '+' AND '.join(conditions)
    total = c.execute('SELECT count(*) n'+base,args).fetchone()['n']
    rows = c.execute('SELECT payload'+base+" ORDER BY payload->'data'->>'sheet_iso_date' DESC NULLS LAST,row_key LIMIT 50 OFFSET %s", args+[(page-1)*50]).fetchall()
    return {'records':[r['payload'] for r in rows], 'total':total, 'page':page, 'source':state}


def rebuild(c):
    from . import projection
    state = status(c)
    if not state:return None
    version = state['export']['current_version']
    records = c.execute('SELECT payload FROM ocr_original.export_rows WHERE version_id=%s ORDER BY row_key', (version,)).fetchall()
    output = []
    for record in records:
        r = record['payload']; d = r['data']
        output.append({'key':'export:'+r['key'], 'values':{'of':d['of'], 'component_ref':d['modelo'],
            'quantity':d['qtd'],'length_mm':d['comp_mm'],'production_date':d['sheet_iso_date'],
            'machine':r['machine'],'source':'OCR original — exportação validada',
            'association_status':NOTE,'sheet':None}, 'original':r['raw'],
            'source_export':{'version':version,'line':r['export_line']},'warnings':r['quality_flags']})
    for area in planning.AREAS:
        projection.publish(c,'original:'+area,needs.digest(['http-export-v1',version,area]),output,
            {'source':'OCR original — exportação de todas as áreas','included_in_planning_balances':False,
             'area_unclassified':True,'note':NOTE,'export_version':version})
    return {'rows':len(output),'mode':'validated_export'}
