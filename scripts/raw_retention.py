"""Retenção do histórico RAW do planeamento (06/10/2026).

Cada publicação RAW cria uma geração (planning_mtg.raw_generations). Um membro
(raw_members) pertence às gerações first_generation <= g < last_generation
(NULL = atual) e aponta para um conteúdo imutável (raw_contents). Desde 22/09
ficaram guardadas todas as gerações; este script apaga o histórico que já
ninguém consegue ler.

Regras de retenção (gerações mantidas):
  1. a geração atual e a anterior de cada dataset;
  2. todas as gerações criadas nos últimos N dias (defeito 7; nunca menos de 7,
     porque o ecrã aceita ?versao= até 7 dias — app/raw/query.generation);
  3. gerações referidas por objetos: referências semanais (capacity_generation,
     sources.planning_versions…), cenários e planos aceites do Gantt
     (raw_jobs.input.source_references), análises em fila (input.version);
  4. fecho transitivo: gerações referidas nos metadados de gerações mantidas
     (core_generation, planning_versions, applied_planning_versions,
     macro_evidence_reuse.previous_generation) — o recálculo incremental da
     capacidade relê estes cursores (app/raw/capacity_scope.rows_at);
  5. para cada capacity:/capacity_machines: mantida, a geração capacity_items:
     da mesma área com o mesmo source_fingerprint (app/raw/capacity_views).

Conteúdos mantidos: os referidos por membros mantidos, os pais
(detail_source_hash) desses conteúdos, a evidência de produtividade referida por
history_hash dentro dos detalhes mantidos, os hashes (64 hex) referidos nos
metadados das gerações mantidas (ocr_manifest, source_manifest) e em objetos/jobs
(referências semanais congelam history_hash), todos os conteúdos criados nos
últimos N dias, a cache macro_inputs e qualquer conteúdo avulso de tipo
desconhecido.

As linhas de raw_generations NÃO são apagadas: pesam ~30 MB, guardam a
auditoria de quando e de quê cada publicação foi feita, e nenhum leitor da app
as usa sem passar por regras que já as recusam (versões com mais de 7 dias
expiram em query.generation; os cursores de capacidade ficam mantidos pela
regra 4).

Uso, por esta ordem:
    python scripts/raw_retention.py                      # --dry-run: só conta (SELECT, ~15 min)
    python scripts/raw_retention.py --create-indexes --dsn <dono das tabelas>
    python scripts/migrate.py apply                      # sql/050 só regista os índices
    python scripts/raw_retention.py --execute            # apaga em lotes pequenos

Corrida com as publicações (o serviço continua a correr):
  - Um lock de exclusividade ('planning-raw-retention') numa ligação própria, do
    princípio ao fim. Uma segunda execução recusa logo.
  - Membros: só se apagam membros fechados (last_generation <= geração mantida).
    Os publicadores só mexem em membros com last_generation NULL e criam membros
    com first_generation maior do que todas as gerações existentes; por isso esta
    fase não precisa dos locks dos publicadores.
  - Conteúdos: cada lote toma SEM ESPERAR (pg_try_advisory_xact_lock) os locks
    de todos os publicadores, pela ordem deles: 'capacity-revision',
    'raw-build:<área>', 'raw:<dataset>'. Se algum estiver ocupado, desfaz e tenta
    outra vez (~0,25 s, --retry-s) até --max-wait-s; depois pára e fica incompleto.
    Os candidatos de cada janela são escolhidos fora dos locks; dentro deles só
    se apagam sublotes de --locked-batch-size (500) com nova verificação completa. Depois de
    apagar e antes de confirmar, se um publicador ficou à espera de um destes
    locks, desfaz o lote e cede-lhe a vez (um publicador REPEATABLE READ pode ter
    tirado a fotografia da base antes de ficar à espera).
  - Antes dos conteúdos avulsos (productivity/ocr_manifest/source_manifest, os
    únicos referidos por JSON e não por chave estrangeira), a lista do que fica
    é atualizada com as gerações publicadas durante a limpeza. Dentro dos locks,
    se aparecer uma geração ainda não vista, desfaz, atualiza e repete.

--execute não cria índices: confirma que raw_member_content_hash e
raw_content_detail_source existem e estão válidos (--create-indexes). Não faz
VACUUM FULL: imprime o comando para correr à parte, com aviso. Escreve um
registo JSON ao longo da execução; código de saída 2 se ficar incompleto.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# O ecrã aceita versões até 7 dias (app/raw/query.generation). Menos do que
# isto deixaria ?versao= a ler uma geração sem membros (lista vazia).
MIN_KEEP_DAYS = 7
DEFAULT_BATCH = 5000
DEFAULT_MAX_WAIT_S = 900
# Medido em produção (06/10, 60 s a amostrar pg_locks): o serviço de cálculo toma
# 'capacity-revision' cerca de uma vez por segundo e segura-o ~56% do tempo; os
# intervalos livres duram ~0,3 s. Por isso os candidatos são escolhidos FORA dos
# locks e apagados em sublotes pequenos dentro deles (poucas dezenas de ms), e a
# nova tentativa é rápida. Um lote grande dentro dos locks cederia quase sempre.
DEFAULT_LOCKED_BATCH = 500
DEFAULT_RETRY_S = 0.25

# Chaves JSON cujo valor (ou subárvore) contém ids de geração.
GENERATION_KEYS = frozenset({
    'generation', 'core_generation', 'previous_generation', 'planning_generation',
    'capacity_generation', 'production_generation', 'planning_versions',
    'applied_planning_versions', 'application_generations', 'version',
})
HEX64 = re.compile(r'^[0-9a-f]{64}$')
# Conteúdos avulsos (sem membros) que a retenção pode apagar quando ninguém os
# refere. A cache macro_inputs e tipos desconhecidos ficam sempre.
DELETABLE_STANDALONE = ('productivity', 'ocr_manifest', 'source_manifest')

MEMBER_INDEX = 'raw_member_content_hash'
SOURCE_INDEX = 'raw_content_detail_source'
INDEXES = {
    MEMBER_INDEX: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS raw_member_content_hash '
                  'ON planning_mtg.raw_members(content_hash)',
    SOURCE_INDEX: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS raw_content_detail_source '
                  'ON planning_mtg.raw_contents(detail_source_hash) WHERE detail_source_hash IS NOT NULL',
}

VACUUM_COMMAND = ('VACUUM (FULL, ANALYZE, VERBOSE) planning_mtg.raw_contents; '
                  'VACUUM (FULL, ANALYZE, VERBOSE) planning_mtg.raw_members;')

# Locks (todos pg_advisory_xact_lock(hashtextextended(chave,0)) nos publicadores):
#   capacity_revision.rebuild e incremental.baseline: 'capacity-revision';
#   projection.rebuild (evidência: productivity.persist; manifests: ocr_scope.store,
#   source_scope.store) e incremental.publish: 'raw-build:<área>';
#   projection.publish/publish_delta (também capacidade e rebuild_original): 'raw:<dataset>'.
# Ordem global dos publicadores: capacity-revision < raw-build:* < raw:*.
GUARD_KEY = 'planning-raw-retention'
CAPACITY_KEY = 'capacity-revision'
DEFAULT_AREAS = ('perfis', 'cantoneiras')

# Condição SQL: conteúdo protegido independentemente de referências.
PROTECTED_SQL = ("(c.created_at >= %(cutoff)s OR (c.values_json = '{}'::jsonb AND c.detail_source_hash IS NULL "
                 "AND NOT (c.detail ?| %(deletable)s)))")
# As três passagens dos conteúdos.
DERIVED_SQL = 'c.detail_source_hash IS NOT NULL'
STANDALONE_SQL = "(c.detail_source_hash IS NULL AND c.values_json = '{}'::jsonb AND c.detail ?| %(deletable)s)"
MEMBER_CONTENT_SQL = f'(c.detail_source_hash IS NULL AND NOT {STANDALONE_SQL})'
UNREFERENCED_SQL = f'''NOT EXISTS (SELECT 1 FROM raw_retention_keep k WHERE k.h = c.hash)
                  AND NOT {PROTECTED_SQL}
                  AND NOT EXISTS (SELECT 1 FROM planning_mtg.raw_members m WHERE m.content_hash = c.hash)
                  AND NOT EXISTS (SELECT 1 FROM planning_mtg.raw_contents d WHERE d.detail_source_hash = c.hash)'''


class RetentionRefused(RuntimeError):
    """Recusa antes de apagar o que quer que seja."""


# ---------------------------------------------------------------- regras puras

@dataclass(frozen=True)
class Generation:
    id: int
    dataset: str
    created_at: datetime
    metadata: dict


@dataclass
class Plan:
    keep: dict = field(default_factory=dict)          # id -> conjunto de razões
    drop: list = field(default_factory=list)          # ids sem membros a partir de agora
    kept_by_dataset: dict = field(default_factory=dict)  # dataset -> ids ordenados
    cutoff: datetime | None = None

    def gaps(self, dataset):
        """Intervalos abertos (lo, hi) entre gerações mantidas do dataset."""
        ids = self.kept_by_dataset.get(dataset) or []
        bounds = [0] + ids
        return [(lo, hi) for lo, hi in zip(bounds, ids) if hi - lo > 1]


def _ints(value):
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        yield value
    elif isinstance(value, str) and value.isdigit():
        yield int(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _ints(item)
    elif isinstance(value, list):
        for item in value:
            yield from _ints(item)


def generation_refs(value):
    """Ids de geração em qualquer chave conhecida, a qualquer profundidade."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in GENERATION_KEYS:
                found.update(_ints(item))
            found |= generation_refs(item)
    elif isinstance(value, list):
        for item in value:
            found |= generation_refs(item)
    return found


