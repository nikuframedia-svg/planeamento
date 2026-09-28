// C09: independent H01-H08 expectations and real UI edits, full isolated copy.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated Planeamento required');
const prefix=process.env.PLANNING_CHECK_PREFIX||'c09-complete-browser';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid prefix');
const fixture=JSON.parse(fs.readFileSync(folder+'/c03-complete-run.json'));
const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),areas:{},errors:[],result:'running'};
// A screenshot failure after completed assertions need not repeat committed edits.
const resume=process.env.PLANNING_CHECK_RESUME;
if(resume){
 if(!/^[a-z0-9-]+$/.test(resume))throw Error('Invalid resume proof');
 const bytes=fs.readFileSync(folder+'/'+resume+'.json'),prior=JSON.parse(bytes);
 assert.equal(prior.result,'failed');assert(prior.error.startsWith('page.screenshot: Timeout'));
 for(const [area,item] of Object.entries(prior.areas)){
  assert.equal(item.steps.length,11);assert.equal(item.rejected.length,4);report.areas[area]=item;
 }
 assert.deepEqual(prior.errors,[]);
 report.resumed_source={file:resume+'.json',sha256:crypto.createHash('sha256').update(bytes).digest('hex'),script_sha256:prior.script_sha256,reason:'Capture failed after completed numerical, persistence and rejection assertions; recheck current state before resuming capture.'};
}
const close=(a,b)=>{if(b===null)assert.equal(a,null);else assert(typeof a==='number'&&Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-8),`${a} != ${b}`);};
const labels={calendar:'Calendários',rate:'Parâmetros',worked_hours:'Horas reais',resource:'Máquinas físicas'};
let browser;
async function capture(page,name){
 console.log('Capturing '+name);await page.bringToFront();
 const cdp=await page.context().newCDPSession(page);let timer;
 try{const result=await Promise.race([cdp.send('Page.captureScreenshot',{captureBeyondViewport:false}),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Native capture exceeded 30s: '+name)),30000);})]);fs.writeFileSync(folder+'/'+name+'.png',Buffer.from(result.data,'base64'));}
 finally{clearTimeout(timer);await cdp.detach();}
}
async function objects(page,kind){const r=await page.request.get(base+'/planeamento/api/raw/objects/'+kind);assert.equal(r.status(),200);return (await r.json()).items;}
async function open(editor,kind,name){
 await editor.locator('#panel-body').getByRole('button',{name:labels[kind],exact:true}).click();
 const prior=(await objects(editor,kind)).find(x=>x.name===name);
 await editor.locator('#panel-body').getByRole('button',{name:prior?name:'Adicionar',exact:true}).click();
 const edit=editor.locator('#edit-panel');await edit.waitFor({state:'visible'});
 return {edit,prior};
}
async function set(edit,label,value){const node=edit.getByLabel(label,{exact:false});if(await node.evaluate(n=>n.tagName)==='SELECT')await node.selectOption(String(value));else await node.fill(String(value));}
async function save(editor,kind){
 const start=Date.now(),pending=editor.waitForResponse(r=>r.url().endsWith('/raw/objects/'+kind)&&r.request().method()==='POST');
 await editor.locator('#save-config').click();const response=await pending,returned=Date.now(),body=await response.json();assert.equal(response.status(),200,JSON.stringify(body));
 await editor.locator('#edit-panel').waitFor({state:'hidden'});
 const request=response.request().postDataJSON();
 const replay=await editor.request.post(base+'/planeamento/api/raw/objects/'+kind,{data:request});assert.equal(replay.status(),200);assert.deepEqual(await replay.json(),body);
 const hist=await editor.request.get(base+'/planeamento/api/raw/objects/'+body.id+'/historico');const history=(await hist.json()).versions;
 assert.equal(history[0].revision,body.revision);assert.equal(history.filter(x=>x.revision===body.revision).length,1);
 assert.deepEqual(history[0].definition,body.definition);
 return {request,response:body,request_ms:returned-start,returned,history};
}
async function results(watch,raw,area,entry,name,settings,saved){
 const rate=settings.method==='minutes_unit'?60/settings.rate:settings.rate;
 const available=settings.shifts*settings.hours-settings.exception,load=23/rate,free=available-load;
 const expected={available_hours:available,planned_hours:load,free_hours:free,occupancy:available>0?100*load/available:null,
  equivalent_shifts:load/settings.hours,capacity_total:available*rate,capacity_free:free*rate,lines_total:2,pending_quantity:23};
 if(settings.actual!==undefined)expected.actual_hours=settings.actual;
 // Observe responses used by the open page; do not refresh or replace its state.
 const marker=saved?{id:saved.response.id,revision:saved.response.revision,kind:saved.request.definition.method?'rate':saved.request.definition.hours!==undefined?'worked_hours':'calendar'}:null;
 await watch.waitForFunction(({expected,marker,method,rate})=>{
  const r=window.__c09Capacity?.rows?.[0];if(!r)return false;
  if(!r.rates.some(x=>x.definition.method===method&&x.definition.value===rate))return false;
  if(marker){
   const items=marker.kind==='rate'?r.rates:marker.kind==='calendar'?r.calendars:r.actual_evidence;
   if(!items.some(x=>(x.id===marker.id||x.key==='manual:'+marker.id)&&x.revision===marker.revision))return false;
  }
  return Object.entries(expected).every(([k,v])=>v===null?r.values[k]===null:typeof r.values[k]==='number'&&Math.abs(r.values[k]-v)<=Math.max(1e-6,Math.abs(v)*1e-8));
 },{expected,marker,method:settings.method,rate:settings.rate},{timeout:20000});
 await raw.waitForFunction(({ids,rate,occupancy})=>{
  const data=Raw.state.data;if(data?.aggregates_pending)return false;
  return ids.every((id,i)=>{const v=data.rows.find(x=>x.need_id===id)?.values;return v&&Math.abs(v.theoretical_hours-(i===0?15:8)/rate)<1e-8&&(occupancy===null?v.hours_pct===null:Math.abs(v.hours_pct-occupancy)<1e-8);});
 },{ids:entry.pieces.map(p=>p.id),rate,occupancy:expected.occupancy},{timeout:20000});
 const visible=Date.now();
 const values=await watch.evaluate(()=>window.__c09Capacity.rows[0].values);
 for(const [k,v] of Object.entries(expected))close(values[k],v);
 const shown=await watch.locator('#matrix tbody tr').first().locator('td').allTextContents();
 // The exact values are independently checked above; compare the actual table's
 // display rounding with those values, not a hidden cache or API alone.
 const format=n=>n==null?'Por confirmar':new Intl.NumberFormat('pt-PT',{maximumFractionDigits:2}).format(n);
 for(const [index,key] of [[1,'available_hours'],[4,'planned_hours'],[5,'free_hours'],[6,'occupancy']])assert.equal(shown[index],format(expected[key]),key);
 if(settings.actual!==undefined)assert.equal(shown[7],format(settings.actual),'actual hours visible');
 const responseToVisible=saved?visible-saved.returned:null;
 if(saved)assert(responseToVisible<=10000,`${name}: propagation ${responseToVisible}ms > 10s`);
 const response=await watch.request.post(base+'/planeamento/api/raw/capacidade/consulta',{data:{area,mode:'weekly',year:2027,week:1,q:'C05 Ensaio '+area+' 1'}});
 assert.equal(response.status(),200);const api=await response.json();assert.equal(api.rows.length,1);
 for(const [k,v] of Object.entries(expected))close(api.rows[0].values[k],v);
 return {name,settings:{...settings},expected,values,shown,api,row:api.rows[0],saved,response_to_visible_ms:responseToVisible};
}
(async()=>{
 browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 for(const [area,entry] of Object.entries(fixture.areas)){
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  const editor=await context.newPage(),watch=await context.newPage(),raw=await context.newPage();
  for(const p of [editor,watch,raw]){p.setDefaultTimeout(20000);p.on('pageerror',e=>report.errors.push({area,message:e.message}));}
  await watch.addInitScript(()=>{const original=window.fetch;window.fetch=async(...args)=>{const r=await original(...args);if(String(args[0]).includes('/raw/capacidade/consulta')){try{window.__c09Capacity=await r.clone().json();}catch{}}return r;};});
  const completed=report.areas[area];const item=report.areas[area]=completed||{steps:[],rejected:[]};
  const name='C05 Ensaio '+area+' 1';
  await watch.goto(base+'/planeamento/disponibilidade?area='+area);await watch.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
  await watch.locator('#search').fill(name);await watch.locator('#year').fill('2027');await watch.locator('#week').fill('1');await watch.getByRole('button',{name:'Consultar',exact:true}).click();
  await watch.waitForFunction(name=>document.querySelector('#matrix tbody tr')?.textContent.includes(name)&&document.querySelectorAll('#matrix tbody tr').length===1,name);
  await raw.goto(base+'/planeamento/raw?area='+area+'&q='+entry.order);await raw.waitForFunction(()=>Raw.state.data?.rows.length===2);
  // Follow the user-visible entry point from RAW to settings.
  await editor.goto(base+'/planeamento/raw?area='+area);await editor.locator('#capacity').click();await editor.locator('#configure').click();
  let settings={shifts:2,hours:7.5,exception:1,method:'units_hour',rate:area==='perfis'?10:20};
  if(!completed){
  // Reset test-owned configuration through the same editor, making reruns safe.
  let opened=await open(editor,'calendar',name+' W1');
  for(const [label,v] of [['Turnos na semana',2],['Horas por turno',7.5],['Horas indisponíveis / exceções',1]])await set(opened.edit,label,v);
  item.reset_calendar=await save(editor,'calendar');
  opened=await open(editor,'rate',name+' taxa');await set(opened.edit,'Método e unidade','units_hour');await set(opened.edit,'Taxa / valor',settings.rate);item.reset_rate=await save(editor,'rate');
  item.steps.push(await results(watch,raw,area,entry,'baseline',settings,null));
  const changes=[['turnos','calendar',{'Turnos na semana':3},{shifts:3}],['horas_turno','calendar',{'Horas por turno':6},{hours:6}],
   ['indisponibilidade','calendar',{'Horas indisponíveis / exceções':2},{exception:2}],['taxa','rate',{'Taxa / valor':settings.rate*2},{rate:settings.rate*2}],
   ['minutos_unidade','rate',{'Método e unidade':'minutes_unit','Taxa / valor':4},{method:'minutes_unit',rate:4}],
   ['zero_disponivel','calendar',{'Turnos na semana':0,'Horas indisponíveis / exceções':0},{shifts:0,exception:0}],
   ['sobrecarga','calendar',{'Turnos na semana':1,'Horas por turno':.6},{shifts:1,hours:.6}],['repor_disponibilidade','calendar',{'Turnos na semana':3,'Horas por turno':6,'Horas indisponíveis / exceções':2},{shifts:3,hours:6,exception:2}]];
  for(const [step,kind,fields,patch] of changes){
   opened=await open(editor,kind,name+(kind==='calendar'?' W1':' taxa'));
   for(const [label,v] of Object.entries(fields))await set(opened.edit,label,v);
   const saved=await save(editor,kind);settings={...settings,...patch};
   item.steps.push(await results(watch,raw,area,entry,step,settings,saved));
   fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));
  }
  const resource=(await objects(editor,'resource')).find(x=>x.name===name);assert(resource);
  const hoursName='C09 Completo horas '+area;
  for(const actual of [7,6]){
   opened=await open(editor,'worked_hours',hoursName);
   await set(opened.edit,'Nome',hoursName);await set(opened.edit,'Máquina física',resource.id);
   await set(opened.edit,'Âmbito das horas','period');await set(opened.edit,'Desde','2027-01-04');await set(opened.edit,'Até (mesma semana ISO)','2027-01-10');
   await set(opened.edit,'Horas reais (h)',actual);await set(opened.edit,'Origem / justificação','Ensaio C09 na cópia isolada, não é uma declaração real de fábrica.');
   await opened.edit.getByLabel('Confirmo as horas reais',{exact:false}).check();
   await opened.edit.getByRole('button',{name:'Conferir declarações',exact:true}).click();
   await opened.edit.getByText('Sem declarações OCR neste âmbito.',{exact:true}).waitFor();
   const saved=await save(editor,'worked_hours');settings.actual=actual;
   item.steps.push(await results(watch,raw,area,entry,'horas_reais_'+actual,settings,saved));
  }
  // Reopen all edited definitions, with an entirely new page load.
  await editor.reload();await editor.locator('#configure').click();
  for(const [kind,n,fields] of [['calendar',name+' W1',{'Turnos na semana':'3','Horas por turno':'6','Horas indisponíveis / exceções':'2'}],['rate',name+' taxa',{'Método e unidade':'minutes_unit','Taxa / valor':'4'}],['worked_hours',hoursName,{'Horas reais (h)':'6'}]]){
   opened=await open(editor,kind,n);for(const [label,v] of Object.entries(fields))assert.equal(await opened.edit.getByLabel(label,{exact:false}).inputValue(),v);
   editor.once('dialog',async dialog=>{assert.equal(dialog.message(),'Descartar as alterações deste formulário?');await dialog.accept();});
   await editor.locator('#cancel-edit').click();await opened.edit.waitFor({state:'hidden'});
  }
  // Atomic rejection, stale revision and invalid dimensional method.
  for(const [kind,n,patch] of [['calendar',name+' W1',{exception_hours:999}],['rate',name+' taxa',{method:'kg_hour'}]]){
   const prior=(await objects(editor,kind)).find(o=>o.name===n);const priorHistory=await (await editor.request.get(base+'/planeamento/api/raw/objects/'+prior.id+'/historico')).json();
   for(const stale of [false,true]){
    const payload={request_id:crypto.randomUUID(),id:prior.id,expected_revision:prior.revision-(stale?1:0),name:prior.name,area:prior.area,definition:{...prior.definition,...(stale?{}:patch)}};
    const r=await editor.request.post(base+'/planeamento/api/raw/objects/'+kind,{data:payload});assert.equal(r.status(),stale?409:422);
    item.rejected.push({kind,stale,status:r.status(),body:await r.json()});
    assert.deepEqual((await objects(editor,kind)).find(o=>o.id===prior.id),prior);
    assert.deepEqual(await (await editor.request.get(base+'/planeamento/api/raw/objects/'+prior.id+'/historico')).json(),priorHistory);
   }
  }
  }else{
   settings={...item.steps.at(-1).settings};
   item.resume_validation=await results(watch,raw,area,entry,'resume_readonly',settings,null);
  }
  await capture(watch,prefix+'-'+area);
  await watch.locator('#matrix tbody').getByRole('button',{name,exact:true}).click();
  await watch.getByRole('button',{name:'Calendário e parâmetros',exact:true}).click();
  const displayed={};
  for(const [label,value] of [['Horas disponíveis confirmadas',16],['Carga prevista (h)',23/15],['Turnos equivalentes confirmados',23/15/6],['Horas livres',16-23/15],['Ocupação (%)',100*23/15/16],['Capacidade física total',240],['Capacidade física livre',217]]){
   const row=watch.locator('#panel-body tr').filter({has:watch.getByRole('cell',{name:label,exact:true})});
   const text=await row.locator('td').nth(1).textContent();const expected=new Intl.NumberFormat('pt-PT',{maximumFractionDigits:2}).format(value)+(label.startsWith('Capacidade física')?' un.':'');
   assert.equal(text,expected,label);displayed[label]=text;
  }
  item.detail_display=displayed;await capture(watch,prefix+'-'+area+'-detail');
  const hoursName='C09 Completo horas '+area;
  item.final_objects=Object.fromEntries(await Promise.all(['resource','calendar','rate','worked_hours'].map(async kind=>[kind,(await objects(editor,kind)).filter(o=>o.name.startsWith(name)||o.name===hoursName)])));
  await context.close();
 }
 assert.deepEqual(report.errors,[]);report.result='passed';console.log('C09: independent H01-H08, calendar/rate/hour changes, visible RAW and weekly results, idempotence, history and rejection passed in both areas.');
})().catch(e=>{report.result='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{
 fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));if(browser)await browser.close();
});
