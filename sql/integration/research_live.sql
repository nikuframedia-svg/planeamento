-- Apply only to the separate research database. Existing v2 loads remain
-- reproducible archives; live consumers use the explicitly named *_atual views.
CREATE SCHEMA IF NOT EXISTS origem_v2;
CREATE SCHEMA IF NOT EXISTS consulta_v2;
CREATE TABLE IF NOT EXISTS origem_v2.aplicacao_versoes (
 id text PRIMARY KEY, conjunto text NOT NULL, linhas integer NOT NULL,
 metadata jsonb NOT NULL, capturada_em timestamptz NOT NULL DEFAULT now(),
 UNIQUE(conjunto,id)
);
CREATE TABLE IF NOT EXISTS origem_v2.aplicacao_conteudos (
 hash text PRIMARY KEY, dados jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS origem_v2.aplicacao_membros (
 versao text NOT NULL REFERENCES origem_v2.aplicacao_versoes(id),
 chave text NOT NULL, conteudo text NOT NULL REFERENCES origem_v2.aplicacao_conteudos(hash),
 PRIMARY KEY(versao,chave)
);
CREATE TABLE IF NOT EXISTS origem_v2.aplicacao_fontes (
 conjunto text PRIMARY KEY, versao text NOT NULL,
 confirmada_em timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(conjunto,versao) REFERENCES origem_v2.aplicacao_versoes(conjunto,id)
);
CREATE TABLE IF NOT EXISTS origem_v2.aplicacao_sincronizacao (
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 ultima_tentativa timestamptz NOT NULL DEFAULT now(),
 ultimo_sucesso timestamptz, erro text
);
CREATE OR REPLACE VIEW consulta_v2.dados_aplicacao_atuais AS
 SELECT f.conjunto,m.chave,c.dados,f.versao,f.confirmada_em,v.metadata
 FROM origem_v2.aplicacao_fontes f JOIN origem_v2.aplicacao_versoes v ON v.id=f.versao
 JOIN origem_v2.aplicacao_membros m ON m.versao=f.versao
 JOIN origem_v2.aplicacao_conteudos c ON c.hash=m.conteudo;
CREATE OR REPLACE VIEW consulta_v2.planeamento_atual AS
 SELECT split_part(conjunto,':',2) area,chave,dados->'values' valores,
        coalesce(dados->'input_values','{}') valores_introduzidos,
        coalesce((dados->>'identity_pending')::boolean,false) identidade_pendente,
        dados->>'need_id' necessidade_id,dados,versao,confirmada_em,metadata
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto LIKE 'planning:%';
CREATE OR REPLACE VIEW consulta_v2.registos_manuais_atuais AS
 SELECT chave,dados,versao,confirmada_em FROM consulta_v2.dados_aplicacao_atuais
 WHERE conjunto='application:records';
CREATE OR REPLACE VIEW consulta_v2.historico_registos_manuais AS
 SELECT chave,dados,versao,confirmada_em FROM consulta_v2.dados_aplicacao_atuais
 WHERE conjunto IN ('application:record_versions','application:need_events','application:local_order_history');
CREATE OR REPLACE VIEW consulta_v2.producao_mes_atual AS
 SELECT chave,dados,versao,confirmada_em FROM consulta_v2.dados_aplicacao_atuais
 WHERE conjunto='mes:production_records';
CREATE OR REPLACE VIEW consulta_v2.ocr_original_atual AS
 SELECT conjunto,chave,dados,versao,confirmada_em FROM consulta_v2.dados_aplicacao_atuais
 WHERE conjunto IN ('ocr:validated_export','ocr:native_sheets');
COMMENT ON VIEW consulta_v2.planeamento_atual IS 'Uma linha por identidade do planeamento; Excel/CPIS são evidências, nunca parcelas somadas. Valores introduzidos conservam texto livre. Identidades pendentes não entram nos totais automáticos.';
COMMENT ON VIEW consulta_v2.ocr_original_atual IS 'Evidência OCR separada de MES. Exportação sem IDs nativos não é somada à produção nem permite afirmar equivalência entre eventos.';
COMMENT ON VIEW consulta_v2.dados_aplicacao_atuais IS 'Publicação atómica da aplicação. Cada conjunto aponta apenas para uma versão; o histórico não aumenta os totais atuais.';