def hash_refs(value):
    """Todos os textos com forma de hash SHA-256 (valores e chaves)."""
    found = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            found.update(k for k in item if HEX64.match(k))
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and HEX64.match(item):
            found.add(item)
    return found


def plan_generations(generations, *, keep_days=MIN_KEEP_DAYS, now=None, object_generation_refs=()):
    """Decide que gerações mantêm membros. Puro: não toca na base de dados."""
    if keep_days < MIN_KEEP_DAYS:
        raise ValueError(f'--keep-days tem de ser pelo menos {MIN_KEEP_DAYS} (o ecrã aceita versões até 7 dias).')
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    by_id = {g.id: g for g in generations}
    by_dataset = defaultdict(list)
    for g in generations:
        by_dataset[g.dataset].append(g)
    keep = defaultdict(set)
    pending = []

    def add(gid, reason):
        if gid in by_id:
            if gid not in keep:
                pending.append(gid)
            keep[gid].add(reason)

    for dataset, items in by_dataset.items():
        items.sort(key=lambda g: g.id, reverse=True)
        for position, g in enumerate(items[:2]):
            add(g.id, 'atual' if position == 0 else 'anterior')
    for g in generations:
        if g.created_at >= cutoff:
            add(g.id, 'recente')
    for gid in object_generation_refs:
        add(gid, 'objeto')
    # Itens de capacidade por (área, fingerprint): a mais recente, como em capacity_views.
    items_by_fp = {}
    for g in sorted(generations, key=lambda g: g.id):
        if g.dataset.startswith('capacity_items:'):
            items_by_fp[(g.dataset.split(':', 1)[1], (g.metadata or {}).get('source_fingerprint'))] = g.id
    while pending:
        g = by_id[pending.pop()]
        for ref in generation_refs(g.metadata or {}):
            add(ref, 'metadados')
        kind, _, area = g.dataset.partition(':')
        if kind in ('capacity', 'capacity_machines'):
            sibling = items_by_fp.get((area, (g.metadata or {}).get('source_fingerprint')))
            if sibling is not None:
                add(sibling, 'itens_capacidade')
    plan = Plan(keep=dict(keep), cutoff=cutoff)
    plan.drop = sorted(gid for gid in by_id if gid not in keep)
    for dataset, items in by_dataset.items():
        plan.kept_by_dataset[dataset] = sorted(g.id for g in items if g.id in keep)
    return plan


# ---------------------------------------------------------------- leitura

def _table_exists(c, name):
    return c.execute('SELECT to_regclass(%s) t', (name,)).fetchone()['t'] is not None


def load_generations(c):
    return [Generation(r['id'], r['dataset'], r['created_at'], r['metadata'] or {}) for r in c.execute(
        'SELECT id,dataset,created_at,metadata FROM planning_mtg.raw_generations ORDER BY id')]


def load_object_refs(c):
    """Ids de geração e hashes referidos por objetos guardados e jobs."""
    generations, hashes = set(), set()
    sources = [('planning_mtg.raw_objects', 'SELECT definition AS j FROM planning_mtg.raw_objects'),
               ('planning_mtg.raw_object_versions', 'SELECT definition AS j FROM planning_mtg.raw_object_versions'),
               ('planning_mtg.raw_jobs', "SELECT jsonb_build_array(input,coalesce(result,'null'::jsonb)) AS j FROM planning_mtg.raw_jobs")]
    for table, sql in sources:
        if not _table_exists(c, table):
            continue
        for r in c.execute(sql):
            generations |= generation_refs(r['j'])
            hashes |= hash_refs(r['j'])
    return generations, hashes


def kept_json(plan):
    from psycopg.types.json import Jsonb
    return Jsonb([{'dataset': d, 'ids': ids} for d, ids in plan.kept_by_dataset.items()])


