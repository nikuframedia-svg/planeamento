"""Family labels never merge SKU identities or inflate a planning population."""
from copy import deepcopy
from pathlib import Path
import uuid

import psycopg
from psycopg.rows import dict_row
import pytest

from app import planning, planning_needs as needs
from app.raw import sku_families as families, projection, query, research_sync
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16
from tests.test_planning_needs import vals

ROOT=Path(__file__).resolve().parents[1]
CONFIG={'contract':'test-1','roots':['M1','DLT','DLTN'], 'families':{
    'M1':{'estado':'confirmada_pelo_utilizador'},
    'DLT':{'estado':'forte_padrao_e_varias_of'},
    'DLTN':{'estado':'forte_padrao_e_uma_of'}}}
REFS=['M1ES11000M4DT','M1ES11000M4GT','M10N-705','DLT319','DLTN319','???']


@pytest.fixture()
def family_db(workspace,postgres16):
    with psycopg.connect(postgres16[0]) as c:
        c.execute((ROOT/'sql/044_sku_family_mapping.sql').read_text())
        c.execute('TRUNCATE planning_mtg.sku_family_rules CASCADE')
        c.execute((ROOT/'sql/integration/research_live.sql').read_text())
        c.execute((ROOT/'sql/integration/research_sku_families.sql').read_text())
        c.execute('TRUNCATE origem_v2.aplicacao_versoes,origem_v2.aplicacao_conteudos CASCADE')
    return workspace


def install(c,config=None,refs=None):
    return families.install(c,'cantoneiras',config or CONFIG,[{'sku':s} for s in (refs or REFS)])


def test_boundaries_original_variants_and_unknown():
    assert families.classify('M1ES11000M4DT',CONFIG)['family']=='M1'
    assert families.classify('M10N-705',CONFIG)['family']!='M1'
    assert families.classify('DLTN319',CONFIG)['family']=='DLTN'
    assert families.classify('DLT319',CONFIG)['family']=='DLT'
    assert families.classify('???',CONFIG)=={'family':None,'status':'sem_familia','rule':'sem_padrao'}


def test_complete_analysis_reproduces_every_sku():
    config,rows=families.load_analysis(ROOT/'docs/familias-sku-mtg3-2026-10-01')
    assert len(rows)==31413 and len(config['roots'])==35
    result=[families.classify(row['sku'],config) for row in rows]
    assert sum(r['family']=='M1' for r in result)==181
    assert sum(r['family']=='H92' for r in result)==1225
    assert sum(r['family'] is None for r in result)==141


def test_explicit_m2_confirmation_preserves_other_families():
    config,rows=families.load_analysis(ROOT/'docs/familias-sku-mtg3-2026-10-01')
    import json
    confirmed=json.loads((ROOT/'docs/familias-sku-mtg3-2026-10-01/ontologia/m2-confirmacao.json').read_text())
    updated=families.with_confirmation(config,confirmed)
    changed=[r['sku'] for r in rows if families.classify(r['sku'],config)!=families.classify(r['sku'],updated)]
    assert len(changed)==395 and set(changed)==set(confirmed['skus'])
    assert families.classify('M204-209',updated)['family']=='M2'
    assert families.classify('M2011',updated)['family']!='M2'
    assert families.classify('M204-NEW',updated)['family']!='M2'
    assert families.classify('M2ES999',updated)['status']=='candidata_por_confirmar'
    assert families.classify('M1ES11000M4DT',updated)['family']=='M1'
    assert sum(families.classify(r['sku'],updated)['family'] is None for r in rows)==141


def test_confirmation_history_retains_original_evidence(family_db):
    refs=['M204-209','M2011']
    with planning.connect() as c:
        families.install(c,'cantoneiras',CONFIG,[{'sku':s,'initial_evidence':'original'} for s in refs])
        config=families.with_confirmation(CONFIG,{'family':'M2','skus':['M204-209'],'source':'user'})
        result=families.install(c,'cantoneiras',config,[{'sku':s} for s in refs])
        assert result['changed']==2
        assert families.install(c,'cantoneiras',config,[{'sku':s} for s in refs])['changed']==0
        history=c.execute("SELECT family,revision,evidence FROM planning_mtg.sku_family_history WHERE sku='M204-209' ORDER BY revision").fetchall()
        assert history[0]['family']=='M' and history[0]['evidence']['initial_evidence']=='original'
        assert history[1]['family']=='M2' and history[1]['evidence']['confirmation']['evidence']['source']=='user'


