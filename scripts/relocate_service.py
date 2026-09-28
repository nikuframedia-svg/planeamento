"""One-time, backed-up relocation from the prepared Planning project.

Uses Linux rename exchange so compatibility paths remain available atomically.
The PostgreSQL database is never modified by this script.
"""
import ctypes,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/separacao-2026-09-24'


def main():
    state=json.loads((OUT/'migration.json').read_text())
    assert state['stage']=='prepared',state['stage']
    old=Path(state['old_root']);backup=Path(state['backup']);units=['kanban-planning.service','kanban-raw-worker.service']
    assert json.loads((OUT/'before.json').read_text())['result']=='passed'
    assert json.loads((OUT/'staged-http.json').read_text())['result']=='passed'
    test_log=(OUT/'final-relocation-tests.log').read_text()
    assert '33 passed' in test_log and 'failed' not in test_log,test_log[-500:]
    assert os.stat(old).st_dev==os.stat(ROOT).st_dev==os.stat(backup).st_dev
    # Preserve all pre-existing tracked edits, even outside the extracted files.
    paths=subprocess.check_output(['git','diff','--name-only'],cwd=old,text=True).splitlines()
    state['preexisting_tracked']={p:hashlib.sha256((old/p).read_bytes()).hexdigest() for p in paths if (old/p).is_file()}
    for p in state['compatibility_candidates']:
        assert hashlib.sha256((old/p).read_bytes()).hexdigest()==state['copied_files'][p],('source_changed_after_copy',p)
    for p,digest in state['runtime_files'].items():
        assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest,('runtime_changed',p)
    libc=ctypes.CDLL(None,use_errno=True)
    def exchange(a,b):
        if libc.renameat2(-100,os.fsencode(a),-100,os.fsencode(b),2):
            error=ctypes.get_errno();raise OSError(error,os.strerror(error),str(a))
    # Check the atomic primitive before touching either service.
    a=OUT/'.exchange-test-a';b=OUT/'.exchange-test-b';a.write_text('ok');b.symlink_to(b)
    exchange(a,b);assert a.read_text()=='ok';a.unlink();b.unlink()
    grouped=[Path('app/raw'),Path('app/dossiers'),Path('deploy/raw-connectors')]
    grouped.extend(p.relative_to(old) for p in (old/'docs').iterdir() if p.is_dir() and
                   any(name.startswith(str(p.relative_to(old))+'/') for name in state['compatibility_candidates']))
    covered=set();transfers=[]
    for p in grouped:
        entries=[name for name in state['compatibility_candidates'] if name.startswith(str(p)+'/')]
        assert entries and (ROOT/p).is_dir(),p
        tracked=subprocess.check_output(['git','ls-files','--',str(p)],cwd=old,text=True).strip()
        assert not tracked,('shared_directory',p)
        transfers.append(p);covered.update(entries)
    transfers.extend(Path(p) for p in state['compatibility_candidates'] if p not in covered)
    runtime={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
             for folder in ['app','sql'] for p in sorted((ROOT/folder).rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    for name in ['pyproject.toml','uv.lock','deploy/kanban-planning.service','deploy/kanban-raw-worker.service']:
        runtime[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    candidate=hashlib.sha256(json.dumps(runtime,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (OUT/'runtime-manifest.json').write_text(json.dumps({'candidate':candidate,'files':runtime,
        'origin_candidate':'3800fea868fea5cce87b714e48a2e7d18cb4d2d2bc2a48f6bcfbb7561b08ca0c',
        'runtime_code_unchanged':len(state['runtime_files'])},indent=2)+'\n')
    state.update(candidate=candidate,transferred_paths=[],cutover_started_at=datetime.now(timezone.utc).isoformat())
    def save():
        (OUT/'migration.json').write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n')
        (backup/'migration.json').write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n')
    save()
    subprocess.run(['systemctl','--user','stop',*units],check=True)
    try:
        documents=old/'data/dossiers';new_documents=ROOT/'data/dossiers';locks=[]
        try:
            for name in ['worker.lock','inbox.lock']:
                lock=(documents/name).open('a');deadline=time.monotonic()+15
                while True:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
                locks.append(lock)
            with sqlite3.connect((documents/'dossiers.db').resolve().as_uri()+'?mode=ro',uri=True) as c:
                assert not c.execute("SELECT 1 FROM documents WHERE status IN ('queued','indexing','extracting','matching') LIMIT 1").fetchone()
                with sqlite3.connect(backup/'dossiers-before.sqlite3') as target:c.backup(target)
            os.chmod(backup/'dossiers-before.sqlite3',0o600)
            with sqlite3.connect(documents/'dossiers.db',timeout=20) as c:
                c.execute('BEGIN IMMEDIATE')
                os.rename(new_documents,backup/'staging-documents')
                new_documents.symlink_to(new_documents,target_is_directory=True)
                exchange(documents,new_documents)
                assert documents.resolve()==new_documents and new_documents.is_dir()
                c.rollback()
            state['documents_moved_atomically']=True;save()
        finally:
            for lock in locks:lock.close()
        for rel in transfers:
            source=old/rel;target=ROOT/rel;archived=backup/'legacy-tree'/rel
            archived.parent.mkdir(parents=True,exist_ok=True)
            link=source.with_name(source.name+'.planning-relocation-link');assert not link.exists()
            # StaticFiles deliberately rejects symlinks outside its root. Keep
            # the legacy MES static mount working with the same file inode.
            if str(rel).startswith('app/web/static/'):
                os.link(target,link)
            else:
                link.symlink_to(target,target_is_directory=source.is_dir())
            exchange(source,link);os.rename(link,archived)
            state['transferred_paths'].append(str(rel))
        url=old/'data/planning_tunnel_url.txt'
        if url.is_file():shutil.copy2(url,ROOT/'data/planning_tunnel_url.txt')
        for unit in units:
            dest=Path.home()/'.config/systemd/user'/unit
            shutil.copy2(ROOT/'deploy'/unit,dest)
            conf=dest.with_name(unit+'.d')/'candidate.conf'
            conf.write_text('[Service]\nEnvironment=PLANNING_CANDIDATE_ID='+candidate+'\n')
        state['stage']='relocated';save()
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','start',*units],check=True)
        state['services_started_at']=datetime.now(timezone.utc).isoformat();save()
        print('Moved project and live document directory; started both services from',ROOT,flush=True)
        print('Candidate',candidate,'compatibility paths',len(transfers),flush=True)
    except Exception:
        # Existing paths still resolve via compatibility links after an exchange;
        # the former processes can safely be restarted without discarding data.
        for unit in units:
            dest=Path.home()/'.config/systemd/user'/unit
            shutil.copy2(backup/(unit+'.before'),dest)
            shutil.copy2(backup/(unit+'.d')/'candidate.conf',dest.with_name(unit+'.d')/'candidate.conf')
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','start',*units],check=True)
        state['stage']='cutover_failed_previous_service_configuration_restored';save();raise


if __name__=='__main__':main()