# Um membro cobre alguma geração mantida k (first <= k < last) sse o número de
# ids mantidos < last é maior do que o número de ids mantidos < first.
# width_bucket(x, ids) devolve quantos ids ordenados são <= x.
MEMBER_DROP_SQL = '''m.last_generation IS NOT NULL AND k.ids IS NOT NULL
    AND m.first_generation <= k.ids[cardinality(k.ids)]
    AND width_bucket(m.last_generation-1, k.ids) = width_bucket(m.first_generation-1, k.ids)'''
KEPT_CTE = 'WITH k AS (SELECT * FROM jsonb_to_recordset(%(kept)s) AS x(dataset text, ids bigint[]))'


def member_stats(c, plan):
    rows = c.execute(KEPT_CTE + f'''
        SELECT m.dataset, count(*) total, count(*) FILTER (WHERE {MEMBER_DROP_SQL}) apagar,
               coalesce(sum(pg_column_size(m.*)) FILTER (WHERE {MEMBER_DROP_SQL}),0) bytes_apagar,
               coalesce(sum(pg_column_size(m.*)),0) bytes_total
        FROM planning_mtg.raw_members m LEFT JOIN k USING(dataset) GROUP BY 1 ORDER BY 1''',
        {'kept': kept_json(plan)}).fetchall()
    return rows


def kept_member_hashes(c, plan=None):
    """Conteúdos dos membros que ficam (todos os restantes, sem plano)."""
    if plan is None:
        sql, params = 'SELECT DISTINCT content_hash h FROM planning_mtg.raw_members', {}
    else:
        sql = KEPT_CTE + f'''SELECT DISTINCT m.content_hash h FROM planning_mtg.raw_members m
            LEFT JOIN k USING(dataset) WHERE NOT ({MEMBER_DROP_SQL})'''
        params = {'kept': kept_json(plan)}
    with c.cursor(name='raw_retention_hashes') as cur:
        cur.itersize = 50000
        cur.execute(sql, params)
        return {r['h'] for r in cur}


def expand_content_keep(c, seeds, *, batch=20000, log=print, known=()):
    """Junta pais (detail_source_hash) e evidência (history_hash) até estabilizar.

    `known`: conteúdos já mantidos e já expandidos (não volta a percorrê-los)."""
    keep = set(seeds)
    frontier = sorted(keep - set(known))
    level = 0
    while frontier:
        level += 1
        found = set()
        for offset in range(0, len(frontier), batch):
            chunk = frontier[offset:offset + batch]
            for r in c.execute('''SELECT c.detail_source_hash,
                    ARRAY(SELECT DISTINCT x #>> '{}' FROM jsonb_path_query(c.detail, 'lax $.**.history_hash') x
                          UNION SELECT DISTINCT y #>> '{}' FROM jsonb_path_query(coalesce(c.detail_patch,'null'::jsonb), 'lax $.**.history_hash') y) refs
                FROM planning_mtg.raw_contents c WHERE c.hash = ANY(%s)''', (chunk,)):
                if r['detail_source_hash']:
                    found.add(r['detail_source_hash'])
                found.update(h for h in r['refs'] if h and HEX64.match(h))
        frontier = sorted(found - keep - set(known))
        keep |= found
        log(f'  nível {level}: +{len(frontier)} conteúdos referidos (pais e evidência)')
    return keep


def content_keep_set(c, plan, generations, object_hashes, *, member_plan, log=print):
    seeds = kept_member_hashes(c, plan if member_plan else None)
    log(f'  conteúdos de membros mantidos: {len(seeds)}')
    kept_meta = set()
    by_id = {g.id: g for g in generations}
    for gid in plan.keep:
        kept_meta |= hash_refs(by_id[gid].metadata)
    extra = (kept_meta | set(object_hashes)) - seeds
    log(f'  hashes referidos por metadados e objetos: {len(kept_meta | set(object_hashes))}')
    return expand_content_keep(c, seeds | extra, log=log)


def content_stats(c, keep, cutoff):
    return c.execute(f'''WITH keep AS MATERIALIZED (SELECT unnest(%(keep)s::text[]) h)
        SELECT CASE WHEN c.detail_source_hash IS NOT NULL THEN 'derivado'
                    WHEN c.values_json = '{{}}'::jsonb THEN coalesce((SELECT min(k) FROM jsonb_object_keys(c.detail) k),'avulso')
                    ELSE 'membro' END tipo,
               count(*) total,
               count(*) FILTER (WHERE NOT keep_hit AND NOT protegido) apagar,
               coalesce(sum(bytes) FILTER (WHERE NOT keep_hit AND NOT protegido),0) bytes_apagar,
               coalesce(sum(bytes),0) bytes_total
        FROM (SELECT c.*, (k.h IS NOT NULL) keep_hit, {PROTECTED_SQL} protegido,
                     pg_column_size(c.values_json)+pg_column_size(c.detail)+pg_column_size(c.search_text)
                     +coalesce(pg_column_size(c.detail_patch),0)+coalesce(pg_column_size(c.detail_source_hash),0)
                     +pg_column_size(c.hash) bytes
              FROM planning_mtg.raw_contents c LEFT JOIN keep k ON k.h = c.hash) c
        GROUP BY 1 ORDER BY 1''', {'keep': sorted(keep), 'cutoff': cutoff,
                                   'deletable': list(DELETABLE_STANDALONE)}).fetchall()


def relation_sizes(c):
    return c.execute('''SELECT pg_total_relation_size('planning_mtg.raw_contents') contents,
        pg_total_relation_size('planning_mtg.raw_members') members,
        pg_total_relation_size('planning_mtg.raw_generations') generations''').fetchone()


def index_state(c):
    """{nome: True (válido) | False (inválido) | None (não existe)} dos índices de suporte."""
    state = {name: None for name in INDEXES}
    for r in c.execute('''SELECT x.relname, (i.indisvalid AND i.indisready) ok FROM pg_class x
            JOIN pg_index i ON i.indexrelid = x.oid
            WHERE x.relnamespace = 'planning_mtg'::regnamespace AND x.relname = ANY(%s)''', (list(INDEXES),)):
        state[r['relname']] = bool(r['ok'])
    return state


def _areas():
    try:
        from app import planning
        return tuple(planning.AREAS)
    except Exception:  # noqa: BLE001 - sem a app (--dsn noutra máquina) usa as áreas conhecidas
        return DEFAULT_AREAS


def publisher_keys(c):
    """Chaves dos locks dos publicadores, pela ordem em que eles as tomam."""
    datasets = c.execute("SELECT coalesce(array_agg(DISTINCT dataset ORDER BY dataset), '{}'::text[]) d "
                         'FROM planning_mtg.raw_generations').fetchone()['d']
    areas = sorted(set(_areas()) | {d.split(':', 1)[1] for d in datasets if ':' in d})
    return [CAPACITY_KEY, *('raw-build:' + a for a in areas), *('raw:' + d for d in datasets)]


