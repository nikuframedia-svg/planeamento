from copy import deepcopy
from app.gantt import source_plan


def test_availability_preserves_conflicts_duplicates_and_published_snapshot():
    class Conn:
        def execute(self, sql, args):
            assert args == ('published-old-snapshot',)
            self.rows = [{'excel_row':n,'row_data':{'values':['',39,2026,machine,'',shifts,hours]}}
                         for n,machine,shifts,hours in [(101,'Vanguard',10,8),
                         (103,'Vanguard',2,16),(104,'MEBA',1,10),(105,'MEBA',1,10)]]
            return self
        def fetchall(self):return self.rows
    gen={'metadata':{'snapshot':{'snapshot_id':'published-old-snapshot','source_filename':'perfis.xlsm'}}}
    rows=source_plan.availability(Conn(),gen,[],{'MEBA':'physical-shared'})
    meba=next(r for r in rows if r['resource_id']=='physical-shared')
    assert meba['hours']==10 and len(meba['evidence'])==2  # duplicates are not summed
    vanguard=next(r for r in rows if r['resource_id']!='physical-shared')
    assert vanguard['hours'] is None and vanguard['alternatives']==[32,80]
    assert vanguard['status']=='conflict'
    confirmed={'id':'cal','revision':2,'kind':'calendar','definition':{
        'resource_id':vanguard['resource_id'],'year':2026,'week':39,'confirmed':True,
        'shifts':3,'hours_per_shift':10}}
    overridden=source_plan.availability(Conn(),gen,[confirmed],{})
    effective=next(r for r in overridden if r['resource_id']==vanguard['resource_id'])
    assert effective['hours']==30 and len(effective['imported_evidence'])==2
    assert all(r['week']==39 for r in rows)  # never extrapolate into future weeks


def op(key, **changes):
    return {'key':key,'state':'blocked','planning_remaining':20,'source_resource_id':'M',
        'milestones':{'operation_forecast':'2026-09-22','period_origin':'Data Corte'},
        'source_duration':{'hours':2,'quantity':20,'origin':'Macro'},'provisional':True,
        'blocking_reasons':['Calendário horário por confirmar.'], **changes}


def test_forecast_covers_all_operations_excludes_complete_and_never_invents_hours():
    operations=[op(str(n)) for n in range(601)]
    operations.extend([op('complete',state='complete',planning_remaining=0),
        op('no-machine',source_resource_id=None),op('no-date',milestones={}),
        op('wrong-quantity',source_duration={'hours':2,'quantity':100,'origin':'Macro'})])
    snapshot={'operations':operations,'weekly_availability':[]}
    before=deepcopy(snapshot);result=source_plan.build(snapshot)
    assert snapshot==before
    assert len(result['entries'])==602 and len(result['pending'])==2 and result['completed']==1
    assert {e['key'] for e in result['entries']}|{e['key'] for e in result['pending']}|{'complete'}=={o['key'] for o in operations}
    entry=result['entries'][0]
    assert entry['start_date']=='2026-09-22' and entry['end_date_exclusive']=='2026-09-23'
    assert entry['precision']=='day' and 'start' not in entry  # not a clock-time bar
    load=result['weekly_load'][0]
    assert load['hours']==1202 and load['unknown_durations']==1 and load['availability'] is None
    assert next(e for e in result['entries'] if e['key']=='wrong-quantity')['hours'] is None


def test_manual_week_overrides_date_but_conflicts_and_abocardar_stay_pending():
    result=source_plan.build({'weekly_availability':[], 'operations':[
        op('manual',milestones={'operation_forecast':'2026-09-22','period_origin':'Decisão local',
                               'period_year':2026,'period_week':43}),
        op('conflict',blocking_reasons=['Data prevista e semana escolhida não coincidem.']),
        op('boc',milestones={'cut_date':'2026-09-22','operation_forecast':None})]})
    assert len(result['entries'])==1
    assert result['entries'][0]['start_date']=='2026-10-19'
    assert result['entries'][0]['precision']=='week'
    assert {p['key'] for p in result['pending']}=={'conflict','boc'}
