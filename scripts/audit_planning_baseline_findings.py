"""C00.3: connect each diagnosed problem to its original and current evidence."""
import hashlib,json,urllib.request
from datetime import datetime,timezone
from pathlib import Path

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
BASE='http://127.0.0.1:18113'
def read(name):return json.loads((FOLDER/name).read_text())
def proof(name):
 p=FOLDER/name;assert p.is_file(),name
 return {'artifact':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def get(path):
 with urllib.request.urlopen(BASE+path,timeout=60) as r:
  assert r.status==200
  return json.load(r)

baseline=read('baseline-browser.json')
assert baseline['manual']=={'requiresSearch':True,'formHidden':True}
assert all(v['draggables']==0 for v in baseline['areas'].values())
assert baseline['areas']['perfis']['arrow']['before'] is not None and baseline['areas']['perfis']['arrow']['after'] is None
assert read('c03-complete-results-final.json')['result']=='passed'
assert read('c03-complete-zero-fixed.json')['result']=='passed'
assert read('c06-final-state.json')['raw_identities']==83156
assert read('c08-real-zoom-final-state.json')['calibri_verified'] is False
sources=get('/planeamento/api/fontes')
(FOLDER/'c00-current-source-diagnostics.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2)+'\n')
raw=get('/planeamento/api/raw/linhas?area=perfis&population=all&q=OF264774&page_size=500')
expected={'macro:mtg2_bf1cd6a25986791e:plan:5588':{'cut':840,'remaining':0,'boc_remaining':0},
          'macro:mtg2_bf1cd6a25986791e:plan:5589':{'cut':840,'boc':765,'remaining':0,'boc_remaining':75},
          'macro:mtg2_bf1cd6a25986791e:plan:5590':{'cut':840,'boc':668,'remaining':0,'boc_remaining':172}}
observed={r['key']:{field:r['values'].get(field) for field in expected[r['key']]} for r in raw['rows'] if r['key'] in expected}
assert observed==expected
v01={'generation':raw['version'],'expected_from_verified_central_events':expected,'observed_api':observed,
     'source_evidence':proof('c02-selected-ocr-final.json'),'browser_evidence':proof('c02-abocardar-browser.json')}
(FOLDER/'c00-current-v01.json').write_text(json.dumps(v01,ensure_ascii=False,indent=2)+'\n')
findings=[
 {'problem':'Registo exigia OF existente','baseline':proof('baseline-browser.json'),'observed_before':baseline['manual'],
  'current':'Criação OF/OV inexistentes e duas peças em cada área, sem seleção prévia; C03 aprovado.',
  'evidence':[proof(n) for n in ('c03-complete-zero-fixed.json','c03-complete-results-final.json','c03-complete-persistence.json')]},
 {'problem':'Fechos não excluídos coerentemente','baseline':proof('c06-legacy-before.log'),
  'current':'C06 aprovado; ativos/histórico/todos e preservação de identidades nas duas áreas, dossiês e RAW antiga.',
  'evidence':[proof(n) for n in ('c06-final-method.md','c06-final-browser.json','c06-final-transitions.log','c06-dossiers-current-population.json')]},
 {'problem':'Painel Colunas perdia abertura/foco e não tinha arrasto','baseline':proof('baseline-browser.json'),
  'observed_before':{a:{'arrow':v['arrow'],'draggables':v['draggables']} for a,v in baseline['areas'].items()},
  'current':'C07 aprovado; arrasto nativo, setas, foco, grupos e persistência verificados.',
  'evidence':[proof(n) for n in ('c07-complete-focus-fixed.json','c07-complete-persistence.json')]},
 {'problem':'Scroll horizontal e Calibri','baseline':proof('baseline-browser.json'),
  'current':'Acesso às colunas e zoom200% corrigidos; fonte Calibri real continua ausente, C08 incompleto.',
  'evidence':[proof(n) for n in ('c08-real-zoom-final.json','c08-real-zoom-final-state.json')]},
 {'problem':'Saldo incorreto OF264774','baseline':proof('v01-projection-first.json'),
  'current':'Três identidades distintas mantêm corte840; abocardar765/668 e saldos75/172 quando aplicável; API corrente conferida.',
  'evidence':[proof('c00-current-v01.json'),proof('c02-abocardar-browser.json')]},
 {'problem':'OCR Cantoneiras e original incompletos','baseline':proof('baseline-data.json'),
  'current':{'central_clone':sources['ocr'],'original_clone':sources['ocr_original'],
             'limit':'Contagens centrais não provam reconciliação integral com as fontes originais. OCR Windows, ingestão contínua e matriz completa C01/C02 continuam por validar.'},
  'evidence':[proof('c00-current-source-diagnostics.json'),proof('c02-selected-ocr-final.json')]},
]
report={'at':datetime.now(timezone.utc).isoformat(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'environment':BASE+' isolated clone; prior evidence retains original environments and revisions',
 'criterion':'C00.3','findings':findings,'result':'diagnosis_and_current_regressions_documented',
 'boundary':'C00 diagnostic completion does not approve real ingestion, missing Calibri, full calculation matrix or publication.'}
(FOLDER/'c00-baseline-findings.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Six diagnostic groups linked to baseline and current evidence; V01 API checked in generation',raw['version'])
