"""Read-only fixtures and independent expectations for the real-history browser trial."""
import json,os
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning, planning_needs as needs, planning_population as population
from app.raw import query,productivity

audit=json.loads((folder/'c05-f12-current-audit.json').read_text())
today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
result={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164/18113',
    'today':str(today),'yesterday':str(today-timedelta(days=1)),'areas':[]}
with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    assert c.execute('SELECT current_database() name').fetchone()['name']=='planning_integral'
    for area in planning.AREAS:
        sample=audit['areas'][area]['historical_sample']
        gen=query.generation(c,area);base,args=query.source(gen)
        target=c.execute('SELECT m.row_key,c.values_json'+base+' AND m.row_key=%s',args+[sample['key']]).fetchone()
        v=target['values_json'];machine=v['machine']
        resource=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='resource' AND NOT archived AND definition->'aliases' @> %s::jsonb",
            (json.dumps([{'area':area,'name':machine}]),)).fetchone()
        proof=productivity.evidence(sample['applied_rate']['history_hash'])
        assert len(proof['cohorts'])==1
        cohort=proof['cohorts'][0]
        closed=c.execute('SELECT m.row_key,c.values_json'+base+' AND NOT ('+population.active_sql()+')'+
            " AND c.values_json->>'machine'=%s AND c.values_json->>'operation'=%s AND (c.values_json->>'applied_rate_value')::numeric=%s AND (c.values_json->>'theoretical_hours')::numeric>0 ORDER BY m.row_key LIMIT 1",
            args+[machine,v['operation'],v['applied_rate_value']]).fetchone()
        assert closed,area
        manual=None
        if cohort['hours_origin']=='Manual':
            manual=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s',(cohort['key'].split(':')[1],)).fetchone()
        cg=query.generation(c,area,dataset='capacity_items');cb,ca=query.source(cg)
        reference=c.execute("SELECT c.detail->'reference_rate' rate"+cb+" AND c.detail->>'planning_key'=%s",ca+[sample['key']]).fetchone()['rate']
        day=date.fromisoformat(cohort['start_date']);year,week,_=day.isocalendar()
        result['areas'].append({'area':area,'resource':resource,'active':target,'closed':closed,'cohort':cohort,
            'manual_hours':manual,'history':proof,'excel_rate':reference['value'],'year':year,'week':week,
            'base_rate':cohort['volume']/cohort['hours'],'generation':gen['id']})
path=folder/'c10-dependencies-fixtures.json'
assert not path.exists(),'Keep the original trial fixture; do not overwrite its restore values.'
path.write_text(json.dumps(needs.serial(result),ensure_ascii=False,indent=2)+'\n')
print([(a['area'],a['active']['row_key'],a['closed']['row_key'],a['base_rate'],a['excel_rate']) for a in result['areas']])
