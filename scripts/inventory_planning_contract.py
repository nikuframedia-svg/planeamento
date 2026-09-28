"""C00 traceability of current fields and all 43 acceptance formulas.

Every external origin is pinned to the workbook inventory and cell ledger.
Metadata coverage is not a claim that every browser/source gate has passed.
"""
from __future__ import annotations
from datetime import datetime,timezone
import argparse
import hashlib,json,os,re
from pathlib import Path

ROOT=Path('docs/validacao-planeamento-integral/20260923-execucao')
# ID; fields; authoritative anchors; inputs; unit; independent acceptance example.
RULES='''F01|description|Layout:Folha1:L2;Perfis:Planeamento:J7|material_type,profile,dimensions,length_mm,angle_deg,grade|texto|Varão redondo, Ø20, L1200, S355JR: descrição contém estes quatro factos e não inventa espessura
F02|cut,ocr_cut|Layout:Folha1:P2;Perfis:Planeamento:V7|eventos únicos de corte validados e associados; acumulado Excel|un.|396 + 444 = 840; repetir o evento396 mantém840
F03|boc,ocr_boc|Layout:Folha1:Q17;Perfis:Planeamento:W144|eventos únicos de abocardar; acumulado Excel|un.|298 abocardadas permanece298 quando o corte é315
F04|cut_pct|Layout:Folha1:R2|Q,C|%|C315/Q500 = 63
F05|boc_pct|Layout:Folha1:S17|Q,B,abocardar|%|B298/Q500 com abocardarSim = 59.6
F06|final_pct|Layout:Folha1:T7|cut_pct,boc_pct,abocardar|%|C315,B298,Q500: Sim59.6; Não63; desconhecido indisponível
F07|remaining,production_excess|Layout:Folha1:U7;Perfis:Planeamento:AS7|Q,C|un.|Q500,C315 = 185; Q5,C7 = 0 com excesso2
F08|boc_remaining|Layout:Folha1:V7|Q,B,abocardar|un.|Q500,B298,Sim = 202; Não = 0
F09|section_unit|Perfis:Planeamento:AX7;Perfis:AreaSecaoCorte:B3:C700;VBA:FuncAreaPerf.bas|família,perfil,d,w,h,t|mm²|VarãoØ20 = 314.1592653589793; tuboØ76.1,e3.25 = 743.8113306455535
F10|section_total,section_pending|Layout:Folha1:AF2;Perfis:Planeamento:AP7:AY7|A,Q,saldo_corte|mm²|314.1592653589793 × 48 = 15079.644737231007 total; saldo20 = 6283.185307179586 pendente
F11|quantity_to_plan|Layout:Folha1:AI2;Perfis:Planeamento:AS7|Q,P da operação|un.|Q100,P40 = 60; local novoQ100 sem produção = 100
F12|hours_pct|Layout:Folha1:AJ2;Perfis:Planeamento:AU7;Perfis:PlanDisponibilidadeSemanal:I2:K2|máquina,anoISO,semanaISO,carga de todas as operações,disponibilidade|%|(2h + 8h) / 14h = 71.42857142857143 em ambas as linhas
F13|expected_week,expected_year|Layout:Folha1:AK2;Perfis:Planeamento:AV7:AW7|data prevista ou semana/ano manual coerente|semanaISO|2027-01-01 = 2026-W53
F14|weight_unit|Perfis:Planeamento:DB7:DC7;VBA:FuncAreaPerf.bas|A,L,densidade comprovada|kg|A1000mm²,L2000mm,aço7850 = 15.7
F15|weight|Layout:Folha1:AL2;Perfis:Planeamento:DB7|peso unitário,saldo principal|kg|15.7kg × 60 = 942
F16|total_length,total_m|Layout:Folha1:AN2;Perfis:Planeamento:BR7|Q,L|mm e m|48 × 1200 = 57600mm = 57.6m
F17|stock_length_mm|Layout:Folha1:AO2;Perfis:Planeamento:BS7|L,substituição manual comprovada|mm|L6000 sugere6000; L6001 sugere12000; manual9000 prevalece
F18|bars|Layout:Folha1:AP2;Perfis:Planeamento:BT7|saldo,S,L|un.|saldo5,S6000,L2500 = ceil(5/floor(6000/2500)) = 3
F19|remaining_m|Perfis:Planeamento:AS7;Perfis:Planeamento:AM7|saldo,L|m|saldo60,L2000 = 120
F20|theoretical_hours|Perfis:Planeamento:AY7:AZ7;Perfis:CapacidadeMáquinas:C2|volume pendente,taxa compatível,preparação explícita|h|30000mm² / 10000mm²/h = 3h; ThomasExcelQ51 usa fator3, taxa manual não
F21|deadline_status,overdue|Layout:Folha1:AH2;Perfis:Planeamento:AR11|data prevista/entrega,dia local,saldos de operações|estado|data ontem com saldo1 = prazo ultrapassado; saldo desconhecido não é conclusão
G01|made,ocr_quantity,ocr_op_*|Cantoneiras:Plan_ produção:AA7;Cantoneiras:Dados:H3:I3|eventos únicos validados por operação; acumulado próprio Excel|un.|op119=40,op209=15: principal40, nunca55
G02|made_pct|Cantoneiras:Plan_ produção:O7:AA7|Q,Pprincipal|%|40/100 × 100 = 40
G03|remaining,secondary_remaining,production_excess|Cantoneiras:Plan_ produção:AG7;Cantoneiras:Plan_ produção:S7:T7|Q,P de cada operação|un.|Q100,principal40,secundária15 = 60 e85
G04|total_length,total_m|Cantoneiras:Plan_ produção:AM7|Q,L|mm e m|Q100,L2000 = 200000mm = 200m
G05|remaining_m|Cantoneiras:Plan_ produção:BK7|saldo,L|m|60 × 2000 / 1000 = 120
G06|speed_m_h,rate_source,applied_rate_value,applied_rate_unit|Cantoneiras:Plan_ produção:AL7|taxa manual vigente,histórico compatível,Excel|m/h ou método explícito|manual30m/h prevalece sobre histórico26.6666667 eExcel80
G07|theoretical_hours|Cantoneiras:Plan_ produção:AO7|metros pendentes,taxa m/h|h|120m / 30m/h = 4h
G08|weight_unit|Cantoneiras:Plan_ produção:AP7;Cantoneiras:Tabela pesos:B3:C462|designação exata,kg/m,L|kg|catálogo de ensaio3kg/m,L2000 = 6kg; realL45X45X4 usa célula comprovada
G09|weight|Cantoneiras:Plan_ produção:AS7|peso unitário,saldo principal|kg|6kg × 60 = 360kg, sem multiplicar por operações
G10|quantity_to_plan|Cantoneiras:Plan_ produção:AG7|saldo da operação planeada|un.|Q100,P40 = 60
G11|expected_week,expected_year,imported_week|Cantoneiras:Plan_ produção:B7|data ou semana/ano comprovados|semanaISO|2027-01-01 = 2026-W53; W39 sem ano fica por calendarizar
G12|description,material_description,deadline_status,overdue|Cantoneiras:Plan_ produção:P7;Cantoneiras:Plan_ produção:L7|descrição original,entradas locais,data pertinente,saldos|texto e estado|preservar L45X45X4 S355J0 EN10025; saldo desconhecido não fecha a peça
H01|available_hours|Perfis:PlanDisponibilidadeSemanal:F2:H2;SQL:planning_mtg.raw_objects:definition[kind=calendar]|turnos,horas por turno,indisponibilidade ou calendário de intervalos|h|2 × 7.5 - 1 = 14
H02|planned_hours|Perfis:PlanDisponibilidadeSemanal:I2;Perfis:CapacidadeMáquinas:K2|operações ativas únicas,horas previstas,recurso/período|h|2 + 8 = 10; uma operação fechada de5h não entra
H03|actual_hours|SQL:planning_mtg.raw_objects:definition.hours[kind=worked_hours];SQL:mes_kanban.production_records:hours_worked;SQL:mes_kanban.validated_sheets:sheet_uid|declarações únicas por folha/período,revisões,sobreposição resolvida|h|folha5h com10peças conta5h, nunca50h
H04|free_hours|Perfis:PlanDisponibilidadeSemanal:J2|H01,H02|h|14 - 10 = 4; 14 - 16 = -2
H05|occupancy|Perfis:PlanDisponibilidadeSemanal:K2|H01,H02|%|10/14 × 100 = 71.42857142857143; 16/14 = 114.28571428571429
H06|equivalent_shifts|Perfis:CapacidadeMáquinas:L2|carga,horas por turno|turnos|10 / 7.5 = 1.3333333333333333 sem arredondar a inteiro
H07|capacity_total|Perfis:PlanDisponibilidadeSemanal:W2|horas disponíveis,taxa por hora compatível|unidade do método|14h × 30m/h = 420m; 2min/un. = 30un./h
H08|capacity_free|Perfis:PlanDisponibilidadeSemanal:L2|horas livres,taxa por hora compatível|unidade do método|4h × 30m/h = 120m; -2h × 30m/h = -60m
H09|historical_rate|SQL:planning_mtg.raw_contents:detail.productivity;SQL:mes_kanban.production_records:quantity;SQL:mes_kanban.production_records:hours_worked|volume e horas da mesma população,máquina,operação,janela,unidade|unidade/h|100m/5h e300m/10h = 400/15 = 26.666666666666668
H10|rate_source,applied_rate_value,applied_rate_unit|Perfis:CapacidadeMáquinas:C2;Cantoneiras:Plan_ produção:AL7;SQL:planning_mtg.raw_objects:definition[kind=rate]|manual vigente,histórico utilizável,Excel válido|unidade/método|manual30 > histórico26.6666667 > Excel80; expirado não prevalece'''