def server_notes(c):
    notes = {}
    for name in ('max_wal_size', 'archive_mode', 'full_page_writes', 'maintenance_work_mem'):
        try:
            notes[name] = c.execute('SELECT current_setting(%s) v', (name,)).fetchone()['v']
        except Exception:  # noqa: BLE001 - definição indisponível não impede a contagem
            notes[name] = '?'
    try:
        notes['replication_slots'] = c.execute('SELECT count(*) n FROM pg_replication_slots').fetchone()['n']
    except Exception:  # noqa: BLE001
        notes['replication_slots'] = '?'
    state = index_state(c)
    notes['indices'] = {name: {True: 'válido', False: 'inválido', None: 'em falta'}[ok] for name, ok in state.items()}
    notes['missing_indexes'] = [name for name, ok in state.items() if ok is not True]
    return notes


# ---------------------------------------------------------------- relatório

def gb(value):
    return f'{value / 1024 ** 3:.2f} GB'


def analyse(c, *, keep_days, now=None, log=print):
    """Contagem completa num único instantâneo. Só SELECT.

    Peso: a fotografia (REPEATABLE READ) fica aberta ~15 min em produção; durante
    esse tempo o autovacuum não limpa linhas mortas mais recentes do que ela."""
    generations = load_generations(c)
    object_generations, object_hashes = load_object_refs(c)
    plan = plan_generations(generations, keep_days=keep_days, now=now, object_generation_refs=object_generations)
    reasons = defaultdict(int)
    for why in plan.keep.values():
        for reason in why:
            reasons[reason] += 1
    log(f'Gerações: {len(generations)} no total; {len(plan.keep)} mantidas; {len(plan.drop)} perdem os membros '
        f'(as linhas de raw_generations ficam para auditoria).')
    log('  razões (uma geração pode ter várias): ' + ', '.join(f'{k}={v}' for k, v in sorted(reasons.items())))
    members = member_stats(c, plan)
    log('Membros por dataset (total / a apagar):')
    for r in members:
        log(f"  {r['dataset']:<32} {r['total']:>10} / {r['apagar']:>10}")
    log('A calcular os conteúdos mantidos…')
    keep = content_keep_set(c, plan, generations, object_hashes, member_plan=True, log=log)
    contents = content_stats(c, keep, plan.cutoff)
    sizes = relation_sizes(c)
    member_drop = sum(r['bytes_apagar'] for r in members)
    member_total = sum(r['bytes_total'] for r in members) or 1
    content_drop = sum(r['bytes_apagar'] for r in contents)
    content_total = sum(r['bytes_total'] for r in contents) or 1
    log('Conteúdos por tipo (total / a apagar):')
    for r in contents:
        log(f"  {r['tipo']:<32} {r['total']:>10} / {r['apagar']:>10}")
    estimate = {
        'raw_contents_atual': sizes['contents'],
        'raw_contents_libertado_estimado': int(sizes['contents'] * content_drop / content_total),
        'raw_members_atual': sizes['members'],
        'raw_members_libertado_estimado': int(sizes['members'] * member_drop / member_total),
    }
    keys = publisher_keys(c)
    summary = {
        'keep_days': keep_days, 'cutoff': plan.cutoff.isoformat(),
        'generations': {'total': len(generations), 'mantidas': len(plan.keep), 'esvaziadas': len(plan.drop),
                        'razoes': dict(reasons)},
        'members': {'total': sum(r['total'] for r in members), 'apagar': sum(r['apagar'] for r in members),
                    'por_dataset': {r['dataset']: {'total': r['total'], 'apagar': r['apagar']} for r in members}},
        'contents': {'total': sum(r['total'] for r in contents), 'apagar': sum(r['apagar'] for r in contents),
                     'mantidos_referidos': len(keep),
                     'por_tipo': {r['tipo']: {'total': r['total'], 'apagar': r['apagar']} for r in contents}},
        'bytes': estimate, 'servidor': server_notes(c), 'locks_publicadores': keys,
    }
    log(f"Espaço: raw_contents {gb(estimate['raw_contents_atual'])} → liberta ~{gb(estimate['raw_contents_libertado_estimado'])}; "
        f"raw_members {gb(estimate['raw_members_atual'])} → liberta ~{gb(estimate['raw_members_libertado_estimado'])} "
        '(só depois de VACUUM FULL; antes disso o espaço fica livre dentro das tabelas, não no disco).')
    notes = summary['servidor']
    log(f"Servidor: max_wal_size={notes['max_wal_size']} archive_mode={notes['archive_mode']} "
        f"maintenance_work_mem={notes['maintenance_work_mem']} replication_slots={notes['replication_slots']}")
    log('Índices de suporte: ' + ', '.join(f'{k} {v}' for k, v in notes['indices'].items()))
    log(f'Locks dos publicadores tomados em cada lote de conteúdos ({len(keys)}): ' + ', '.join(keys))
    return plan, generations, summary


# ---------------------------------------------------------------- execução

TRANSIENT_ERRORS = ('LockNotAvailable', 'QueryCanceled', 'SerializationFailure', 'DeadlockDetected',
                    'ForeignKeyViolation')


class _Busy(Exception):
    """Um lock de publicador está ocupado."""


class _Yield(Exception):
    """Um publicador ficou à espera de um dos nossos locks: desfazer e ceder."""


class _Refresh(Exception):
    """Apareceu uma geração ainda não vista: atualizar a lista do que fica."""


@dataclass
class Options:
    batch: int = DEFAULT_BATCH        # janela de leitura (membros e conteúdos)
    locked_batch: int = DEFAULT_LOCKED_BATCH  # conteúdos apagados por transação com os locks
    lock_timeout: int = 2000          # ms, por instrução (locks de linhas/tabelas)
    statement_timeout: int = 60000    # ms, por instrução
    max_wait_s: float = DEFAULT_MAX_WAIT_S  # por lote, à espera dos locks dos publicadores
    retry_s: float = DEFAULT_RETRY_S  # pausa média entre tentativas (com variação)
    attempts: int = 5                 # tentativas por lote de membros


@dataclass
class _KeepState:
    keep: set
    seen: set   # ids de geração já considerados na lista do que fica


