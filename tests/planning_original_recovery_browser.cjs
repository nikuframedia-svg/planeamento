const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated full clone required');
const run=(script,...args)=>JSON.parse(execFileSync('.venv/bin/python',[script,...args],{env:{...process.env,PYTHONPATH:'.'},encoding:'utf8'}));
const mutate=action=>run('scripts/planning_original_live_trial.py','perfis',action);
const worker=action=>run('/tmp/manage_planning_isolated.py','worker',action);
async function settled(){const end=Date.now()+30000;while(!mutate('inspect').settled){assert(Date.now()<end);await new Promise(r=>setTimeout(r,200));}}
(async()=>{
 await settled();const initial=mutate('inspect');
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 const report={at:new Date().toISOString(),base,errors:[],initial,method:'Stop isolated worker, publish original revision, inspect pending source in browser, restart worker, observe existing RAW without reload.'};
 try{
  const raw=await browser.newPage(),source=await browser.newPage();
  for(const p of [raw,source])p.on('pageerror',e=>report.errors.push(e.message));
  await raw.goto(base+'/planeamento/raw?area=perfis&q='+initial.values_before.component_ref);
  await raw.waitForFunction(key=>Raw.state.data?.rows.some(r=>r.key===key),initial.key);
  report.stopped=worker('stop');report.publication=mutate('insert');
  await source.goto(base+'/planeamento/ocr-original');
  await source.waitForFunction(()=>document.querySelector('#source')?.textContent.includes('Revisão atual ainda não aplicada'));
  report.pending=await (await source.request.get(base+'/planeamento/api/ocr-original/registos')).json();
  assert.equal(report.pending.source.included_in_planning_balances,false);
  assert(report.pending.records[0].planning.every(p=>p.state==='pending_publication'));
  assert.equal(await raw.evaluate(key=>Raw.state.data.rows.find(r=>r.key===key).values.remaining,initial.key),initial.values_before.remaining);
  await source.screenshot({path:folder+'/t4-worker-stopped-original.png',fullPage:true});
  report.restarted=worker('start');const restartedAt=Date.now();
  await raw.waitForFunction(key=>{const r=Raw.state.data?.rows.find(r=>r.key===key);return r?.values.remaining===32&&Math.abs(r.values.theoretical_hours-1.6)<1e-9&&!Raw.state.data.aggregates_pending;},initial.key,{timeout:15000});
  report.restartToVisibleMs=Date.now()-restartedAt;assert(report.restartToVisibleMs<=10000);
  report.applied=await (await source.request.get(base+'/planeamento/api/ocr-original/registos')).json();
  assert.equal(report.applied.source.included_in_planning_balances,true);
  mutate('remove');await settled();
  await raw.waitForFunction(({key,remaining})=>Raw.state.data?.rows.find(r=>r.key===key)?.values.remaining===remaining,{key:initial.key,remaining:initial.values_before.remaining});
  mutate('cleanup');await settled();
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.failure=e.stack;report.result='failed';throw e}
 finally{fs.writeFileSync(folder+'/t4-original-worker-recovery.json',JSON.stringify(report,null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
