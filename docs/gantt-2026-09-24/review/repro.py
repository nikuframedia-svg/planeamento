"""Pure in-memory review examples. No connection or write to PostgreSQL."""
import sys, json
from pathlib import Path
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
sys.path.insert(0, '/home/luis/projects/planeamento')
from tests.test_planning_gantt import synthetic, operation, calendar, MONDAY
from app.gantt import baseline, validation, inputs
from app import planning_dates, planning_estimates

results = {}

# A feasible fixed job must reserve its slot before lower-priority free jobs.
snap = synthetic([operation('a',120),operation('b',60)], pins={
    'b':{'resource_id':'meba','start':MONDAY.isoformat()}})
valid = {'states':{'a':'scheduled','b':'scheduled'},'bars':{
    'a':{'resource_id':'meba','duration_minutes':120,'start_minute':60,'end_minute':180,'segments':[(60,180)],'provisional':False,'provisional_reasons':[]},
    'b':{'resource_id':'meba','duration_minutes':60,'start_minute':0,'end_minute':60,'segments':[(0,60)],'provisional':False,'provisional_reasons':[]}}}
try:
    baseline.build(snap)
    error=None
except ValueError as exc:
    error=str(exc)
results['feasible_pin_rejected']={'baseline_error':error,'independent_feasible_schedule':validation.validate(snap,valid)}

# An urgent last operation is still part of the Picking completion of its OF.
cut=operation('cut',60,priority=1)
boc=operation('boc',60,machine='boc',predecessor='cut',priority=0)
cut['deadline']=boc['deadline']=(MONDAY+timedelta(minutes=60)).isoformat()
snap=synthetic([cut,boc],resources=('meba','boc'))
proposal=baseline.build(snap)
results['picking_of_lateness']={'bars':proposal['bars'],'score':proposal['score'],
    'expected_picking_lateness_minutes':60,'actual_picking_lateness_minutes':proposal['score'][3]}

# A downstream operation inherits uncertainty of unfinished predecessor balance.
cut=operation('cut',60);cut['balance_provisional']=cut['provisional']=True
boc=operation('boc',60,machine='boc',predecessor='cut')
snap=synthetic([cut,boc],resources=('meba','boc'))
proposal=baseline.build(snap)
results['provisional_dependency']={'cut_provisional':proposal['bars']['cut']['provisional'],
    'boc_provisional':proposal['bars']['boc']['provisional'],'validation':validation.validate(snap,proposal)}

# The signature excludes required quantity; old Qtd em Falta is not coherent after a quantity edit.
row={'area':'perfis','values':{'quantity_required':200},'original':{'quantity_required':100},
     'raw':{'Qtd em Falta':40},'plan_key':'macro-line',
     'calculation':{'compatible':True,'production_sources':[{'operation':'corte','remaining':None}]}}
results['obsolete_macro_balance_after_quantity_edit']=planning_estimates.select_balance(row,'corte')

# Capture exact published-row fields through a query-only in-memory adapter.
rid='11111111-1111-4111-8111-111111111111'
configs=[{'id':rid,'kind':'resource','name':'M','definition':{'confirmed':True,'operations':['corte'],
          'aliases':[{'area':'perfis','name':'M'}]}},
    {'kind':'calendar','definition':{**calendar(),'resource_id':rid}},
    {'kind':'rate','definition':{'confirmed':True,'resource_id':rid,'area':'perfis','operation':'corte',
       'method':'units_hour','value':10,'valid_from':'2026-01-01'}}]
class Cursor:
    def __init__(self,rows):self.rows=rows
    def fetchall(self):return self.rows
class Conn:
    def __init__(self, values):self.values=values
    def execute(self,sql,args=None):
        if 'raw_objects' in sql:return Cursor(configs)
        return Cursor([{'row_key':'line1','values_json':self.values,
            'detail':{'area':'perfis','calculation':{'compatible':True,'production_sources':[
              {'operation':'corte','remaining':10,'origin':'OCR validado'}]}}}])
def captured(extra):
    values={'of':'OF1','component_ref':'R','machine':'M','quantity_required':10,'abocardar':'-',**extra}
    with patch.object(inputs,'references',return_value={'planning_generation':1,'sources_pending':False}), \
         patch.object(inputs.query,'generation',return_value={}), patch.object(inputs.query,'source',return_value=(' FROM dummy WHERE true',[])):
        return inputs.capture(Conn(values),{'horizon_weeks':12},MONDAY)['operations'][0]

for name,extra in [('manual_week',{'planned_year':2026,'planned_week':43,'cut_date':'2026-09-22'}),
                   ('manual_conflict',{'planned_year':2026,'planned_week':40,'expected_date':'2026-09-22'})]:
    op=captured(extra)
    results[name]={'shared_resolver':planning_dates.period(extra,area='perfis'),
         'gantt_state':op['state'],'gantt_deadline':op['deadline'],
         'gantt_reasons':op['blocking_reasons'],'milestones':op['milestones']}

# Duplicate operation keys must fail before a proposal can be accepted.
snap=synthetic([operation('same',60),operation('same',60)])
try:
    baseline.build(snap)
    duplicate_error=None
except ValueError as exc:
    duplicate_error=str(exc)
results['duplicate_keys']={'input_count':len(snap['operations']),'baseline_error':duplicate_error,
    'validation':validation.validate(snap,{'bars':{},'states':{'same':'overflow'}})}

print(json.dumps(results,ensure_ascii=False,indent=2))
Path(__file__).with_name('fix-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
