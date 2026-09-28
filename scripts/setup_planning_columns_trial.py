"""Seed two old-format views only in the isolated planning copy for C07."""
import json
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from psycopg.types.json import Jsonb

FOLDER = Path('docs/validacao-planeamento-integral/20260923-execucao')


def main():
    target = FOLDER/'c07-complete-fixture.json'
    if target.exists():
        raise SystemExit('Fixture already exists; preserve it and reuse its IDs.')
    os.environ['MES_PG_DSN'] = json.loads(Path(
        '/home/luis/.local/state/planning-backups/integral-20260923/isolated.json'
    ).read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    result = {'at':datetime.now(timezone.utc).isoformat(), 'environment':'isolated planning_integral', 'views':{}}
    with planning.connect() as c:
        assert c.execute('SELECT current_database() n').fetchone()['n'] == 'planning_integral'
        result['sources_before'] = source_fingerprints(c)
        result['generations'] = {area:query.generation(c,area)['id'] for area in planning.AREAS}
        for area in planning.AREAS:
            id = str(uuid4()); name = 'C07 legacy fixture '+area
            definition = {'hidden_groups':['technical'], 'filters':{'state':'open'},
                          'widths':{'of':177}, 'sort':'of', 'direction':'desc'}
            c.execute("""INSERT INTO planning_mtg.raw_objects
                (id,kind,name,area,revision,definition,archived,actor)
                VALUES(%s,'view',%s,%s,1,%s,false,'C07 isolated fixture')""",
                (id,name,area,Jsonb(definition)))
            c.execute("""INSERT INTO planning_mtg.raw_object_versions
                (object_id,revision,definition,name,archived,actor)
                VALUES(%s,1,%s,%s,false,'C07 isolated fixture')""", (id,Jsonb(definition),name))
            result['views'][area] = {'id':id,'name':name,'raw_definition':definition}
        assert source_fingerprints(c) == result['sources_before']
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('Two isolated legacy views created; production sources and planning pieces unchanged.')


if __name__ == '__main__':
    main()
