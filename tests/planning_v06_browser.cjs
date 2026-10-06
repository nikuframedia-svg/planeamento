// Cumulative V06 on the same two needs, with the real isolated worker.
const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
const execute=promisify(execFile),base=process.env.PLANNING_CHECK_BASE,F='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Integral isolated copy required');
const report={at:new Date().toISOString(),scope:'Planeamento de Perfis e Cantoneiras; MES sources only',areas:[],errors:[],failures:[],worker:'Isolated background worker; browser does not rebuild projections'};
const uid=()=>crypto.randomUUID(),same=(a,b)=>typeof a==='number'&&typeof b==='number'?Math.abs(a-b)<1e-7:a===b;
const mutate=async(action,area,id)=>JSON.parse((await execute('.venv/bin/python',['-m','scripts.planning_v06_context',action,...(area?['--area',area]:[]),...(id?['--need-id',id]:[])],{maxBuffer:8*1024*1024})).stdout);
let browser;
const previous=fs.existsSync(F+'/t10-v06-browser.json')?JSON.parse(fs.readFileSync(F+'/t10-v06-browser.json')):null;
const priorFile=previous?F+'/t10-v06-attempt-'+Date.now()+'.json':null;
if(previous)fs.copyFileSync(F+'/t10-v06-browser.json',priorFile);
(async()=>{
 const context=JSON.parse(fs.readFileSync(process.env.PLANNING_V06_CONTEXT||F+'/t9-v06-context.json'));assert.equal(context.scope,'V06 isolated acceptance only');
 browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 for(const area of ['perfis','cantoneiras']){
  const fixture=context.areas[area],page=await browser.newPage({viewport:{width:1440,height:1000}}),form=await browser.newPage({viewport:{width:1440,height:1000}});
  for(const p of [page,form])p.on('pageerror',e=>report.errors.push(e.message));
  const item={area,original_key:fixture.row.key,steps:[]};report.areas.push(item);
  async function post(path,data){const r=await page.request.post(base+'/planeamento/api/'+path,{data,timeout:120000});const out=await r.json();assert.equal(r.status(),200,JSON.stringify(out));return out;}
  async function get(path){const r=await page.request.get(base+'/planeamento/api/'+path);assert.equal(r.status(),200);return r.json();}
  let key=fixture.row.key,id=fixture.need_id||null;
  const listing=async()=>post('raw/consultas',{area,population:'all',selected:[id||key]});
  const row=async()=>{const d=await listing();assert.equal(d.rows.length,1);return d.rows[0];};
  await page.goto(base+'/planeamento/raw?area='+area+'&q='+encodeURIComponent(fixture.row.values.of));
  await page.locator('#population').selectOption('all');
  await page.waitForFunction(({key,id})=>Raw.state.data?.rows.some(r=>r.need_id===id||r.key===key||r.selection_aliases?.includes(key)),{key,id},{timeout:30000});
  const original=await row(),frozen=await listing();item.frozen_generation=frozen.version;
  const prior=previous?.areas.find(a=>a.area===area&&a.need_id===id);
  if(id){assert(prior,'Existing need must retain its previous test evidence');item.steps=prior.steps.filter(s=>s.validated||s.history_events!=null);item.need_id=id;item.rate_before=prior.rate_before;item.hours=prior.hours;item.reused_prefix=priorFile;}
  const hasStep=name=>item.steps.some(s=>s.name===name);
  async function complete(name,received,expected={},published=null,preview=null,source=false){
   const step={name,...received,source_change:source};item.steps.push(step);
   const stamp=received.completed_ms;
   await page.waitForFunction(({id,key,expected,version})=>{
    const r=Raw.state.data?.rows.find(r=>r.need_id===id||r.key===key||r.selection_aliases?.includes(key));
    return r&&(!version||Number(Raw.state.data.version)>=Number(version))&&Object.entries(expected).every(([k,v])=>r.values[k]===v);
   },{id,key,expected,version:published},{timeout:30000});
   step.response_to_line_ms=Date.now()-stamp;
   await page.waitForFunction(({version})=>Raw.state.data&&!Raw.state.data.aggregates_pending&&!Raw.state.data.source_refresh_pending&&(!version||Number(Raw.state.data.version)>=Number(version)),{version:published},{timeout:60000});
   step.response_to_aggregates_ms=Date.now()-stamp;
   const data=await listing();step.version=data.version;step.row=data.rows[0];assert(step.row);
   if(!source&&step.response_to_line_ms>2000)report.failures.push(area+':'+name+':line '+step.response_to_line_ms+'ms');
   if(step.response_to_aggregates_ms>10000)report.failures.push(area+':'+name+':aggregates '+step.response_to_aggregates_ms+'ms');
   for(const [k,v] of Object.entries(expected))assert.equal(step.row.values[k],v,k);
   if(preview){for(const x of preview.results)assert(same(step.row.values[x.field],x.value),name+' preview '+x.field+': '+step.row.values[x.field]+' != '+x.value);step.preview=preview;}
   const cols=['quantity_required','length_mm','remaining','theoretical_hours','hours_pct','machine','planning_active'];
   step.exports={columns:cols,expected:cols.map(k=>step.row.values[k])};
   for(const fmt of ['csv','xlsx']){
    const r=await page.request.post(base+'/planeamento/api/raw/exportar/'+fmt,{data:{area,population:'all',selected:[id||key],columns:cols}});assert.equal(r.status(),200);
    const file=F+'/t10-v06-'+area+'-'+item.steps.length+'.'+fmt;fs.writeFileSync(file,await r.body());step.exports[fmt]=file;
   }
   const prior=await post('raw/consultas',{area,population:'all',version:frozen.version,selected:[original.key]});assert.deepEqual(prior.rows[0],original);
   if(id){const d=await get('necessidades/'+id);assert.equal(d.need.revision,step.row.revision);step.need_revision=d.need.revision;step.history_events=(await get('necessidades/'+id+'/historico')).events.length;}
   step.validated=true;
   console.log(area,name,step.response_to_line_ms,step.response_to_aggregates_ms);
   fs.writeFileSync(F+'/t10-v06-browser.json',JSON.stringify(report,null,2));return step;
  }
  async function edit(name,values){
   if(hasStep(name))return;
   const d=await listing(),r=d.rows[0],cat=await get('catalogos?area='+area);
   const simulated=await post('necessidades/prever',{area,need_id:id,expected_revision:r.revision,catalog_version:cat.version,values});
   const t=Date.now(),saved=await post('raw/lotes',{request_id:uid(),area,version:d.version,edits:[{key:r.key,expected_revision:r.revision,values}]});const done=Date.now();
   assert.equal(saved.publication.status,'published');
   return complete(name,{request_ms:done-t,completed_ms:done},values,saved.publication.areas[area].version,simulated);
  }
  const originalLength=fixture.row.values.length_mm;
  let rate=prior?.rate_before;
  if(!id){
  const cat=await get('catalogos?area='+area),t=Date.now();
  const saved=await post('necessidades/registar',{request_id:uid(),area,catalog_version:cat.version,
   source:{kind:'plan_line',id:fixture.row.plan_key,version:fixture.row.calculation.macro_snapshot},record_status:'draft',values:{notes:'V06 cumulative acceptance in isolated copy',operation:area==='perfis'?'corte':'112'}});
  const done=Date.now();id=saved.need_id;item.need_id=id;assert(id);key=fixture.row.key;
  await complete('creation',{request_ms:done-t,completed_ms:done},{notes:'V06 cumulative acceptance in isolated copy'},saved.publication.areas[area].version);
  await mutate('remember',area,id);
  }
  await form.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+id);
  await form.locator('#field-component_ref').waitFor();assert.equal(await form.locator('#field-component_ref').inputValue(),fixture.row.values.component_ref);
  await edit('quantity_length',{quantity_required:50,length_mm:originalLength+((await row()).values.length_mm===originalLength+1?2:1)});
  await edit('restore_length',{length_mm:originalLength});
  await edit('machine_week',{machine:fixture.machines[1],planned_year:2027,planned_week:2,expected_date:'2027-01-11'});
  const resource=fixture.resources[1].resource,allRates=await get('raw/objects/rate');
  if(!hasStep('rate')){
  rate=allRates.items.find(r=>r.id===fixture.resources[1].rate.id);assert(rate);item.rate_before=rate;
  const rateVersion=Number((await listing()).version)+1,rt=Date.now();await post('raw/objects/rate',{request_id:uid(),id:rate.id,expected_revision:rate.revision,area,name:rate.name,definition:{...rate.definition,value:rate.definition.value+1}});
  const rd=Date.now();await complete('rate',{request_ms:rd-rt,completed_ms:rd},{},rateVersion);
  }
  if(!hasStep('hours')){
  const hd={resource_id:resource.id,mode:'period',start_date:'2027-01-11',end_date:'2027-01-17',hours:2,operation:area==='perfis'?'corte':'112',source:'V06 isolated hours; not a factory declaration',confirmed:true};
  const existingHours=(await get('raw/objects/worked_hours?area='+area)).items.find(h=>!h.archived&&h.definition.resource_id===resource.id&&h.definition.mode==='period'&&h.definition.start_date===hd.start_date&&h.definition.end_date===hd.end_date);
  if(existingHours){item.hours_before=existingHours;hd.hours=Number(existingHours.definition.hours)+1;}
  const hp=await post('raw/horas/prever',{definition:hd});
  const hoursVersion=Number((await listing()).version)+1,ht=Date.now();const hours=await post('raw/objects/worked_hours',{request_id:uid(),area,...(existingHours?{id:existingHours.id,expected_revision:existingHours.revision}:{}),name:'V06 hours '+id,definition:{...hd,replace_ocr:hp.replacement_required,basis_hash:hp.basis_hash}});const hdone=Date.now();item.hours=hours;
  await complete('hours',{request_ms:hdone-ht,completed_ms:hdone},{},hoursVersion);
  }
  for(const action of ['mes','mes_correct']){
   if(hasStep(action+'_association'))continue;
   let recordId=fixture.mes_revisions?.find(s=>s.action===action)?.after.id;
   if(!hasStep(action)){
    const version=Number((await listing()).version)+1,st=Date.now(),source=await mutate(action,area,id);recordId=source.result.record_id;
    await complete(action,{source_sync_ms:source.committed_ms-st,completed_ms:source.committed_ms,record_id:recordId},{},version,null,true);
   }
   let evidence=await get('producao/pendencias?estado=all&of='+fixture.row.values.of+'&area='+area);
   const record=evidence.records.find(r=>r.id===recordId);assert(record,JSON.stringify(evidence));
   const d=await get('necessidades/'+id),operationCode=area==='perfis'?'corte':String((await row()).values.operation);
   const operation=d.operations.find(o=>o.area===area&&o.code===operationCode);
   assert(operation);
   const at=Date.now();const association=await post('associacoes',{request_id:uid(),production_record_id:record.id,expected_revision:record.decision?.revision||0,evidence_hash:record.evidence_hash,reason:'V06 explicit identity and operation review in isolated copy',allocations:[{need_id:id,operation_id:operation.id,expected_need_revision:d.need.revision,quantity:action==='mes'?4:6}]});
   const ad=Date.now();await complete(action+'_association',{request_ms:ad-at,completed_ms:ad},{},association.publication.areas[area].version);
  }
  if(!fixture.document_id){
   const source=await mutate('document',area,id),beforeDoc=await get('necessidades/'+id);
   await post('necessidades/resolver',{request_id:uid(),area,source:source.result.source,need_id:id,expected_revision:beforeDoc.need.revision,reason:'V06 explicit document link'});
  }
  if(!hasStep('document_revision')){
  const beforeDoc=(await get('necessidades/'+id)).sources.find(s=>s.kind==='pdf').payload.values.length_mm;
  const docRevision=await mutate('document_revision',area,id);
  await page.waitForFunction(({id,length})=>Raw.state.data?.rows.find(r=>r.need_id===id)?.sources.some(s=>s.kind==='pdf'&&s.payload.values.length_mm===length),{id,length:beforeDoc+5},{timeout:30000});
  const dstep=await complete('document_revision',{completed_ms:docRevision.committed_ms},{length_mm:originalLength},null,null,true);
  assert(dstep.row.sources.some(s=>s.kind==='pdf'&&s.payload.values.length_mm===beforeDoc+5));
  }
  for(const action of ['cpis_close','cpis_open','macro_close','macro_open']){
   if(hasStep(action))continue;
   const version=Number((await listing()).version)+1,st=Date.now(),change=await mutate(action,area,id);
   const active=action.endsWith('open');
   await complete(action,{source_sync_ms:change.committed_ms-st,completed_ms:change.committed_ms},{planning_active:active},version,null,true);
  }
  await form.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+id);await form.locator('#field-component_ref').waitFor();
  await form.screenshot({path:F+'/t10-v06-'+area+'-form.png',fullPage:true});await page.screenshot({path:F+'/t10-v06-'+area+'-raw.png',fullPage:true});
  if(!hasStep('restore_rate')){
  const currentRate=(await get('raw/objects/rate')).items.find(r=>r.id===rate.id);
  const restoreVersion=Number((await listing()).version)+1,restoreStart=Date.now();
  await post('raw/objects/rate',{request_id:uid(),id:rate.id,expected_revision:currentRate.revision,area,name:rate.name,definition:rate.definition});
  const restored=Date.now();await complete('restore_rate',{request_ms:restored-restoreStart,completed_ms:restored},{},restoreVersion);
  }
  await page.close();await form.close();
 }
 report.failures=report.areas.flatMap(a=>a.steps.flatMap(s=>[...(!s.source_change&&s.response_to_line_ms>2000?[a.area+':'+s.name+':line '+s.response_to_line_ms+'ms']:[]),...(s.response_to_aggregates_ms>10000?[a.area+':'+s.name+':aggregates '+s.response_to_aggregates_ms+'ms']:[])]));
 assert.deepEqual(report.errors,[]);report.result=report.failures.length?'incomplete':'passed';
})().catch(e=>{report.result='failed';report.error=e.stack;console.error(e);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(F+'/t10-v06-browser.json',JSON.stringify(report,null,2));if(browser)await browser.close();});