class _Progress:
    """Chama progress(record) em cada fase e a cada 60 s ou 50 lotes."""

    def __init__(self, record, callback, *, every_s=60, every_batches=50):
        self.record, self.callback = record, callback
        self.every_s, self.every_batches = every_s, every_batches
        self.batches, self.last = 0, time.monotonic()

    def phase(self, name):
        self.record['fase'] = name
        self._emit()

    def tick(self):
        self.batches += 1
        if self.batches >= self.every_batches or time.monotonic() - self.last >= self.every_s:
            self._emit()

    def _emit(self):
        self.batches, self.last = 0, time.monotonic()
        if self.callback:
            self.callback(self.record)


def _connect(dsn, *, autocommit=False, readonly=False):
    import psycopg
    from psycopg.rows import dict_row
    c = psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10, autocommit=autocommit,
                        application_name='raw_retention')
    c.read_only = readonly
    return c


def _is_transient(exc):
    return type(exc).__name__ in TRANSIENT_ERRORS


def _set_timeouts(c, opts):
    c.execute(f"SET LOCAL lock_timeout = '{int(opts.lock_timeout)}ms'")
    c.execute(f"SET LOCAL statement_timeout = '{int(opts.statement_timeout)}ms'")


def _try_locks(c, keys):
    """Toma sem esperar os locks de transação; devolve a primeira chave ocupada."""
    for key in keys:
        if not c.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) ok', (key,)).fetchone()['ok']:
            return key
    return None


def _publishers_waiting(c, keys):
    """Há alguém (outra sessão) à espera de um destes locks de 64 bits?"""
    return c.execute('''SELECT EXISTS (SELECT 1 FROM pg_locks l
            JOIN unnest(%s::text[]) AS k(key)
              ON l.classid::bigint = ((hashtextextended(k.key,0) >> 32) & 4294967295)
             AND l.objid::bigint = (hashtextextended(k.key,0) & 4294967295)
            WHERE l.locktype = 'advisory' AND NOT l.granted AND l.objsubid = 1
              AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())) w''',
                     (list(keys),)).fetchone()['w']


def _run_batch(c, work, *, opts, stats, log, label):
    """Lote sem locks de publicadores (membros). Devolve o resultado de work(c) ou None se desistir."""
    for attempt in range(1, opts.attempts + 1):
        try:
            with c.transaction():
                _set_timeouts(c, opts)
                return work(c)
        except Exception as exc:  # noqa: BLE001 - só os erros transitórios repetem
            if not _is_transient(exc):
                raise
            stats['esperas_lock'] += 1
            log(f'  {label}: lote adiado ({type(exc).__name__}), tentativa {attempt}/{opts.attempts}')
            time.sleep(min(max(opts.retry_s, 0.5) * 2 ** attempt, 30))
    log(f'  {label}: lote ignorado depois de várias tentativas; fica para a próxima execução.')
    return None


def _locked_batch(c, work, *, opts, stats, log, label):
    """Lote de conteúdos com os locks de todos os publicadores (só try-locks: nunca espera nem entra em deadlock).

    Devolve o resultado de work(c), ou None se ao fim de opts.max_wait_s não conseguir.
    _Refresh lançado por work passa para quem chamou (depois do ROLLBACK)."""
    deadline = time.monotonic() + opts.max_wait_s
    attempt = 0
    while True:
        attempt += 1
        try:
            with c.transaction():
                _set_timeouts(c, opts)
                keys = publisher_keys(c)
                busy = _try_locks(c, keys)
                if busy:
                    raise _Busy(busy)
                result = work(c)
                if _publishers_waiting(c, keys):
                    raise _Yield()
            return result
        except _Busy as exc:
            stats['esperas_lock'] += 1
            reason = f"lock '{exc}' ocupado por uma publicação"
        except _Yield:
            stats['cedencias'] += 1
            reason = 'uma publicação ficou à espera; lote desfeito para lhe dar a vez'
        except Exception as exc:  # noqa: BLE001 - só os erros transitórios repetem
            if not _is_transient(exc):
                raise
            stats['esperas_lock'] += 1
            reason = type(exc).__name__
        if time.monotonic() >= deadline:
            log(f'  {label}: desisto ao fim de {opts.max_wait_s:.0f}s ({reason}).')
            return None
        if attempt == 1 or attempt % 60 == 0:
            log(f'  {label}: à espera ({reason})…')
        time.sleep(opts.retry_s * random.uniform(0.5, 1.5))


def delete_members(c, plan, *, opts, stats, log=print, tick=None):
    """Apaga membros fechados entre gerações mantidas, com um cursor por first_generation.

    Sem locks de publicadores: só se apagam membros com last_generation <= hi (uma
    geração mantida, já publicada); os publicadores só fecham membros com
    last_generation NULL e criam membros com first_generation acima de tudo o que existe."""
    total = 0
    for dataset in sorted(plan.kept_by_dataset):
        deleted = 0
        for lo, hi in plan.gaps(dataset):
            cursor = lo + 1
            while True:
                def work(c, cursor=cursor):
                    rows = c.execute('''DELETE FROM planning_mtg.raw_members m USING (
                            SELECT dataset,row_key,first_generation FROM planning_mtg.raw_members
                            WHERE dataset=%s AND first_generation>=%s AND first_generation<%s AND last_generation<=%s
                            ORDER BY first_generation LIMIT %s) d
                        WHERE m.dataset=d.dataset AND m.row_key=d.row_key AND m.first_generation=d.first_generation
                        RETURNING m.first_generation''', (dataset, cursor, hi, hi, opts.batch)).fetchall()
                    return [r['first_generation'] for r in rows]
                done = _run_batch(c, work, opts=opts, stats=stats, log=log, label=f'membros {dataset}')
                if done is None:
                    stats['lotes_ignorados'] += 1
                    stats['por_terminar'].append({'fase': 'membros', 'dataset': dataset, 'desde_geracao': cursor,
                                                  'ate_geracao': hi})
                    break
                deleted += len(done)
                if tick:
                    tick()
                if len(done) < opts.batch:
                    break
                # Não volta a ler os sobreviventes antes do cursor.
                cursor = max(done)
        if deleted:
            log(f'  {dataset}: {deleted} membros apagados')
        total += deleted
    return total


def _add_keep(c, state, hashes):
    new = set(hashes) - state.keep
    if new:
        with c.cursor().copy('COPY raw_retention_keep(h) FROM STDIN') as copy:
            for h in new:
                copy.write_row((h,))
        c.execute('ANALYZE raw_retention_keep')
        state.keep |= new
    return new


def _unseen_generations(c, seen):
    return c.execute('SELECT EXISTS (SELECT 1 FROM planning_mtg.raw_generations WHERE NOT (id = ANY(%s))) x',
                     (sorted(seen),)).fetchone()['x']


