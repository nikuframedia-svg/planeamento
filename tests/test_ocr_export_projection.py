"""Exportação do OCR (07/10/2026): uma versão nova só regrava as linhas que mudaram.

A versão da exportação muda a cada ~3 minutos nos dias úteis. Ela fica nos
metadados da geração; o conteúdo de cada linha não a repete, nem repete a
posição da linha no ficheiro (muda sempre que entra uma linha acima).
"""
import psycopg
from psycopg.rows import dict_row

from app import planning
from app.raw import ocr_export, projection, research_sync
from tests.test_data_integration import free_workspace, workbook
from tests.test_planning_integral_registration import local_workspace, workspace, database, canonical, registry, postgres16

URL = 'http://test/export'
ROWS = [['2026-09-29', 'OF42', 'X', 10, 'M1', 1000],
        ['2026-09-28', 'OF43', 'Y', 5, 'M2', 2000],
        ['2026-09-27', 'OF44', 'Z', 7, 'M3', 3000],
        ['2026-09-26', 'OF45', 'W', 3, 'M4', 4000]]


def export(dsn, rows):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        return ocr_export.publish(c, ocr_export.parse(workbook(rows)), URL)


def counts(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        return c.execute("""SELECT
            (SELECT count(*) FROM planning_mtg.raw_contents) contents,
            (SELECT count(*) FROM planning_mtg.raw_members WHERE dataset='original:perfis') members,
            (SELECT count(*) FROM planning_mtg.raw_members WHERE dataset='original:perfis' AND last_generation IS NULL) current,
            (SELECT count(*) FROM planning_mtg.raw_generations WHERE dataset LIKE 'original:%%') original_generations,
            (SELECT count(*) FROM planning_mtg.raw_generations WHERE dataset NOT LIKE 'original:%%') other_generations""").fetchone()


def test_new_export_version_rewrites_only_the_changed_row(free_workspace, postgres16):
    dsn = postgres16[0]
    downstream = {area: projection.rebuild(area)['id'] for area in planning.AREAS}
    first = export(dsn, ROWS)
    assert projection.rebuild_original()['rows'] == 4
    before = counts(dsn)
    assert before['current'] == 4

    # Mesmo ficheiro com uma linha alterada, agora no topo: as outras três mudam de posição.
    changed = ['2026-09-28', 'OF43', 'Y', 6, 'M2', 2000]
    second = export(dsn, [changed, ROWS[0], ROWS[2], ROWS[3]])
    assert second['version'] != first['version'] and not second['unchanged']
    projection.rebuild_original()
    after = counts(dsn)
    assert after['contents'] - before['contents'] == 1      # só a linha alterada tem conteúdo novo
    assert after['members'] - before['members'] == 1        # e só ela entra na nova geração
    assert after['current'] == 4
    assert after['original_generations'] - before['original_generations'] == 2   # uma por área
    assert after['other_generations'] == before['other_generations']

    with psycopg.connect(dsn, row_factory=dict_row) as c:
        for area in planning.AREAS:
            gen = c.execute('SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1',
                            ('original:' + area,)).fetchone()
            assert gen['metadata']['export_version'] == second['version']
            assert gen['row_count'] == 4
        details = [r['detail'] for r in c.execute("""SELECT c.detail FROM planning_mtg.raw_members m
            JOIN planning_mtg.raw_contents c ON c.hash=m.content_hash
            WHERE m.dataset='original:perfis' AND m.last_generation IS NULL""")]
        assert not any('source_export' in d for d in details)
        # A posição na exportação continua disponível na própria exportação (página OCR original).
        lines = {r['data']['of']: r['export_line'] for r in ocr_export.query(c, ocr_export.status(c))['records']}
        assert lines == {'OF43': 2, 'OF42': 3, 'OF44': 4, 'OF45': 5}

    # A mesma versão outra vez não cria geração nenhuma nem volta a ler a exportação.
    assert export(dsn, [changed, ROWS[0], ROWS[2], ROWS[3]])['unchanged']
    assert projection.rebuild_original() == {'rows': 4, 'mode': 'validated_export', 'unchanged': True}
    assert counts(dsn) == after

    # Nada a jusante depende da exportação: planeamento, produção e capacidades ficam como estavam.
    assert {area: projection.rebuild(area)['id'] for area in planning.AREAS} == downstream


def test_research_mirror_skips_an_unchanged_export(free_workspace, postgres16):
    export(postgres16[0], ROWS)
    for area in planning.AREAS:
        projection.rebuild(area)
    with planning.connect(readonly=True) as source, psycopg.connect(postgres16[0], row_factory=dict_row) as dest:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        for package in research_sync.packages(source):
            research_sync.publish(dest, *package)
        known = {r['conjunto']: r['metadata'] for r in dest.execute('''SELECT f.conjunto,v.metadata
            FROM origem_v2.aplicacao_fontes f JOIN origem_v2.aplicacao_versoes v ON v.id=f.versao''').fetchall()}
        assert dest.execute("SELECT count(*) n FROM consulta_v2.ocr_original_atual WHERE conjunto='ocr:validated_export'").fetchone()['n'] == 4
        assert 'ocr:validated_export' not in [name for name, _, _ in research_sync.packages(source, known)]
