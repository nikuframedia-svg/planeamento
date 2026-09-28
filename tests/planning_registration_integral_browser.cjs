const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
if(!base || !process.env.PLANNING_TEST_ISOLATED)throw Error('Isolated test server required');
const output='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),report=[];
  for(const [index,area] of ['perfis','cantoneiras'].entries()){
   const order='OF99'+String(Date.now()).slice(-6)+index;
   await page.goto(base+'/planeamento/manual?area='+area);
   await page.locator('#field-component_ref').waitFor({state:'visible'});
   assert.equal(await page.locator('#search').isVisible(),false);
   await page.locator('#local-of').fill(order);
   await page.locator('#local-ov').fill('OV-INTEGRAL-'+index);
   await page.locator('#local-customer').fill('Cliente ensaio isolado');
   await page.locator('#local-designation').fill('Obra ensaio isolado');
   await page.locator('#local-delivery_date').fill('2026-10-15');
   await page.locator('#field-component_ref').fill('INTEGRAL-'+area);
   await page.locator('#field-material_type').selectOption(area==='perfis'?'Varão redondo':'Cantoneira');
   const profile=page.locator('#field-profile');
   if(await profile.evaluate(n=>n.tagName)==='SELECT'){
    const option=await profile.locator('option').evaluateAll(xs=>xs.find(x=>x.value&&x.value!=='__custom__')?.value);
    await profile.selectOption(option);
   }else await profile.fill(area==='perfis'?'20':'L45X45X4');
   for(const [field,value] of Object.entries(area==='perfis'?{outer_diameter_mm:'20'}:{width_mm:'45',height_mm:'45',thickness_mm:'4'})){
    const input=page.locator('#field-'+field);if(await input.isVisible())await input.fill(value);
   }
   await page.locator('#field-grade').fill('S355JR');
   await page.locator('#field-length_mm').fill('2000');
   await page.locator('#field-quantity_required').fill('100');
   await page.locator('#field-stock_length_mm').fill('12000');
   await page.locator('#field-material_requested').selectOption('false');
   await page.locator('#field-expected_date').fill('2026-10-01');
   const machine=await page.locator('#field-machine option').evaluateAll(xs=>xs.find(x=>x.value)?.value);
   await page.locator('#field-machine').selectOption(machine);
   if(area==='cantoneiras'){
    const operation=await page.locator('#field-operation option').evaluateAll(xs=>xs.find(x=>x.value&&x.value!=='0')?.value);
    await page.locator('#field-operation').selectOption(operation);
   }
   await page.locator('button[name=draft]').click();
   await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Rascunho guardado')||!document.querySelector('#error').hidden);
   assert.equal(await page.locator('#error').isVisible(),false,await page.locator('#error').textContent());
   assert.ok(page.url().includes('necessidade='));
   const id=new URL(page.url()).searchParams.get('necessidade');
   const detail=await (await page.request.get(base+'/planeamento/api/necessidades/'+id)).json();
   assert.equal(detail.local_order.values_json.ov,'OV-INTEGRAL-'+index);
   assert.equal(detail.need.specification.quantity_required,100);
   assert.equal(detail.records[0].values_json.stock_length_mm,12000);
   assert.equal(detail.records[0].values_json.material_requested,false);
   await page.reload();await page.locator('#field-component_ref').waitFor({state:'visible'});
   assert.equal(await page.locator('#local-ov').inputValue(),'OV-INTEGRAL-'+index);
   assert.equal(await page.locator('#field-stock_length_mm').inputValue(),'12000');
   await page.screenshot({path:output+'/c03-'+area+'-form.png',fullPage:true});
   report.push({area,order,id,detail});
  }
  fs.writeFileSync(output+'/c03-browser.json',JSON.stringify(report,null,2));
  console.log('Created previously nonexistent OF/OV in both areas without searching; reloaded administrative and technical values preserved');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