def refresh_keep(c, state, *, stats, log=print):
    """Fora dos locks: junta à lista do que fica o que as gerações publicadas entretanto referem.

    Gerações por id ainda não visto (a ordem da sequência não é a ordem dos commits):
    hashes nos metadados, conteúdos dos membros que criaram (com pais e evidência) e,
    de novo, os hashes de objetos e jobs."""
    with c.transaction():
        rows = c.execute('SELECT id,dataset,metadata FROM planning_mtg.raw_generations WHERE NOT (id = ANY(%s))',
                         (sorted(state.seen),)).fetchall()
        found = set()
        for r in rows:
            found |= hash_refs(r['metadata'] or {})
        if rows:
            found |= {r['h'] for r in c.execute('''SELECT DISTINCT m.content_hash h FROM planning_mtg.raw_members m
                    JOIN unnest(%s::text[], %s::bigint[]) AS g(dataset, id)
                      ON m.dataset = g.dataset AND m.first_generation = g.id''',
                    ([r['dataset'] for r in rows], [r['id'] for r in rows]))}
        _, object_hashes = load_object_refs(c)
        found |= object_hashes
        added = expand_content_keep(c, found - state.keep, log=log, known=state.keep) if found - state.keep else set()
    new = _add_keep(c, state, added)
    state.seen |= {r['id'] for r in rows}
    stats['atualizacoes'] += 1
    log(f'  lista do que fica atualizada: {len(rows)} gerações novas, +{len(new)} conteúdos mantidos')
    return new


def delete_contents(c, state, cutoff, *, opts, stats, log=print, progress=None):
    """Três passagens: derivados (apontam para os pais), conteúdos de membros, avulsos.

    Devolve True se terminou; False se um lote desistiu (a limpeza fica incompleta)."""
    progress = progress or _Progress(stats, None)
    totals = stats['contents_deleted']
    params = {'cutoff': cutoff, 'deletable': list(DELETABLE_STANDALONE)}
    for label, only in (('derivados', DERIVED_SQL), ('membros', MEMBER_CONTENT_SQL)):
        deleted, last = totals.get(label, 0), ''
        while True:
            # Fora dos locks: a janela seguinte e os seus candidatos (a parte pesada da verificação).
            with c.transaction():
                _set_timeouts(c, opts)
                hi = c.execute('''SELECT max(hash) h FROM (SELECT hash FROM planning_mtg.raw_contents
                    WHERE hash > %s ORDER BY hash LIMIT %s) w''', (last, opts.batch)).fetchone()['h']
                candidates = [] if hi is None else [r['hash'] for r in c.execute(
                    f'''SELECT c.hash FROM planning_mtg.raw_contents c
                    WHERE c.hash > %(lo)s AND c.hash <= %(hi)s AND {only} AND {UNREFERENCED_SQL} ORDER BY c.hash''',
                    {**params, 'lo': last, 'hi': hi})]
            if hi is None:
                break
            for offset in range(0, len(candidates), opts.locked_batch):
                chunk = candidates[offset:offset + opts.locked_batch]

                def work(c, chunk=chunk):
                    # Dentro dos locks volta a confirmar tudo (alguém pode ter passado a referi-los).
                    return c.execute(f'''DELETE FROM planning_mtg.raw_contents c
                        WHERE c.hash = ANY(%(chunk)s) AND {only} AND {UNREFERENCED_SQL}''',
                                     {**params, 'chunk': chunk}).rowcount
                n = _locked_batch(c, work, opts=opts, stats=stats, log=log, label=f'conteúdos {label}')
                if n is None:
                    stats['lotes_ignorados'] += 1
                    stats['por_terminar'].append({'fase': f'conteúdos {label}', 'desde_hash': last})
                    totals[label] = deleted
                    return False
                deleted += n
                totals[label] = deleted
                progress.tick()
            last = hi
        log(f'  conteúdos {label}: {deleted} apagados')
        progress.phase(f'conteudos_{label}')

    # Avulsos: referidos por JSON, não por chave estrangeira. Primeiro atualizar.
    refresh_keep(c, state, stats=stats, log=log)
    progress.phase('atualizado')
    candidates = [r['h'] for r in c.execute(f'''SELECT c.hash h FROM planning_mtg.raw_contents c
        WHERE {STANDALONE_SQL} AND NOT {PROTECTED_SQL}
          AND NOT EXISTS (SELECT 1 FROM raw_retention_keep k WHERE k.h = c.hash) ORDER BY c.hash''', params)]
    deleted = totals.get('avulsos', 0)
    for offset in range(0, len(candidates), opts.locked_batch):
        chunk = candidates[offset:offset + opts.locked_batch]

        def work(c, chunk=chunk):
            # Com os locks todos tomados não há publicações por confirmar: a lista de ids fica completa.
            if _unseen_generations(c, state.seen):
                raise _Refresh()
            return c.execute(f'''DELETE FROM planning_mtg.raw_contents c
                WHERE c.hash = ANY(%(chunk)s) AND {STANDALONE_SQL} AND {UNREFERENCED_SQL}''',
                             {**params, 'chunk': chunk}).rowcount
        while True:
            try:
                n = _locked_batch(c, work, opts=opts, stats=stats, log=log, label='conteúdos avulsos')
                break
            except _Refresh:
                refresh_keep(c, state, stats=stats, log=log)
        if n is None:
            stats['lotes_ignorados'] += 1
            stats['por_terminar'].append({'fase': 'conteúdos avulsos', 'desde_hash': chunk[0]})
            totals['avulsos'] = deleted
            return False
        deleted += n
        totals['avulsos'] = deleted
        progress.tick()
    totals['avulsos'] = deleted
    log(f'  conteúdos avulsos: {deleted} apagados')
    return True


def check_ready(c):
    """Antes de apagar seja o que for: privilégio DELETE e índices válidos."""
    privileges = c.execute('''SELECT has_table_privilege('planning_mtg.raw_members','DELETE') m,
        has_table_privilege('planning_mtg.raw_contents','DELETE') c''').fetchone()
    if not (privileges['m'] and privileges['c']):
        raise RetentionRefused('Esta ligação não pode apagar em raw_members/raw_contents (falta o privilégio DELETE).')
    state = index_state(c)
    invalid = [name for name, ok in state.items() if ok is False]
    missing = [name for name, ok in state.items() if ok is None]
    if invalid or missing:
        steps = []
        for name in invalid:
            steps.append(f'DROP INDEX CONCURRENTLY planning_mtg.{name};  (índice inválido de uma criação interrompida)')
        steps += ['python scripts/raw_retention.py --create-indexes --dsn <dono das tabelas>  (num momento calmo)',
                  'python scripts/migrate.py apply  (sql/050 só regista os índices)',
                  'python scripts/raw_retention.py --execute']
        raise RetentionRefused('Faltam índices válidos (' + ', '.join(invalid + missing) + '); nada foi apagado. '
                               'Passos: ' + ' → '.join(steps))
    return state