def test_idempotent_history_and_read_only_projection(family_db):
    with planning.connect() as c:
        assert install(c)['changed']==6
        assert install(c)['changed']==0
        assert families.ensure(c,'cantoneiras',REFS+REFS)['changed']==0
    with planning.connect(readonly=True) as c:
        original=[{'key':'one','values':{'component_ref':REFS[0],'quantity_required':10}},
                  {'key':'two','values':{'component_ref':REFS[1],'quantity_required':20}},
                  {'key':'three','values':{'component_ref':REFS[0],'quantity_required':30}}]
        rows=deepcopy(original);families.annotate(c,'cantoneiras',rows)
        assert len(rows)==3 and [r['key'] for r in rows]==['one','two','three']
        assert sum(r['values']['quantity_required'] for r in rows)==60
        assert all(r['values']['sku_family']=='M1' for r in rows)
        assert [r['values']['component_ref'] for r in rows]==[r['values']['component_ref'] for r in original]
        assert c.execute('SELECT count(*) n FROM planning_mtg.sku_family_history').fetchone()['n']==6
    updated=deepcopy(CONFIG);updated['families']['DLT']['estado']='confirmada_pelo_utilizador'
    with planning.connect() as c:
        install(c,updated)
        assert c.execute("SELECT revision,status FROM planning_mtg.sku_family_mappings WHERE sku='DLT319'").fetchone()=={'revision':2,'status':'confirmada_pelo_utilizador'}
        assert c.execute("SELECT count(*) n FROM planning_mtg.sku_family_history WHERE sku='DLT319'").fetchone()['n']==2


def test_reinstall_keeps_confirmations_and_remaps_discovered_references(family_db):
    confirmed=families.with_confirmation(CONFIG,{'family':'M2','skus':['M204-209'],'source':'user'})
    with planning.connect() as c:
        install(c,confirmed)
        families.ensure(c,'cantoneiras',['DLT999','M204-209'],source='mes_model_ref')
        version=families.token(c,'cantoneiras')
        assert install(c)['changed']==0
        assert families.token(c,'cantoneiras')==version
        changed=deepcopy(CONFIG);changed['families']['DLT']['estado']='confirmada_pelo_utilizador'
        install(c,changed)
        maps=c.execute('SELECT * FROM planning_mtg.sku_family_mappings').fetchall()
        assert {m['rules_id'] for m in maps}=={families.token(c,'cantoneiras')}
        extra=next(m for m in maps if m['sku']=='DLT999')
        assert extra['status']=='confirmada_pelo_utilizador' and extra['evidence']['source']=='mes_model_ref'
        assert next(m for m in maps if m['sku']=='M204-209')['family']=='M2'


def test_refresh_includes_mes_only_and_frozen_references_without_merging(family_db,postgres16):
    from psycopg.types.json import Jsonb
    uid='family-'+str(uuid.uuid4())
    with planning.connect() as c:install(c)
    with psycopg.connect(postgres16[0]) as c:
        for suffix,app in [('', 'kanban-mes'),('-mtg2','kanban-mes-mtg2')]:
            c.execute('''INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,
                operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app)
                VALUES(%s,'2025-01-01','tpl','cantoneiras','Teste','hash','{}','{}','Teste',%s)''',(uid+suffix,app))
        for i,(sheet,ref,extra) in enumerate([
            (uid,'DLT999',{}),(uid,'DLT 999',{}),
            (uid,None,{'plan_identity':{'component_ref':'M1MESONLY'}}),
            (uid+'-mtg2','MTG2ONLY999',{})]):
            c.execute('''INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,
                operator_name,quantity,model_ref,extra,validated_at)
                VALUES(%s,%s,'2025-01-01','cantoneiras','Teste',1,%s,%s,now())''',(sheet,i,ref,Jsonb(extra)))
    families.refresh()
    assert families.refresh()['cantoneiras']['changed']==0
    with planning.connect(readonly=True) as c:
        maps={r['sku']:r for r in c.execute("SELECT * FROM planning_mtg.sku_family_mappings WHERE area='cantoneiras'")}
        assert maps['DLT999']['family']=='DLT' and maps['DLT 999']['family'] is None
        assert maps['M1MESONLY']['family']=='M1'
        assert maps['DLT999']['evidence']['sources']==['mes_model_ref']
        assert 'MTG2ONLY999' not in maps


