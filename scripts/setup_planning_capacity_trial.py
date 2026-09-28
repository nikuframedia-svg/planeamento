"""Explicitly synthetic C05 machine/week scenario, restricted to the full clone."""
import os,json,uuid,time
from pathlib import Path
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import objects,edits,query,capacity_revision
with planning.connect(readonly=True) as c:assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'

def save(kind,name,definition):
    with planning.connect(readonly=True) as c:
        prior=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE kind=%s AND name=%s AND NOT archived',(kind,name)).fetchone()
    if prior:return {'id':str(prior['id']),'revision':prior['revision'],'definition':prior['definition']}
    return objects.save({'request_id':str(uuid.uuid4()),'name':name,'definition':definition},kind)

fixtures=json.loads((folder/'c03-browser.json').read_text());report={'synthetic':True,'areas':[]}
for fixture in fixtures:
    area=fixture['area'];op='corte' if area=='perfis' else '112'
    machines=['Serrote Doall Pav.1','Serrote MEBA IS381 Pav 3'] if area=='perfis' else ['Ficep Rapid 20T','Peddi 6']
    item={'area':area,'need_id':fixture['id'],'machines':machines,'resources':[],'operation':op,'rate':10 if area=='perfis' else 20}
    for index,machine in enumerate(machines):
        name='C05 Ensaio '+area+' '+str(index+1)
        res=save('resource',name,{'aliases':[{'area':area,'name':machine}],'operations':[op],'confirmed':True})
        rate=save('rate',name+' taxa',{'resource_id':res['id'],'area':area,'operation':op,'method':'units_hour','value':item['rate'],'valid_from':'2026-01-01','confirmed':True})
        calendars=[save('calendar',name+' W'+str(week),{'resource_id':res['id'],'year':2027,'week':week,
            'shifts':2,'hours_per_shift':7.5,'exception_hours':1,'confirmed':True}) for week in [1,2]]
        item['resources'].append({'resource':res,'rate':rate,'calendars':calendars})
    before=query.listing({'area':area,'selected':[fixture['id']]});row=before['rows'][0]
    item['initial']=edits.update_batch({'request_id':str(uuid.uuid4()),'area':area,'version':before['version'],
        'edits':[{'key':row['key'],'expected_revision':row['revision'],'values':{
            'quantity_required':20,'machine':machines[0],'expected_date':'2027-01-04'}}]})
    report['areas'].append(item)
start=time.monotonic();capacity_revision.rebuild();report['initial_capacity_seconds']=time.monotonic()-start
for item in report['areas']:
    row=query.listing({'area':item['area'],'selected':[item['need_id']]})['rows'][0]
    expected=20/item['rate'];assert row['values']['theoretical_hours']==expected
    assert abs(row['values']['hours_pct']-100*expected/14)<1e-8
    item['initial_row']=row
(folder/'c05-capacity-live-fixtures.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print('Synthetic trial initialized in clone; capacities',report['initial_capacity_seconds'])
