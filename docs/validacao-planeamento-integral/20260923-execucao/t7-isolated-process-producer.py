from pathlib import Path
import json,os,subprocess,sys,signal,time,urllib.request
f=Path('docs/validacao-planeamento-integral/20260923-execucao')
config=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())
kind,action=sys.argv[1:]
assert kind in ['server','worker'] and action in ['start','stop','restart']
state=f/('t7-current-server.json' if kind=='server' else 't4-original-worker.json')
data=json.loads(state.read_text())
server=json.loads((f/'t7-current-server.json').read_text())
env=dict(e.decode().split('=',1) for e in Path(f"/proc/{server['pid']}/environ").read_bytes().split(b'\0') if b'=' in e)
assert env['MES_PG_DSN']==config['dsn'] and env['MES_DATA_DIR']=='/tmp/planning-integral-data'
pid=data['pid']
if action in ['stop','restart']:
 assert Path(f'/proc/{pid}').exists()
 cmd=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
 assert (b'app.raw.worker' if kind=='worker' else b'app.web.planning_app:app') in cmd
 assert ('MES_PG_DSN='+config['dsn']).encode() in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
 if kind=='server':assert b'18113' in cmd
 os.kill(pid,signal.SIGTERM)
 for _ in range(100):
  if not Path(f'/proc/{pid}').exists():break
  time.sleep(.1)
 else:raise RuntimeError('Isolated process did not stop')
 data['stopped']=True
 state.write_text(json.dumps(data,indent=2)+'\n')
if action in ['start','restart']:
 assert not Path(f'/proc/{pid}').exists()
 args=['-m','app.raw.worker'] if kind=='worker' else ['-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port','18113']
 with (f/('t4-original-worker.log' if kind=='worker' else 't7-current-server.log')).open('ab') as log:
  p=subprocess.Popen([str(Path('.venv/bin/python').absolute()),*args],env=env,stdout=log,stderr=log,start_new_session=True)
 data.update(previous_pid=pid,pid=p.pid,stopped=False)
 state.write_text(json.dumps(data,indent=2)+'\n')
 if kind=='server':
  for _ in range(100):
   try:urllib.request.urlopen('http://127.0.0.1:18113/planeamento',timeout=2);break
   except Exception:time.sleep(.1)
print(json.dumps({'kind':kind,'action':action,'pid':data['pid']}))
