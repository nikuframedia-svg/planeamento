from pathlib import Path
import json,os,signal,subprocess,time,urllib.request
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
old=json.loads((folder/'c02-source-policy-server.json').read_text())['pid']
cmd=Path(f'/proc/{old}/cmdline').read_bytes().split(b'\0')
assert b'app.web.planning_app:app' in cmd and b'18113' in cmd
config=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())
env=dict(e.decode().split('=',1) for e in Path(f'/proc/{old}/environ').read_bytes().split(b'\0') if b'=' in e)
assert env['MES_PG_DSN']==config['dsn']
assert env['MES_DATA_DIR']=='/tmp/planning-integral-data'
assert env['MES_DOSSIER_WORKER_DISABLED']=='1'
os.kill(old,signal.SIGTERM)
for _ in range(100):
 if not Path(f'/proc/{old}').exists():break
 time.sleep(.1)
else:raise RuntimeError('Old isolated process still present; not starting replacement')
with (folder/'c02-removed-evidence-server.log').open('ab') as log:
 p=subprocess.Popen([str(Path('.venv/bin/python').absolute()),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port','18113'],env=env,stdout=log,stderr=log,start_new_session=True)
for _ in range(100):
 try:
  assert urllib.request.urlopen('http://127.0.0.1:18113/planeamento',timeout=2).status==200
  break
 except Exception:
  assert p.poll() is None
  time.sleep(.2)
else:raise RuntimeError('New isolated process not ready')
(folder/'c02-removed-evidence-server.json').write_text(json.dumps({'previous_pid':old,'pid':p.pid,'port':18113},indent=2)+'\n')
print('Isolated planning server ready:',p.pid)
