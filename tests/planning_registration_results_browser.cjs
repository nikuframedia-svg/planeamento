// Read-only DOM parity: every calculated result and every editable RAW field.
const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated Planeamento required');
const prefix=process.env.PLANNING_CHECK_PREFIX||'c03-complete-results-final';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid prefix');
const fixture=JSON.parse(fs.readFileSync(folder+'/c03-complete-run.json'));
const report={at:new Date().toISOString(),base,areas:{},errors:[],writes:[]};
let browser;
(async()=>{
 browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 for(const [area,entry] of Object.entries(fixture.areas)){
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&!r.url().endsWith('/necessidades/prever'))report.writes.push(r.url());});
  const response=page.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&r.request().postDataJSON()?.need_id===entry.pieces[0].id);
  await page.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+entry.pieces[0].id);
  const preview=await (await response).json();assert.equal(preview.saved,false);
  const raw=await (await page.request.get(base+'/planeamento/api/raw/colunas?area='+area)).json();
  const applicable=new Set(raw.columns.map(f=>f.id));
  await page.waitForFunction(()=>document.querySelector('#preview-status').textContent.startsWith('Pré-visualização calculada'));
  await page.locator('#calculation-preview details summary').click();
  const visible=await page.locator('#preview-results tr[data-preview-field]').evaluateAll(ns=>ns.map(n=>({field:n.dataset.previewField,value:n.children[1].textContent,origin:n.children[2].textContent})));
  assert.deepEqual(visible.map(r=>r.field).sort(),Object.keys(preview.row.calculation.rules).filter(k=>applicable.has(k)).sort());
  for(const r of preview.results){
   const text=(r.value===null||r.value===undefined||r.value===''?'Não disponível':typeof r.value==='boolean'?(r.value?'Sim':'Não'):String(r.value))+(r.value!=null&&r.unit?' '+r.unit:'');
   assert.equal(visible.find(v=>v.field===r.field).value,text,r.field);
   if(r.field!=='stock_length_mm')assert.equal(await page.locator('#field-'+r.field).count(),0,'Derived field is not a manual input: '+r.field);
  }
  const principal=area==='perfis'?'cut':'made';
  assert(visible.find(r=>r.field===principal).origin.includes('Condição inicial local'));
  const controls=await page.locator('#preparation [id^="field-"]').evaluateAll(ns=>ns.map(n=>n.id.slice(6)));
  const editable=raw.columns.filter(f=>f.editable).map(f=>f.id);assert(editable.every(id=>controls.includes(id)));
  const readonlyFacts=raw.columns.filter(f=>f.group==='production'&&!f.editable).map(f=>f.id);
  assert(readonlyFacts.every(id=>!controls.includes(id)));
  await page.locator('#calculation-preview').scrollIntoViewIfNeeded();
  await page.screenshot({path:folder+'/'+prefix+'-'+area+'.png',fullPage:true});
  report.areas[area]={need_id:entry.pieces[0].id,editable,controls,readonly_facts:readonlyFacts,preview,visible,internal_rules_outside_area_contract:Object.keys(preview.row.calculation.rules).filter(k=>!applicable.has(k))};await page.close();
 }
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.writes,[]);report.result='passed';
 console.log('C03 DOM parity: all calculated results rendered, editable RAW fields present, production facts not editable; no writes.');
})().catch(e=>{report.result='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{
 fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));if(browser)await browser.close();
});
