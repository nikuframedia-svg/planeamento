const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated full copy required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={base,at:new Date().toISOString(),worker:'Not running; row publication must be synchronous',areas:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  const previous=fs.existsSync(folder+'/c05-publish-browser.json')?JSON.parse(fs.readFileSync(folder+'/c05-publish-browser.json','utf8')):{areas:[]};
  const fixtures=JSON.parse(fs.readFileSync(folder+'/c03-browser.json','utf8'));
  for(const fixture of fixtures){
   const item={area:fixture.area,id:fixture.id};report.areas.push(item);
   await page.goto(base+'/planeamento/preparar?area='+fixture.area+'&necessidade='+fixture.id);
   await page.locator('#field-quantity_required').waitFor();const initial=Number(await page.locator('#field-quantity_required').inputValue());
   await page.locator('#field-quantity_required').fill(String(initial+1));
   let started=Date.now();const [received]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/necessidades/registar')&&r.request().method()==='POST',{timeout:60000}),page.locator('button[name=draft]').click()]);const returned=Date.now();
   const saved=await received.json();assert.equal(received.status(),200,JSON.stringify(saved));
   assert.equal(saved.publication.status,'published');
   const published=saved.publication.rows.find(r=>r.area===fixture.area&&r.need_id===fixture.id);
   assert.equal(published.values.remaining,initial+1);assert.equal(published.revision,saved.revision);
   await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Linha atualizada na RAW'),null,{timeout:10000});
   item.form={requestMs:returned-started,responseToVisibleMs:Date.now()-returned,saved};assert(item.form.responseToVisibleMs<=2000);
   const existing=previous.areas.find(r=>r.area===fixture.area)?.second;
   if(existing){item.second=existing;}else{
   await page.getByRole('button',{name:'Adicionar outra peça desta OF',exact:true}).click();
   await page.locator('#field-component_ref').fill('C05-SECOND-'+fixture.area+'-'+Date.now());
   const values=fixture.detail.records.find(r=>r.area===fixture.area).values_json;
   await page.locator('#field-material_type').selectOption(values.material_type);
   const profile=page.locator('#field-profile');
   if(await profile.evaluate(n=>n.tagName)==='SELECT')await profile.selectOption(values.profile);else await profile.fill(values.profile);
   for(const field of ['outer_diameter_mm','width_mm','height_mm','thickness_mm','grade']){
    const input=page.locator('#field-'+field);if(values[field]!=null&&await input.isVisible())await input.fill(String(values[field]));
   }
   await page.locator('#field-length_mm').fill('2001');await page.locator('#field-quantity_required').fill('7');
   await page.locator('#field-stock_length_mm').fill('6000');await page.locator('#field-abocardar').uncheck();
   await page.locator('#field-machine').selectOption(values.machine);
   if(fixture.area==='cantoneiras')await page.locator('#field-operation').selectOption(values.operation);
   const [nextReceived]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/necessidades/registar')&&r.request().method()==='POST',{timeout:60000}),page.locator('button[name=draft]').click()]);item.second=await nextReceived.json();
   assert.equal(nextReceived.status(),200,JSON.stringify(item.second));
   assert.notEqual(item.second.need_id,fixture.id);
   const nextRow=item.second.publication.rows.find(r=>r.area===fixture.area&&r.need_id===item.second.need_id);
   assert.equal(nextRow.values.of,fixture.order);assert.equal(nextRow.values.remaining,7);
   if(fixture.area==='perfis')assert.equal(nextRow.values.bars,4);
   await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Linha atualizada na RAW'));
   }
   await page.goto(base+'/planeamento/raw?area='+fixture.area+'&q='+encodeURIComponent(fixture.detail.need.component_ref));
   await page.waitForFunction(id=>window.Raw?.state.data?.rows.some(r=>r.need_id===id),fixture.id);
   const location=await page.evaluate(id=>{const s=Raw.state;return {row:s.data.rows.findIndex(r=>r.need_id===id),col:s.columns.indexOf('quantity_required'),version:s.data.version}},fixture.id);
   assert(location.col>=0);
   await page.locator(`#sheet td[data-row="${location.row}"][data-col="${location.col}"]`).dblclick();
   await page.locator('#edit-value').fill(String(initial+2));
   started=Date.now();
   const [editedReceived]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/raw/lotes')&&r.request().method()==='POST',{timeout:60000}),page.locator('#editor-form').getByRole('button',{name:'Guardar rascunho',exact:true}).click()]);const editReturned=Date.now();
   const edited=await editedReceived.json();assert.equal(editedReceived.status(),200,JSON.stringify(edited));
   await page.waitForFunction(({id,q})=>Raw.state.data.rows.find(r=>r.need_id===id)?.values.remaining===q,{id:fixture.id,q:initial+2});
   item.raw={requestMs:editReturned-started,responseToVisibleMs:Date.now()-editReturned,edited};assert(item.raw.responseToVisibleMs<=2000);
   assert.equal(await page.locator('#editor').isVisible(),false);
   assert((await page.locator('#notice').innerText()).includes('processamento'));
   const api=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:fixture.area,selected:[fixture.id]}});const now=await api.json();
   assert.equal(now.rows[0].values.quantity_required,initial+2);assert.equal(now.rows[0].revision,edited.items[0].revision);
   await page.screenshot({path:folder+'/c05-'+fixture.area+'-published.png',fullPage:true});
   item.final=now.rows[0];fs.writeFileSync(folder+'/c05-publish-browser.json',JSON.stringify(report,null,2));
  }
  assert.deepEqual(report.errors,[]);console.log('Both forms and RAW publish current revisions without worker; a second piece is created within each existing local OF.');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(folder+'/c05-publish-browser.json',JSON.stringify(report,null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