def test_filters_and_research_join_do_not_duplicate_rows(family_db,postgres16):
    with planning.connect() as c:
        install(c)
        rows=[{'key':str(i),'values':{'of':'OF4200','component_ref':ref,'quantity_required':10},'warnings':[]} for i,ref in enumerate(REFS)]
        families.annotate(c,'cantoneiras',rows)
        projection.publish(c,'planning:cantoneiras','family-test',rows,{})
    found=query.listing({'area':'cantoneiras','population':'all','filters':[{'field':'sku_family','op':'eq','value':'M1'}]})
    assert found['total']==2
    assert len({r['values']['component_ref'] for r in found['rows']})==2
    assert any(f['id']=='sku_family' and not f['editable'] for f in found['columns'])
    with planning.connect(readonly=True) as source, psycopg.connect(postgres16[0],row_factory=dict_row) as dest:
        for name in ('sku_family_rules','sku_family_heads','sku_family_mappings','sku_family_history'):
            research_sync.publish(dest,'application:'+name,research_sync.table(source,'planning_mtg',name),{})
        research_sync.publish(dest,'planning:cantoneiras',[(r['key'],r) for r in rows],{})
        assert dest.execute('SELECT count(*) n FROM consulta_v2.planeamento_com_familias_sku').fetchone()['n']==6
        assert dest.execute("SELECT skus_distintos,linhas_planeamento FROM consulta_v2.resumo_familias_sku WHERE familia_sku='M1'").fetchone()=={'skus_distintos':2,'linhas_planeamento':2}
        assert dest.execute("SELECT count(*) n FROM cadastro_v2.mapeamento_familias_sku WHERE estado='sem_familia'").fetchone()['n']==1


def test_new_manual_sku_is_mapped_in_the_save_transaction(family_db,monkeypatch,postgres16):
    with psycopg.connect(postgres16[0]) as c:c.execute((ROOT/'sql/042_free_registration.sql').read_text())
    monkeypatch.setenv('MES_PLANNING_FREE_ENTRY','1')
    with planning.connect() as c:install(c)
    values={**vals(),'component_ref':'M1ES99999NEW','operation':'112'}
    resolved=needs.resolve({'request_id':str(uuid.uuid4()),'area':'cantoneiras','production_order_no':'OF4200','values':values})
    needs.save({'request_id':str(uuid.uuid4()),'area':'cantoneiras','need_id':resolved['need_id'],
        'expected_revision':resolved['revision'],'values':values})
    with planning.connect(readonly=True) as c:
        assert c.execute("SELECT family FROM planning_mtg.sku_family_mappings WHERE sku='M1ES99999NEW'").fetchone()['family']=='M1'