def _alive(guard):
    try:
        guard.execute('SELECT 1')
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('A ligação que segura o lock de exclusividade caiu; limpeza abortada.') from exc


def new_record(keep_days):
    return {'estado': 'em_curso', 'fase': 'inicio', 'started_at': datetime.now(timezone.utc).isoformat(),
            'finished_at': None, 'keep_days': keep_days, 'cutoff': None, 'generations_kept': None,
            'generations_emptied': None, 'members_deleted': 0, 'contents_deleted': {},
            'esperas_lock': 0, 'cedencias': 0, 'atualizacoes': 0, 'lotes_ignorados': 0, 'por_terminar': [],
            'erro': None}


def execute(dsn, *, keep_days, batch=DEFAULT_BATCH, lock_timeout=2000, statement_timeout=60000,
            max_wait_s=DEFAULT_MAX_WAIT_S, retry_s=DEFAULT_RETRY_S, now=None, log=print, progress=None, record=None,
            locked_batch=DEFAULT_LOCKED_BATCH):
    """Apaga o histórico ilegível. `progress(record)` é chamado em cada fase e periodicamente.

    `record` (opcional) é preenchido no lugar: quem chama consegue gravá-lo mesmo se houver exceção."""
    opts = Options(batch=batch, lock_timeout=lock_timeout, statement_timeout=statement_timeout,
                   max_wait_s=max_wait_s, retry_s=retry_s, locked_batch=locked_batch)
    if record is None:
        record = {}
    record.update(new_record(keep_days))
    tracker = _Progress(record, progress)
    guard = None
    try:
        # Exclusividade: ligação própria, lock de sessão do princípio ao fim. Nunca espera.
        guard = _connect(dsn, autocommit=True)
        if not guard.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok', (GUARD_KEY,)).fetchone()['ok']:
            raise RetentionRefused('Já existe uma limpeza RAW em curso (outra execução segura o lock); nada foi apagado.')
        with _connect(dsn, autocommit=True) as c:
            check_ready(c)
            with c.transaction():
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                generations = load_generations(c)
                object_generations, object_hashes = load_object_refs(c)
            plan = plan_generations(generations, keep_days=keep_days, now=now, object_generation_refs=object_generations)
            record.update(cutoff=plan.cutoff.isoformat(), generations_kept=len(plan.keep),
                          generations_emptied=len(plan.drop))
            log(f'Plano: {len(plan.keep)} gerações mantidas, {len(plan.drop)} esvaziadas.')
            tracker.phase('plano')

            _alive(guard)
            log('1/3 A apagar membros fora das gerações mantidas…')
            record['members_deleted'] = delete_members(c, plan, opts=opts, stats=record, log=log, tick=tracker.tick)
            tracker.phase('membros')

            _alive(guard)
            log('2/3 A calcular conteúdos referidos (novo instantâneo, inclui o publicado entretanto)…')
            with c.transaction():
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                generations2 = load_generations(c)
                object_generations2, object_hashes2 = load_object_refs(c)
                plan2 = plan_generations(generations2, keep_days=keep_days, now=now,
                                         object_generation_refs=object_generations | object_generations2)
                plan2.keep = {**plan2.keep, **{g: plan.keep[g] for g in plan.keep if g not in plan2.keep}}
                keep = content_keep_set(c, plan2, generations2, object_hashes | object_hashes2,
                                        member_plan=False, log=log)
            c.execute('CREATE TEMP TABLE IF NOT EXISTS raw_retention_keep(h text PRIMARY KEY)')
            c.execute('TRUNCATE raw_retention_keep')
            state = _KeepState(keep=set(), seen={g.id for g in generations2})
            _add_keep(c, state, keep)
            tracker.phase('keep_ready')

            _alive(guard)
            log('3/3 A apagar conteúdos sem referências (com os locks dos publicadores, lote a lote)…')
            complete = delete_contents(c, state, plan.cutoff, opts=opts, stats=record, log=log, progress=tracker)
            _alive(guard)
        record['estado'] = 'concluido' if complete and not record['lotes_ignorados'] else 'incompleto'
    except BaseException as exc:
        record['estado'] = 'interrompido'
        record['erro'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        if guard is not None:
            guard.close()  # fecha a sessão e liberta o lock de exclusividade
    return record


def create_indexes(dsn, *, maintenance_work_mem='1GB', max_transaction_age_s=300, log=print):
    """Cria os dois índices de suporte com CREATE INDEX CONCURRENTLY (exige o dono das tabelas)."""
    if not re.fullmatch(r'\d+(kB|MB|GB)', maintenance_work_mem):
        raise RetentionRefused('--maintenance-work-mem tem de ser, por exemplo, 512MB ou 1GB.')
    with _connect(dsn, autocommit=True) as c:
        if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok', (GUARD_KEY,)).fetchone()['ok']:
            raise RetentionRefused('Há uma limpeza RAW em curso; tenta depois.')
        owner = c.execute('''SELECT bool_and(pg_has_role(current_user, x.relowner, 'MEMBER')) ok FROM pg_class x
            WHERE x.oid IN ('planning_mtg.raw_members'::regclass, 'planning_mtg.raw_contents'::regclass)''').fetchone()['ok']
        if not owner:
            raise RetentionRefused('Esta ligação não é dona de raw_members/raw_contents; usa --dsn com o dono das tabelas.')
        state = index_state(c)
        invalid = [name for name, ok in state.items() if ok is False]
        if invalid:
            raise RetentionRefused('Índice inválido (criação interrompida). Apaga-o primeiro: '
                                   + ' '.join(f'DROP INDEX CONCURRENTLY planning_mtg.{n};' for n in invalid))
        todo = [name for name, ok in state.items() if ok is None]
        if not todo:
            log('Os dois índices já existem e estão válidos. Nada a fazer.')
            return state
        old = c.execute('''SELECT pid, coalesce(application_name,'') app, xact_start FROM pg_stat_activity
            WHERE datname = current_database() AND pid <> pg_backend_pid()
              AND xact_start < now() - make_interval(secs => %s) ORDER BY xact_start''',
                        (max_transaction_age_s,)).fetchall()
        if old:
            raise RetentionRefused('Há transações abertas há mais de 5 min; o CREATE INDEX CONCURRENTLY ficaria à espera '
                                   'delas. ' + '; '.join(f"pid {r['pid']} ({r['app'] or '?'}) desde {r['xact_start']}"
                                                         for r in old))
        sizes = c.execute('''SELECT pg_relation_size('planning_mtg.raw_contents') contents,
            pg_relation_size('planning_mtg.raw_members') members''').fetchone()
        log('AVISO antes de criar os índices:')
        log(f"  - lê a parte principal de raw_contents (~{gb(sizes['contents'])}, sem o TOAST) e de raw_members "
            f"(~{gb(sizes['members'])}), duas vezes cada (CONCURRENTLY);")
        log('  - espera que terminem as transações em curso antes de cada passo; não bloqueia leituras nem gravações;')
        log('  - segura ShareUpdateExclusiveLock: bloqueia autovacuum, VACUUM, ANALYZE e ALTER TABLE nessas tabelas;')
        log('  - não corras scripts/migrate.py ao mesmo tempo (falharia ao fim de 5 s);')
        log(f'  - ocupa ~1 GB de disco (índice e ficheiros de ordenação); maintenance_work_mem={maintenance_work_mem}.')
        c.execute(f"SET maintenance_work_mem = '{maintenance_work_mem}'")
        # Com lock_timeout ligado, as esperas internas do CONCURRENTLY falhariam e deixariam um índice inválido.
        c.execute('SET statement_timeout = 0')
        c.execute('SET lock_timeout = 0')
        for name in todo:
            started = time.monotonic()
            log(f'  a criar {name}…')
            c.execute(INDEXES[name])
            log(f'  índice {name} pronto ({time.monotonic() - started:.0f}s)')
        state = index_state(c)
        bad = [name for name, ok in state.items() if ok is not True]
        if bad:
            raise RuntimeError('Índice por validar: ' + ', '.join(bad) + '. Apaga com DROP INDEX CONCURRENTLY e repete.')
        c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (GUARD_KEY,))
    log('Índices válidos. A seguir: python scripts/migrate.py apply (regista a sql/050) e depois --execute.')
    return state


