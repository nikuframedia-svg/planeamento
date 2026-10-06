const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(!base||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={base,at:new Date().toISOString(),areas:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));
  const fixtures=JSON.parse(fs.readFileSync(folder+'/c03-browser.json','utf8'));
  for(const fixture of fixtures){
   await page.goto(base+'/planeamento/preparar?area='+fixture.area+'&necessidade='+fixture.id);
   await page.waitForFunction(()=>document.querySelector('#preview-status').textContent.startsWith('Pré-visualização calculada'));
   const before=await page.evaluate(async id=>(await(await fetch('/planeamento/api/necessidades/'+id)).json()).need,fixture.id);
   const input=page.locator('#field-quantity_required'),original=Number(await input.inputValue());
   const changed=original+23,start=Date.now();
   const response=page.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&Number(r.request().postDataJSON().values.quantity_required)===changed);
   await input.fill(String(changed));
   const received=await response,returnedAt=Date.now();assert.equal(received.status(),200);
   const data=await received.json();assert.equal(data.saved,false);assert.equal(data.row.values.remaining,changed);
   await page.waitForFunction(q=>[...document.querySelectorAll('#preview-results tr')].find(r=>r.dataset.previewField==='remaining')?.textContent.includes(String(q)),changed);
   const visibleAt=Date.now();
   // A late response for an older edit cannot restore its result over a newer edit.
   let started,finished;const oldStarted=new Promise(resolve=>started=resolve),oldFinished=new Promise(resolve=>finished=resolve);
   await page.route('**/necessidades/prever',async route=>{
    if(Number(route.request().postDataJSON().values.quantity_required)!==changed+1)return route.continue();
    started();const response=await route.fetch();await new Promise(r=>setTimeout(r,1500));await route.fulfill({response});finished();
   });
   await input.fill(String(changed+1));await oldStarted;
   await input.fill(String(changed+2));
   await page.waitForFunction(q=>[...document.querySelectorAll('#preview-results tr')].find(r=>r.dataset.previewField==='remaining')?.textContent.includes(String(q)),changed+2);
   await oldFinished;
   const displayed=await page.locator('#preview-results tr[data-preview-field=remaining]').textContent();assert(displayed.includes(String(changed+2)));
   await page.unroute('**/necessidades/prever');
   const after=await page.evaluate(async id=>(await(await fetch('/planeamento/api/necessidades/'+id)).json()).need,fixture.id);
   assert.equal(after.revision,before.revision);assert.equal(after.quantity_required,before.quantity_required);
   await page.locator('#calculation-preview').scrollIntoViewIfNeeded();
   await page.locator('#calculation-preview details').evaluate(n=>n.open=true);
   await page.screenshot({path:folder+'/c05-'+fixture.area+'-preview.png',fullPage:true});
   report.areas.push({area:fixture.area,need_id:fixture.id,before_revision:before.revision,after_revision:after.revision,
    serverResult:data.row.values,requestPlusDebounceMs:returnedAt-start,responseToVisibleMs:visibleAt-returnedAt,lateResponsePreserved:displayed});
  }
  assert.deepEqual(report.errors,[]);fs.writeFileSync(folder+'/c05-preview-browser.json',JSON.stringify(report,null,2));
  console.log('Both forms preview current server facts without saving; delayed old responses cannot replace newer results.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
