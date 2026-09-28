// Repeat only the outstanding V06 timing paths on the retained identities.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
const execute=promisify(execFile),base=process.env.PLANNING_CHECK_BASE,F='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated integral copy required');
const context=JSON.parse(fs.readFileSync(process.env.PLANNING_V06_CONTEXT));
const macroOnly=process.env.PLANNING_V06_MACRO_ONLY==='1',uiOnly=process.env.PLANNING_V06_UI_ONLY==='1',prefix=macroOnly?'t10-v06-macro-final-browser':uiOnly?'t10-v06-final-ui-browser':'t10-v06-completion-browser';
const report={at:new Date().toISOString(),scope:'V06 retained Perfis/Cantoneiras identities; real UI saves and background source revisions',timing_policy:'24/09 user instruction: report aggregate latency; exceeding 10s does not block delivery.',steps:[],errors:[],failures:[],latency_exceedances:[]};
let browser;
async function source(action,area,id){return JSON.parse((await execute('.venv/bin/python',['-m','scripts.planning_v06_context',action,'--area',area,'--need-id',id],{maxBuffer:8*1024*1024})).stdout);}
(async()=>{
 browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 for(const area of (macroOnly?['cantoneiras']:['perfis','cantoneiras'])){
  const fixture=context.areas[area],id=fixture.need_id,page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(base+'/planeamento/raw?area='+area+'&q='+encodeURIComponent(fixture.row.values.of));await page.locator('#population').selectOption('all');
  await page.waitForFunction(id=>Raw.state.data?.rows.some(r=>r.need_id===id)&&!Raw.state.data.aggregates_pending&&!Raw.state.data.source_refresh_pending,id,{timeout:60000});
  if(!macroOnly&&!await page.evaluate(()=>Raw.state.columns.includes('quantity_required'))){
   await page.locator('#open-columns').click();
   const column=page.locator('[data-column-id="quantity_required"]'),group=column.locator('xpath=ancestor::details[1]');
   if(!await group.evaluate(node=>node.open))await group.locator('summary').click();
   await column.locator('input[data-column-control="quantity_required:visible"]').check();
   await page.locator('#close-drawer').click();
  }
  async function current(){return page.evaluate(id=>Raw.state.data.rows.find(r=>r.need_id===id),id);}
  async function finish(name,stamp,condition,arg,extra={}){
   await page.waitForFunction(condition,{id,...arg},{timeout:60000});
   const step={area,name,need_id:id,...extra,response_to_line_ms:Date.now()-stamp};
   await page.waitForFunction(()=>!Raw.state.data.aggregates_pending&&!Raw.state.data.source_refresh_pending,null,{timeout:60000});
   step.response_to_aggregates_ms=Date.now()-stamp;step.row=await current();step.version=await page.evaluate(()=>Raw.state.data.version);
   if(!extra.source_change&&step.response_to_line_ms>2000)report.failures.push(area+':'+name+':line');
   if(step.response_to_aggregates_ms>10000)report.latency_exceedances.push(area+':'+name+':aggregates');
   report.steps.push(step);console.log(area,name,step.response_to_line_ms,step.response_to_aggregates_ms);
   fs.writeFileSync(F+'/'+prefix+'.json',JSON.stringify(report,null,2));
  }
  const original=(await current()).values.quantity_required;
  for(const quantity of (macroOnly?[]:[original+1,original])){
   const pos=await page.evaluate(id=>({row:Raw.state.data.rows.findIndex(r=>r.need_id===id),col:Raw.state.columns.indexOf('quantity_required')}),id);assert(pos.col>=0);
   await page.locator(`#sheet td[data-row="${pos.row}"][data-col="${pos.col}"]`).dblclick();await page.locator('#edit-value').fill(String(quantity));
   const start=Date.now();const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/raw/lotes')&&r.request().method()==='POST',{timeout:120000}),page.locator('#editor-form').getByRole('button',{name:'Guardar rascunho',exact:true}).click()]);const stamp=Date.now();
   const saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));assert.equal(saved.publication.status,'published');
   await finish(quantity===original?'ui_restore_quantity':'ui_quantity',stamp,({id,quantity,version})=>Raw.state.data.rows.find(r=>r.need_id===id)?.values.quantity_required===quantity&&Number(Raw.state.data.version)>=Number(version),{quantity,version:saved.publication.areas[area].version},{request_ms:stamp-start});
  }
  if(area==='cantoneiras'&&!uiOnly){
   if(!macroOnly){
   const before=await current(),length=before.sources.find(s=>s.kind==='pdf').payload.values.length_mm;
   const started=Date.now(),changed=await source('document_revision',area,id);
   await finish('document_revision',changed.committed_ms,({id,length})=>Raw.state.data.rows.find(r=>r.need_id===id)?.sources.some(s=>s.kind==='pdf'&&s.payload.values.length_mm===length),{length:length+5},{source_change:true,source_sync_ms:changed.committed_ms-started});
   assert.equal((await current()).values.length_mm,before.values.length_mm,'Human geometry must be preserved');
   }
   for(const action of ['macro_close','macro_open']){
    const start=Date.now(),change=await source(action,area,id);
    await finish(action,change.committed_ms,({id,active})=>Raw.state.data.rows.find(r=>r.need_id===id)?.values.planning_active===active,{active:action.endsWith('open')},{source_change:true,source_sync_ms:change.committed_ms-start});
   }
  }
  await page.screenshot({path:F+'/t10-v06-completion-'+area+'.png',fullPage:true});await page.close();
 }
 assert.deepEqual(report.errors,[]);report.result=report.failures.length?'incomplete':'passed';
})().catch(e=>{report.result='failed';report.error=e.stack;console.error(e);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(F+'/'+prefix+'.json',JSON.stringify(report,null,2));if(browser)await browser.close();});