def save_record(path, record):
    """Grava o registo de forma atómica (ficheiro temporário + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    os.replace(tmp, path)
    return path


def write_record(record, directory):
    path = Path(directory) / f"raw-retention-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    return save_record(path, record)


# ---------------------------------------------------------------- linha de comando

def _default_dsn():
    sys.path.insert(0, str(ROOT))
    from scripts import audit_readonly  # noqa: F401 - lê o .env antes de importar app
    from app import planning
    return os.environ.get('MES_PG_DSN') or planning.settings.pg_dsn


def main(argv=None, *, log=print, progress=None):
    parser = argparse.ArgumentParser(description='Retenção do histórico RAW do planeamento.')
    parser.add_argument('--keep-days', type=int, default=MIN_KEEP_DAYS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='só conta e mostra (defeito)')
    mode.add_argument('--create-indexes', action='store_true',
                      help='cria os índices de suporte (CREATE INDEX CONCURRENTLY; dono das tabelas)')
    mode.add_argument('--execute', action='store_true', help='apaga em lotes pequenos (exige os índices)')
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH)
    parser.add_argument('--locked-batch-size', type=int, default=DEFAULT_LOCKED_BATCH,
                        help='conteúdos apagados por transação com os locks das publicações (defeito 500)')
    parser.add_argument('--retry-s', type=float, default=DEFAULT_RETRY_S,
                        help='pausa média entre tentativas quando uma publicação segura um lock (defeito 0,25 s)')
    parser.add_argument('--lock-timeout-ms', type=int, default=2000)
    parser.add_argument('--statement-timeout-ms', type=int, default=60000)
    parser.add_argument('--max-wait-s', type=float, default=DEFAULT_MAX_WAIT_S,
                        help='tempo máximo por lote à espera dos locks das publicações (defeito 900)')
    parser.add_argument('--maintenance-work-mem', default='1GB')
    parser.add_argument('--dsn', help='por defeito MES_PG_DSN / .env do projeto')
    parser.add_argument('--log-dir', default=str(ROOT / 'data' / 'raw-retention'))
    args = parser.parse_args(argv)
    if args.keep_days < MIN_KEEP_DAYS:
        parser.error(f'--keep-days tem de ser pelo menos {MIN_KEEP_DAYS}.')
    if not 100 <= args.batch_size <= 20000:
        parser.error('--batch-size entre 100 e 20000.')
    if not 10 <= args.locked_batch_size <= 5000:
        parser.error('--locked-batch-size entre 10 e 5000.')
    if not 0.01 <= args.retry_s <= 10:
        parser.error('--retry-s entre 0,01 e 10.')
    if args.max_wait_s < 0:
        parser.error('--max-wait-s não pode ser negativo.')
    dsn = args.dsn or _default_dsn()
    if args.create_indexes:
        log('Modo --create-indexes.')
        return create_indexes(dsn, maintenance_work_mem=args.maintenance_work_mem, log=log)
    if not args.execute:
        log('Modo só contar (--dry-run): nenhuma escrita; transação READ ONLY.')
        with _connect(dsn, readonly=True) as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            c.execute("SET LOCAL statement_timeout = '1800s'")
            _, _, summary = analyse(c, keep_days=args.keep_days, log=log)
            c.rollback()
        missing = summary['servidor']['missing_indexes']
        log('Passos a seguir:')
        if missing:
            log('  1. python scripts/raw_retention.py --create-indexes --dsn <dono das tabelas>  (num momento calmo)')
            log('  2. python scripts/migrate.py apply  (sql/050 só regista os índices)')
        log('  3. python scripts/raw_retention.py --execute')
        log('  4. Depois, num momento calmo (bloqueia as tabelas durante a cópia): ' + VACUUM_COMMAND)
        return summary
    log('Modo --execute: apaga em lotes de %d linhas por transação.' % args.batch_size)
    path = Path(args.log_dir) / f"raw-retention-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    record = {}

    def emit(current):
        save_record(path, current)
        if progress:
            progress(current)

    log('Registo: ' + str(path))
    try:
        execute(dsn, keep_days=args.keep_days, batch=args.batch_size, lock_timeout=args.lock_timeout_ms,
                statement_timeout=args.statement_timeout_ms, max_wait_s=args.max_wait_s, log=log,
                progress=emit, record=record, locked_batch=args.locked_batch_size, retry_s=args.retry_s)
    finally:
        if record:
            save_record(path, record)
    log(json.dumps(record, ensure_ascii=False, default=str))
    if record['estado'] == 'incompleto':
        log('Ficou INCOMPLETO (havia publicações a correr ou lotes que falharam): repete o --execute mais tarde.')
    log('O espaço só volta ao disco com VACUUM FULL (bloqueia as tabelas; corre à parte, com aviso): ' + VACUUM_COMMAND)
    return record


def cli(argv=None, *, log=print):
    """Código de saída: 0 concluído, 1 recusado (nada apagado), 2 incompleto (repetir o --execute)."""
    try:
        result = main(argv, log=log)
    except RetentionRefused as exc:
        print('Recusado: ' + str(exc), file=sys.stderr)
        return 1
    return 2 if isinstance(result, dict) and result.get('estado') == 'incompleto' else 0


if __name__ == '__main__':
    sys.exit(cli())