def test_ontology_preserves_graph_and_distinguishes_production_evidence(family_db,postgres16):
    """No duplicate edges, no MTG2/future/zero leakage, no full-profile certainty."""
    config=families.with_confirmation(CONFIG,{'family':'M2','skus':['M204-209'],'source':'user'})
    with planning.connect() as c:install(c,config,REFS+['M204-209','M2011'])
    with psycopg.connect(postgres16[0],row_factory=dict_row) as c:
        c.execute('''CREATE SCHEMA IF NOT EXISTS producao_v2;
          CREATE TABLE IF NOT EXISTS cadastro_v2.setores(codigo text PRIMARY KEY,designacao text);
          CREATE TABLE IF NOT EXISTS cadastro_v2.artigos(id text PRIMARY KEY,setor text,referencia text);
          CREATE TABLE IF NOT EXISTS cadastro_v2.recursos(codigo text PRIMARY KEY,designacao text);
          CREATE TABLE IF NOT EXISTS cadastro_v2.alias_recursos(nome_origem text,recurso_codigo text);
          CREATE TABLE IF NOT EXISTS producao_v2.ordens(codigo text PRIMARY KEY);
          TRUNCATE cadastro_v2.setores,cadastro_v2.artigos,cadastro_v2.recursos,cadastro_v2.alias_recursos,producao_v2.ordens;
          INSERT INTO cadastro_v2.setores VALUES('MTG3','Cantoneiras');
          INSERT INTO cadastro_v2.artigos VALUES('article1','MTG3','M204-209');
          INSERT INTO cadastro_v2.recursos VALUES('RAPID25','Rapid 25T');
          INSERT INTO cadastro_v2.alias_recursos VALUES('Ficep Rapid 25T','RAPID25');
          INSERT INTO producao_v2.ordens VALUES('OF4200');
          CREATE OR REPLACE VIEW consulta_v2.kg_nos AS
           SELECT 'artigo:'||id id,'artigo'::text tipo,referencia rotulo,'{}'::jsonb atributos FROM cadastro_v2.artigos
           UNION ALL SELECT 'of:'||codigo,'of',codigo,'{}'::jsonb FROM producao_v2.ordens
           UNION ALL SELECT 'recurso:'||codigo,'recurso',designacao,'{}'::jsonb FROM cadastro_v2.recursos;
          CREATE OR REPLACE VIEW consulta_v2.kg_relacoes AS
           SELECT 'original'::text id,'artigo:article1'::text origem,'of:OF4200'::text destino,
            'original_relation'::text relacao,'documental'::text estado,'{}'::jsonb evidencia;''')
    with planning.connect(readonly=True) as source,psycopg.connect(postgres16[0],row_factory=dict_row) as c:
        for name in ('sku_family_rules','sku_family_heads','sku_family_mappings','sku_family_history'):
            research_sync.publish(c,'application:'+name,research_sync.table(source,'planning_mtg',name),{})
        research_sync.publish(c,'mes:validated_sheets',[
            ('s1',{'sheet_uid':'s1','source_app':'kanban-mes'}),
            ('s2',{'sheet_uid':'s2','source_app':'kanban-mes-mtg2'})],{})
        base={'sheet_uid':'s1','sheet_date':'2025-01-01','model_ref':REFS[0],
              'production_order':'4200','machine':'Ficep Rapid 25T','quantity':2}
        records=[{**base,'id':1},{**base,'id':2,'model_ref':None,'full_profile':True,
                    'extra':{'plan_identity':{'component_ref':'M204-209'}}},
                 {**base,'id':3,'sheet_uid':'s2'},{**base,'id':4,'quantity':0},
                 {**base,'id':5,'sheet_date':'2099-01-01'},
                 {**base,'id':6,'model_ref':'M10N-705'},
                 {**base,'id':7,'quantity':'NaN'},
                 {**base,'id':8,'extra':{'plan_identity':{'component_ref':'M204-209'}}},
                 {**base,'id':9,'sheet_date':None},
                 {**base,'id':10,'model_ref':'???','production_order':'9999'}]
        research_sync.publish(c,'mes:production_records',[(str(r['id']),r) for r in records],{})
        excel={'pavilion':'MTG3','production_order_no':'OF4200','component_ref':REFS[0],
               'quantity_made':10,'cutting_machine':'Ficep Rapid 25T'}
        planned=[{**excel,'source_line_id':'e1'}, {**excel,'source_line_id':'e2','component_ref':'M204-209','quantity_made':None},
                 {**excel,'source_line_id':'e3','component_ref':'M2011','pavilion':'1'},
                 {**excel,'source_line_id':'e4','component_ref':'???'}, {**excel,'source_line_id':'e5'}]
        research_sync.publish(c,'excel:cantoneiras',[(r['source_line_id'],r) for r in planned],{})
        manual={'id':'manual1','area':'cantoneiras','component_ref':REFS[0],
                'production_order_no':'OFnew','record_status':'draft','revision':1,
                'values_json':{'machine':'Ficep Rapid 25T','quantity_made':999},
                'input_values':{'quantity_required':'texto livre'}}
        research_sync.publish(c,'application:records',[
            ('manual1',manual),('blank-of',{**manual,'id':'blank-of','production_order_no':' OF '})],{})
        sql=(ROOT/'sql/integration/research_sku_ontology.sql').read_text()
        c.execute(sql)
        first=c.execute('SELECT count(*) n FROM consulta_v2.kg_relacoes').fetchone()['n']
        c.execute(sql)
        assert c.execute('SELECT count(*) n FROM consulta_v2.kg_relacoes').fetchone()['n']==first
        assert c.execute("SELECT count(*) n FROM consulta_v2.kg_relacoes WHERE id='original'").fetchone()['n']==1
        m2=c.execute("SELECT * FROM consulta_v2.kg_familias_resumo WHERE familia='M2'").fetchone()
        assert m2['skus_catalogados']==1 and m2['registos_mes']==0 and m2['associacoes_indiretas_mes']==1
        assert m2['skus_com_acumulado_excel']==0 and m2['skus_planeados_mtg3']==1
        assert m2['estado_evidencia_producao']=='associacao_indireta_por_confirmar'
        m1=c.execute("SELECT * FROM consulta_v2.kg_familias_resumo WHERE familia='M1'").fetchone()
        assert m1['registos_mes']==1 and m1['skus_com_acumulado_excel']==1
        assert m1['registos_manuais']==2
        coverage={r['id']:r['estado_cobertura'] for r in c.execute('SELECT * FROM consulta_v2.kg_familias_cobertura')}
        assert len(coverage)==len(records)-1+len(planned)+2
        assert coverage['kgf:evidencia:mes:4']=='quantidade_nao_positiva'
        assert coverage['kgf:evidencia:mes:5']=='data_futura'
        assert coverage['kgf:evidencia:mes:8']=='conflito_referencia_associada'
        assert coverage['kgf:evidencia:mes:9']=='sem_data'
        assert coverage['kgf:evidencia:mes:10']=='integrada_sem_familia'
        assert coverage['kgf:evidencia:excel:e3']=='pavilhao_nao_mtg3'
        assert c.execute("SELECT count(*) n FROM consulta_v2.kg_familias_evidencias WHERE sku='M2011'").fetchone()['n']==0
        nodes=[r['id'] for r in c.execute('SELECT id FROM consulta_v2.kg_nos')]
        edges=c.execute('SELECT id,origem,destino FROM consulta_v2.kg_relacoes').fetchall()
        assert len(nodes)==len(set(nodes))
        assert len(edges)==len({e['id'] for e in edges})
        assert all(e['origem'] in nodes and e['destino'] in nodes for e in edges)
        assert 'kgf:referencia_of:OFNEW' in nodes and 'of:OF9999' in nodes and 'of:OF' not in nodes
        assert 'of:OFNEW' not in nodes
        assert any(e['id']=='kgf:evidencia_of:kgf:evidencia:manual:manual1' and e['destino']=='kgf:referencia_of:OFNEW' for e in edges)
        assert c.execute("SELECT tipo FROM consulta_v2.kg_nos WHERE id='kgf:referencia_of:OFNEW'").fetchone()['tipo']=='referencia_of_por_confirmar'
        assert c.execute("SELECT tipo_evidencia FROM consulta_v2.kg_evidencias WHERE relacao_id='kgf:membro:cantoneiras:M204-209'").fetchone()['tipo_evidencia']=='human_judgement'
        # A RAW/manual edit replaces current evidence and keeps one source ID.
        manual.update(component_ref='M204-209',revision=2)
        research_sync.publish(c,'application:records',[('manual1',manual)],{})
        rows=c.execute("SELECT * FROM consulta_v2.kg_familias_evidencias WHERE tipo='planeamento_manual'").fetchall()
        assert len(rows)==1 and rows[0]['familia']=='M2' and rows[0]['evidencia']['revisao']==2
        assert rows[0]['evidencia']['valores_introduzidos']['quantity_required']=='texto livre'
        assert c.execute("SELECT registos_mes FROM consulta_v2.kg_familias_resumo WHERE familia='M2'").fetchone()['registos_mes']==0