# Direct macro cells. Derived fields below acquire their formula references.
PERFIS=dict(id='A',customer='C',designation='F',ov='D',of='E',cut_date='I',delivery_date='K',picking_week='CG',team='BJ',pavilion='BK',component_ref='L',notes='AT',abocardar='T',quantity_required='AH',material_type='AF',profile='AG',outer_diameter_mm='AI',width_mm='AJ',height_mm='AK',thickness_mm='AL',length_mm='AM',angle_deg='AN',grade='AO',machine='AQ',expected_date='AR',stock_length_mm='BS',chanfro='U',ponteira='AE',material_request_date='CK',material_available_date='CE',material_lot='CF')
CANT=dict(id='A',customer='F',designation='I',ov='G',of='H',cut_date='L',team='AJ',pavilion='AK',component_ref='M',notes='AU',quantity_required='O',material_type='N',profile='Q',length_mm='R',machine='AI',operation='S',operation_detail='T',material_description='P',macro_closed='AH',imported_week='B',chanfro='V')
LOCAL={
 'operation':'Perfis: operação corte ou abocardar da preparação; need_operations.code. Cantoneiras: catálogo de códigos Dados H:I',
 'operation_detail':'Perfis: preparação adicional explicitamente declarada; records.values_json. Cantoneiras: código da segunda operação,0 significa ausência',
 'hours_pct':'Ocupação agregada máquina/semana/ano nas duas áreas; regraF12, nunca contribuição individual',
 'identity_discriminator':'Desempate humano de identidade; needs.specification; sem célula Excel equivalente',
 'custom_profile':'Modo de perfil manual; needs.specification; sem célula Excel equivalente',
 'special_profile':'Designação especial declarada; needs.specification; sem célula Excel equivalente',
 'geometry':'Geometria explicitamente declarada; needs.specification; sem célula Excel equivalente',
 'material_requested':'Estado trivalente manual; Layout Folha1 AM; needs.specification',
 'planned_week':'Semana manual com ano obrigatório; needs.specification; validação ISO',
 'planned_year':'Ano ISO manual com semana obrigatória; needs.specification',
 'picking_year':'Ano manual da semana de picking; needs.specification; não inventar ano de CG/B',
 'finish_week':'Semana manual de conclusão prevista; records.values_json',
 'finish_year':'Ano ISO manual de conclusão prevista; records.values_json',
 'weekly_capacity_hours':'Preparação local legada; disponibilidade aplicada deriva do calendário auditado',
 'other_operations':'Texto de preparação preservado; needs.specification/records.values_json',
 'status':'Estado administrativo CPIS: cpis_mtg.orders ou raw_mtg.cpis_rows; readonly',
 'preparation_status':'planning_mtg.records.record_status; rascunho/preparada',
 'last_activity':'Máxima data validada dos eventos da OF; mes_kanban.production_records',
 'unassigned_records':'Eventos únicos da OF sem associação resolvida; mes_kanban.production_records e decisões humanas',
 'execution_status':'Estado derivado da cobertura de produção; não altera estado administrativo CPIS',
 'planning_active':'CPIS não fechado e linha macro não fechada; planning_population-v1',
 'closure_reason':'Proveniência CPIS/macro dos fechos; não usar percentagem de produção',
 'delivery_date':'Contexto CPIS ou data manual de ordem local identificada; planning_mtg.local_orders',
 'picking_week':'Semana declarada na preparação; requires picking_year quando manual',
 'stock_length_mm':'Substituição manual/importada identificada ou sugestãoF17',
 'outer_diameter_mm':'Dimensão técnica local; needs.specification; unidade mm',
 'width_mm':'Dimensão técnica local; needs.specification; unidade mm',
 'height_mm':'Dimensão técnica local; needs.specification; unidade mm',
 'thickness_mm':'Dimensão técnica local; needs.specification; unidade mm',
 'angle_deg':'Ângulo técnico local; needs.specification; graus',
 'grade':'Qualidade importada da descrição ou manual; needs.specification',
 'expected_date':'Data manual prevista da preparação; needs.specification',
 'abocardar':'Operação aplicável a Perfis; não criar implicitamente em Cantoneiras',
 'ponteira':'Preparação local em Cantoneiras; needs.specification',
 'material_request_date':'Data manual de requisição; needs.specification',
 'material_available_date':'Data manual de disponibilidade; needs.specification',
 'material_lot':'Lote manual; needs.specification'}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--population-proof',default='c04-formula-population-first.json');parser.add_argument('--output',default='c00-contract-origin-inventory.json');options=parser.parse_args()
 assert Path(options.output).name==options.output and options.output.endswith('.json')
 os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
 from app import planning_catalogs
 from app.raw import contracts
 books=json.loads((ROOT/'workbook-inventory.json').read_text());baseline=json.loads((ROOT/'field-formula-inventory.json').read_text())
 for book in books:assert hashlib.sha256(Path(book['file']).read_bytes()).hexdigest()==book['sha256']
 rules=[];by_field={}
 for line in RULES.splitlines():
  rid,fields,origins,inputs,unit,expected=line.split('|');item={'id':rid,'fields':fields.split(','),'origins':origins.split(';'),'inputs':inputs,'unit':unit,'expected_example':expected,'population_validation':None}
  for area in (['perfis','cantoneiras'] if rid=='F12' else ['perfis'] if rid.startswith('F') else ['cantoneiras'] if rid.startswith('G') else ['perfis','cantoneiras']):
   for field in item['fields']:by_field.setdefault((area,field),[]).append(rid)
  rules.append(item)
 assert len(rules)==43 and len({r['id'] for r in rules})==43
 audit=json.loads((ROOT/options.population_proof).read_text())
 for rule in rules:
  coverage={area:d['by_rule'][rule['id']] for area,d in audit['areas'].items() if rule['id'] in d['by_rule']}
  if coverage:rule['population_validation']={'artifact':options.population_proof,'coverage':coverage,'boundary':audit['boundary']}
 out={'at':datetime.now(timezone.utc).isoformat(),'scope':'Current RAW schema and form catalog contracts; all43 formula origins and independent expected examples. Does not assert actual rendered form parity or complete formula validation.','source_manifest':'workbook-inventory.json','sources':[{'file':b['file'],'sha256':b['sha256'],'names':b['names'],'validations':{s:x['validations'] for s,x in b['sheets'].items() if x['validations']}} for b in books],'formulas':rules,'fields':{},'missing_origins':[],'profile_families':baseline['profile_families']}
 for area,columns in [('perfis',PERFIS),('cantoneiras',CANT)]:
  fields=contracts.fields(area);catalog=planning_catalogs.catalog(area);form={f['id']:f for f in catalog['fields']};raw={f['id']:f for f in fields};entries=[]
  for fid in sorted(raw.keys()|form.keys()):
   origins=[]
   if fid in columns:origins.append({'kind':'macro_cell','file':'Met2_Plan_Perfis.xlsm' if area=='perfis' else 'Met3_Plan_Cantoneiras.xlsm','sheet':'Planeamento' if area=='perfis' else 'Plan_ produção','header_cell':columns[fid]+'6','data_column':columns[fid]})
   if fid in LOCAL:origins.append({'kind':'local_or_source_contract','definition':LOCAL[fid]})
   formula_ids=by_field.get((area,fid),[])
   if fid.startswith('ocr_op_'):formula_ids=['G01']
   if formula_ids:origins.append({'kind':'derived','formula_ids':formula_ids})
   if not origins:out['missing_origins'].append({'area':area,'field':fid})
   entries.append({'id':fid,'raw':raw.get(fid),'form_catalog':form.get(fid),'origins':origins,'raw_editable_without_form':bool(raw.get(fid,{}).get('editable') and fid not in form)})
  out['fields'][area]={'raw_count':len(raw),'form_catalog_count':len(form),'fields':entries,'raw_editable_without_form':[r['id'] for r in entries if r['raw_editable_without_form']],'catalog_version':catalog['version'],'level1_source':catalog['level1_source'],'catalog_validations':catalog['validations']}
 out['formula_population_covered']=sum(bool(r['population_validation']) for r in rules)
 out['result']='inventory_complete_in_stated_scope' if not out['missing_origins'] and not any(v['raw_editable_without_form'] for v in out['fields'].values()) else 'inventory_gaps'
 (ROOT/options.output).write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n')
 print({a:{k:v for k,v in d.items() if k in ['raw_count','form_catalog_count','raw_editable_without_form']} for a,d in out['fields'].items()});print('Missing origins',out['missing_origins']);print('Formula origins',len(rules),'population-audited',out['formula_population_covered'])
 if out['result']=='inventory_gaps':raise SystemExit(1)

if __name__=='__main__':main()
