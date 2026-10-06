const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict'),{execFileSync,spawn}=require('node:child_process');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
const prefix=process.env.PLANNING_PROOF_PREFIX||'t4-original';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid proof prefix');
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated full clone required');
const mutate=(area,action)=>JSON.parse(execFileSync('.venv/bin/python',['scripts/planning_original_live_trial.py',area,action],{env:{...process.env,PYTHONPATH:'.'},encoding:'utf8'}));
function observe(area,initial,remaining,hours){
 const child=spawn('.venv/bin/python',['scripts/planning_ocr_live_observer.py',area,initial.key,initial.values_before.operation,JSON.stringify(remaining),JSON.stringify(hours)],{env:{...process.env,PYTHONPATH:'.'}});
 let buffer='',resolveReady,resolveResult,rejectResult,error='';
 const ready=new Promise(r=>resolveReady=r),result=new Promise((r,j)=>{resolveResult=r;rejectResult=j});
 child.stdout.on('data',chunk=>{buffer+=chunk;let i;while((i=buffer.indexOf('\n'))>=0){const line=JSON.parse(buffer.slice(0,i));buffer=buffer.slice(i+1);if(line.ready)resolveReady();else resolveResult(line);}});
 child.stderr.on('data',chunk=>error+=chunk);child.on('exit',code=>{if(code)rejectResult(Error(error));});
 return {ready,result};
}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 const report={at:new Date().toISOString(),base,areas:[],errors:[],method:'Synthetic original SQLite publication to open RAW and capacity view without reload; capacity item queried from the same browser. Real worker polling, no direct rebuild call.'};
 try{
  for(const area of ['perfis','cantoneiras']){
   // Fixture cleanup is a distinct publication. Complete it before timing the
   // next source revision, and retain the same 10-second acceptance threshold.
   const settledDeadline=Date.now()+30000;
   while(!mutate(area,'inspect').settled){
    assert(Date.now()<settledDeadline,'Previous isolated fixture publication did not finish');
    await new Promise(resolve=>setTimeout(resolve,250));
   }
   const initial=mutate(area,'inspect'),raw=await browser.newPage({viewport:{width:1600,height:1000}}),cap=await browser.newPage({viewport:{width:1500,height:1000}});
   let capData=null;cap.on('response',async r=>{
    if(r.url().endsWith('/raw/capacidade/consulta')&&r.ok()){
     try{capData=await r.json();}catch(e){if(!cap.isClosed())report.errors.push(e.message);}
    }
   });
   for(const page of [raw,cap])page.on('pageerror',e=>report.errors.push(e.message));
   await raw.goto(base+'/planeamento/raw?area='+area+'&q='+encodeURIComponent(initial.values_before.component_ref));
   await raw.waitForFunction(key=>Raw.state.data?.rows.some(r=>r.key===key),initial.key);
   const columns=['of','ov','component_ref','quantity_required',area==='perfis'?'cut':'made','remaining','theoretical_hours','rate_source','applied_rate_value'];
   const previous=await raw.evaluate(()=>Raw.state.columns);
   await raw.locator('#open-columns').click();
   for(const id of new Set([...previous,...columns])){
    const control=raw.locator('[data-column-control="'+id+':visible"]');
    if(await control.isChecked()===columns.includes(id))continue;
    const group=control.locator('xpath=ancestor::details');
    if(!await group.evaluate(n=>n.open))await group.locator('summary').click();
    await control.setChecked(columns.includes(id));
   }
   await raw.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
   await cap.goto(base+'/planeamento/capacidades?area='+area);await cap.waitForFunction(()=>document.querySelectorAll('#matrix tbody tr').length>0);
   const responseDeadline=Date.now()+10000;
   while(!capData&&Date.now()<responseDeadline)await cap.waitForTimeout(10);
   assert(capData,'The initial capacity response must be captured before mutations');
   const item={area,initial,steps:[]};report.areas.push(item);
   for(const action of ['insert','correct','remove']){
    const capVersion=capData.version,produced=action==='insert'?10:25;
    const remaining=action==='remove'?initial.values_before.remaining:initial.values_before.quantity_required-produced;
    const hours=action==='remove'?initial.values_before.theoretical_hours:area==='perfis'?remaining/20:remaining/produced*(action==='insert'?2:4);
    const observed=observe(area,initial,remaining,hours);await observed.ready;
    const change=mutate(area,action);
    const step={action,change,expected:{remaining,hours}};item.steps.push(step);
    await raw.waitForFunction(({key,remaining})=>Raw.state.data?.rows.find(r=>r.key===key)?.values.remaining===remaining,{key:initial.key,remaining},{timeout:20000});
    step.commitToRawMs=Date.now()-change.committedMs;
    await raw.waitForFunction(({key,hours})=>{const r=Raw.state.data?.rows.find(r=>r.key===key);return r&&((hours==null&&r.values.theoretical_hours==null)||Math.abs(r.values.theoretical_hours-hours)<1e-9)&&!Raw.state.data.aggregates_pending;},{key:initial.key,hours},{timeout:20000});
    while(String(capData.version)===String(capVersion)&&Date.now()-change.committedMs<20000)await cap.waitForTimeout(50);
    assert.notEqual(String(capData.version),String(capVersion));
    const current=await raw.evaluate(async({area,key})=>{
      const r=await fetch('/planeamento/api/raw/consultas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({area,dataset:'capacity_items',selected:[key]})});return r.json();
    },{area,key:initial.key+':'+initial.values_before.operation});
    assert.equal(current.rows.length,1);assert.equal(current.rows[0].values.quantity,remaining);
    if(hours==null)assert.equal(current.rows[0].values.planned_hours,null);else assert(Math.abs(current.rows[0].values.planned_hours-hours)<1e-9);
    step.commitToCapacityMs=Date.now()-change.committedMs;step.publication=await observed.result;
    for(const [name,value] of Object.entries(step.publication.publication))value.commitToObservedMs=value.observedMs-change.committedMs;step.capacityItem=current.rows[0];step.capacityViewVersion=capData.version;
    step.raw=await raw.evaluate(key=>Raw.state.data.rows.find(r=>r.key===key),initial.key);
    step.visible=await raw.evaluate(key=>{
      const row=Raw.state.data.rows.findIndex(r=>r.key===key),fields=['remaining','theoretical_hours','rate_source'];
      return Object.fromEntries(fields.map(field=>[field,document.querySelector('#sheet tbody').rows[row].cells[Raw.state.columns.indexOf(field)].textContent]));
    },initial.key);
    const number=text=>Number(text.replace(/\s/g,'').replace(',','.'));
    if(remaining==null)assert.equal(step.visible.remaining,'—');else assert.equal(number(step.visible.remaining),remaining);
    if(hours==null)assert.equal(step.visible.theoretical_hours,'—');else assert(Math.abs(number(step.visible.theoretical_hours)-hours)<=.000051);
    assert.equal(step.visible.rate_source,step.raw.values.rate_source||'—');
    step.commitToVisibleMs=Date.now()-change.committedMs;
    if(area==='cantoneiras'&&action!=='remove'){assert.equal(step.raw.values.rate_source,'Histórico');assert.equal(step.raw.values.applied_rate_value,produced*.15/(action==='insert'?2:4));}
    console.log(area,action,Math.round(step.commitToRawMs),Math.round(step.commitToCapacityMs));
    if(action==='correct')await raw.screenshot({path:folder+'/'+prefix+'-'+area+'-ocr-live.png',fullPage:true});
    fs.writeFileSync(folder+'/'+prefix+'-ocr-incremental-browser.json',JSON.stringify(report,null,2));
   }
   await raw.close();await cap.close();
   mutate(area,'cleanup');
  }
  report.timing_failures=report.areas.flatMap(item=>item.steps.filter(step=>step.commitToRawMs>10000||step.commitToCapacityMs>10000||step.commitToVisibleMs>10000).map(step=>({area:item.area,action:step.action,rawMs:step.commitToRawMs,capacityMs:step.commitToCapacityMs,visibleMs:step.commitToVisibleMs})));
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.timing_failures,[]);report.result='passed';
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/'+prefix+'-ocr-incremental-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
