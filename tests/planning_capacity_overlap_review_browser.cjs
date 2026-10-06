// C09 read-only review of the real imported declarations replaced in the clone.
const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated Planeamento required');
const prior=JSON.parse(fs.readFileSync(folder+'/c09-browser.json'));
const report={at:new Date().toISOString(),script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),areas:[],errors:[],writes:[]};let browser;
(async()=>{
 browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 for(const fixture of prior.areas){
  const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/raw/objects/'))report.writes.push(r.url());});
  const all=await (await page.request.get(base+'/planeamento/api/raw/objects/worked_hours')).json();
  const declaration=all.items.find(x=>x.id===fixture.saved.id);assert(declaration);
  const history=await (await page.request.get(base+'/planeamento/api/raw/objects/'+declaration.id+'/historico')).json();
  await page.goto(base+'/planeamento/disponibilidade?area='+fixture.area);await page.locator('#configure').click();
  await page.locator('#panel-body').getByRole('button',{name:'Horas reais',exact:true}).click();
  await page.locator('#panel-body').getByRole('button',{name:declaration.name,exact:true}).click();
  const edit=page.locator('#edit-panel');assert.equal(await edit.getByLabel('Horas reais (h)',{exact:true}).inputValue(),'6');
  assert(await edit.getByLabel('Substituir integralmente',{exact:false}).isChecked());
  const response=page.waitForResponse(r=>r.url().endsWith('/raw/horas/prever')&&r.request().postDataJSON()?.id===declaration.id);
  await edit.getByRole('button',{name:'Conferir declarações',exact:true}).click();const result=await response;assert.equal(result.status(),200);const preview=await result.json();
  assert.equal(preview.replacement_required,fixture.area==='perfis');assert.equal(preview.manual_overlaps.length,0);
  assert.deepEqual(preview.observations.filter(x=>x.hours!==null).map(x=>x.hours),fixture.area==='perfis'?[8]:[]);
  assert.deepEqual(preview.observations.map(x=>x.key).sort(),[...declaration.definition.replaces].sort());
  assert.equal(await edit.locator('#hours-evidence tbody tr').count(),fixture.area==='perfis'?3:9);
  const d=declaration.definition;
  const capacity=await (await page.request.post(base+'/planeamento/api/raw/capacidade/consulta',{data:{area:fixture.area,mode:'weekly',year:d.year,week:d.week,q:'C09 Isolado '+fixture.area}})).json();
  assert.equal(capacity.rows.length,1);const row=capacity.rows[0];assert.equal(row.values.actual_hours,6);
  assert.equal(row.actual_coverage.total,1);assert.equal(row.actual_coverage.known,1);assert.equal(row.actual_evidence.length,1);
  assert.equal(row.actual_evidence[0].origin,'Manual');assert.deepEqual([...row.actual_evidence[0].sheets].sort(),[...d.replaces].sort());
  assert.deepEqual((await(await page.request.get(base+'/planeamento/api/raw/objects/worked_hours')).json()).items.find(x=>x.id===declaration.id),declaration);
  assert.deepEqual(await(await page.request.get(base+'/planeamento/api/raw/objects/'+declaration.id+'/historico')).json(),history);
  await page.screenshot({path:folder+'/c09-overlap-review-'+fixture.area+'.png'});
  report.areas.push({area:fixture.area,declaration,history,preview,row});await page.close();
 }
 assert.deepEqual(report.errors,[]);assert.deepEqual(report.writes,[]);report.result='passed';console.log('Current UI and published totals: 3 + 9 original declarations, one audited manual replacement per resource, 6h each; no duplicate hours or writes.');
})().catch(e=>{report.result='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(folder+'/c09-overlap-review.json',JSON.stringify(report,null,2));if(browser)await browser.close();});
