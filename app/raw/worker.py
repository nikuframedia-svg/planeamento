"""Independent RAW worker: python -m app.raw.worker. No operational source writes."""
import os,time,uuid,logging,threading,multiprocessing
from concurrent.futures import ThreadPoolExecutor,ProcessPoolExecutor
from dotenv import load_dotenv
load_dotenv('.env')
from .. import planning
from . import projection,capacity,analysis,workbooks

log=logging.getLogger(__name__)
SOURCE_POLL_SECONDS=1


def source_status(source, *, begin=False, error=None, available=True):
    with planning.connect() as c:
        c.execute("INSERT INTO planning_mtg.raw_worker_state(source) VALUES(%s) ON CONFLICT DO NOTHING",(source,))
        if begin:c.execute("UPDATE planning_mtg.raw_worker_state SET attempted_at=now() WHERE source=%s",(source,))
        else:c.execute("UPDATE planning_mtg.raw_worker_state SET confirmed_at=CASE WHEN %s THEN now() ELSE confirmed_at END,available=%s,error=%s WHERE source=%s",(available,available,error,source))


def refresh_sources():
    def pending(areas=()):
        with planning.connect() as c:
            projection.mark_aggregates_pending(c,str(uuid.uuid4()),source_failures=areas,only_if_needed=True)
    def refresh(name,fn):
        try:
            source_status(name,begin=True);result=fn()
            # The original source must report a published instance, not just a running worker.
            missing=name=='original' and not result
            source_status(name,available=not missing,error='Conector da SQLite original sem publicação confirmada.' if missing else None)
            return not missing
        except Exception as exc:
            log.exception('Could not prepare RAW source %s',name)
            try:source_status(name,error=str(exc) if isinstance(exc,planning.PlanningError) else type(exc).__name__,available=False)
            except Exception:log.exception('Could not publish source failure status')
            return False
    from . import document_dependencies
    if not refresh('documents',document_dependencies.refresh):
        pending(planning.AREAS);return False
    # Each area owns a separate publication lock. Wait for both committed
    # populations before deriving capacities shared between the areas.
    with ThreadPoolExecutor(max_workers=len(planning.AREAS)) as builders:
        futures=[builders.submit(refresh,area,lambda area=area:projection.rebuild(area)) for area in planning.AREAS]
        ready=[future.result() for future in futures]
    if all(ready):
        completed=refresh('capacity',capacity.rebuild)
        if not completed:pending()
        return completed
    pending([area for area,ok in zip(planning.AREAS,ready) if not ok])
    source_status('capacity',available=False,error='Atualização das áreas incompleta; último conjunto de capacidades conservado.')
    return False


def refresh_auxiliary():
    try:
        from . import sku_families
        sku_families.refresh()
    except Exception:log.exception('Could not register new SKU family mappings')
    # Network observations must not delay local edits or central OCR revisions.
    try:workbooks.observe_drive()
    except Exception:log.exception('Drive metadata unavailable; cached observation retained')
    try:
        from . import ocr_export
        ocr_export.refresh()
        source_status('original',begin=True);result=projection.rebuild_original()
        source_status('original',available=bool(result),error=None if result else 'Conector da SQLite original sem publicação confirmada.')
    except Exception as exc:
        log.exception('Could not prepare original OCR source')
        source_status('original',available=False,error=str(exc) if isinstance(exc,planning.PlanningError) else type(exc).__name__)


def tick(worker_id,slots=2):
    with planning.connect() as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended('raw-job-claims',0))")
        c.execute("UPDATE planning_mtg.raw_jobs SET status='queued',worker=NULL WHERE status='running' AND heartbeat_at<now()-interval '3 minutes'")
        for obj in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='analysis' AND NOT archived AND definition->>'automatic'='true' AND definition->>'confirmed'='true'").fetchall():
            try:analysis.queue(c,obj)
            except planning.PlanningError:log.exception('Analysis source unavailable')
        active=c.execute("SELECT count(*) n FROM planning_mtg.raw_jobs WHERE status='running'").fetchone()['n']
        slots=min(slots,max(0,2-active))
        running_gantt=c.execute("SELECT count(*) n FROM planning_mtg.raw_jobs WHERE kind='gantt' AND status='running'").fetchone()['n']
        queued=c.execute("SELECT * FROM planning_mtg.raw_jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s",(max(10,slots*5),)).fetchall()
        jobs=[]
        for candidate in queued:
            if len(jobs)>=slots:break
            if candidate['kind']=='gantt':
                if running_gantt:continue
                running_gantt+=1
            jobs.append(candidate)
        for j in jobs:c.execute("UPDATE planning_mtg.raw_jobs SET status='running',worker=%s,heartbeat_at=now(),attempts=attempts+1 WHERE id=%s",(worker_id,j['id']))
        return jobs


def main():
    from .wakeup import LocalChanges
    load_dotenv('.env');logging.basicConfig(level=logging.INFO)
    worker_id=str(uuid.uuid4());pool=ThreadPoolExecutor(max_workers=2);gantt_pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'));source_pool=ThreadPoolExecutor(max_workers=1);aux_pool=ThreadPoolExecutor(max_workers=1)
    pending={};source_task=None;next_refresh=0;last_signal=None;aux_task=None;next_aux=0
    changes=LocalChanges();changes.wait(0)
    while True:
        try:
            with planning.connect(readonly=True) as c:current_signal=c.execute('SELECT sum(revision) n FROM planning_mtg.raw_signals').fetchone()['n']
            if current_signal!=last_signal:next_refresh=0;last_signal=current_signal
        except Exception:log.exception('Could not read local wake-up signal')
        if time.monotonic()>=next_refresh and (source_task is None or source_task.done()):
            source_task=source_pool.submit(refresh_sources);next_refresh=time.monotonic()+SOURCE_POLL_SECONDS
        if time.monotonic()>=next_aux and (aux_task is None or aux_task.done()):
            aux_task=aux_pool.submit(refresh_auxiliary);next_aux=time.monotonic()+60
        pending={id:f for id,f in pending.items() if not f.done()}
        try:
            with planning.connect() as c:
                if pending:c.execute("UPDATE planning_mtg.raw_jobs SET heartbeat_at=now() WHERE worker=%s AND status='running'",(worker_id,))
            for job in tick(worker_id,2-len(pending)):
                if job['kind']=='gantt':
                    from ..gantt.service import run_job
                    pending[job['id']]=gantt_pool.submit(run_job,job)
                else:pending[job['id']]=pool.submit(analysis.run_job,job)
        except Exception:log.exception('RAW worker cycle failed')
        # A committed configuration/line edit already emits pg_notify. Listen
        # without holding a transaction; the regular poll still covers OCR,
        # dropped connections and notifications received during recalculation.
        urgent=source_task is not None and not source_task.done() and next_refresh==0
        # Central OCR commits do not emit the local planning notification.
        # Bound their detection delay while the calculation remains separate.
        if changes.wait(.1 if urgent else SOURCE_POLL_SECONDS):next_refresh=0

if __name__=='__main__':main()
