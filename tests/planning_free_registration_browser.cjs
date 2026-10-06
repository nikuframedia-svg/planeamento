const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE;
if(!base||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated test server required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/planeamento/manual?area=perfis');
  await page.locator('#field-component_ref').waitFor({state:'visible'});
  await page.locator('#local-of').fill('OF887799');
  await page.locator('#local-delivery_date').fill('2026-10-30');
  await page.locator('#field-component_ref').fill('ENS-REGISTO-LIVRE');
  await page.locator('#field-machine').fill('Máquina livre');
  await page.locator('#field-profile').fill('Perfil livre');
  await page.locator('#field-length_mm').fill('por medir');
  await page.locator('#field-quantity_required').fill('10');
  await page.locator('#more-options>summary').click();
  await page.locator('#field-quantity_to_plan').fill('25');
  await page.locator('#field-cut_date').fill('2026-10-20');
  // Um só botão «Guardar» (06/10/2026); o rascunho não aparece em entrada livre.
  assert.equal(await page.locator('#preparation button[type=submit]:visible').count(),1);
  assert.equal(await page.locator('button[name=ready]').textContent(),'Guardar');
  await page.locator('button[name=ready]').click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('guardado')||!document.querySelector('#error').hidden);
  assert.equal(await page.locator('#error').isVisible(),false,await page.locator('#error').textContent());
  const id=new URL(page.url()).searchParams.get('necessidade');assert.ok(id);
  await page.reload();await page.locator('#field-component_ref').waitFor({state:'visible'});
  assert.equal(await page.locator('#field-length_mm').inputValue(),'por medir');
  assert.equal(await page.locator('#field-quantity_to_plan').inputValue(),'25');
  assert.equal(await page.locator('#local-delivery_date').inputValue(),'2026-10-30');
  assert.equal(await page.locator('#field-cut_date').inputValue(),'2026-10-20');
  const response=await page.request.get(base+'/planeamento/api/necessidades/'+id);
  const detail=await response.json();assert.equal(detail.records[0].record_status,'ready');
  assert.equal(detail.records[0].input_values.machine,'Máquina livre');
  assert.deepEqual(errors,[]);
  console.log('Browser: registo livre concluído, persistido e reaberto sem erros.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
