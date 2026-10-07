const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,area=process.env.PLANNING_CHECK_AREA,need=process.env.PLANNING_CHECK_NEED;
const folder='docs/validacao-planeamento-integral/20260923-execucao';
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Disposable server required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,area,need,errors:[],steps:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+need+'&ocr_source=original');
  await page.waitForFunction(()=>document.querySelector('#field-component_ref')?.value);
  // «Produção e histórico» abre-se primeiro (bloco fechado desde 06/10/2026).
  await page.locator('#secondary-details>summary').click();
  await page.locator('#evidence-open').click();await page.locator('#production-open').click();
  assert.equal(await page.locator('#production-source').inputValue(),'original');
  const item=page.locator('#production-content .item').first();
  await item.getByLabel('Quantidade atribuída',{exact:true}).fill('2');
  await item.getByLabel('Justificação',{exact:true}).fill('Distribuição parcial conferida no ensaio isolado');
  let response=page.waitForResponse(r=>r.url().endsWith('/api/associacoes'));
  await item.getByRole('button',{name:'Guardar associação',exact:true}).click();
  let saved=await response;assert.equal(saved.status(),200);let result=await saved.json();
  const partialResponseAt=Date.now(),partialRequestMs=saved.request().timing().responseEnd;
  assert.equal(result.publication.status,'published');
  await page.waitForFunction(()=>document.querySelector('#production-content')?.textContent.includes('Distribuição parcial'));
  report.steps.push({action:'partial',revision:result.revision,publication:result.publication.status,
    request_ms:partialRequestMs,response_to_visible_ms:Date.now()-partialResponseAt});
  const complete=page.locator('#production-content .item').first();
  await complete.getByLabel('Quantidade atribuída',{exact:true}).fill('4');
  await complete.getByLabel('Justificação',{exact:true}).fill('Distribuição integral conferida no ensaio isolado');
  response=page.waitForResponse(r=>r.url().endsWith('/api/associacoes'));
  await complete.getByRole('button',{name:'Guardar associação',exact:true}).click();
  saved=await response;assert.equal(saved.status(),200);result=await saved.json();
  const responseAt=Date.now();assert.equal(result.revision,2);
  await page.waitForFunction(()=>document.querySelectorAll('#production-content .item').length===0);
  const lag=Date.now()-responseAt;assert(lag<=2000);
  await page.locator('#production-dialog').getByRole('button',{name:'Fechar',exact:true}).click();
  assert.match(await page.locator('#evidence').innerText(),/Produção validada no OCR[\s\S]*4/);
  const raw=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area,population:'all',selected:[need]}});
  assert.equal(raw.status(),200);const row=(await raw.json()).rows[0];
  assert.equal(row.values[area==='perfis'?'cut':'made'],4);assert.equal(row.values.remaining,96);
  report.steps.push({action:'complete',revision:result.revision,request_ms:saved.request().timing().responseEnd,lag_ms:lag,remaining:row.values.remaining});
  await page.locator('#production-open').click();await page.locator('#production-filter').selectOption('associated');
  await page.waitForFunction(()=>document.querySelectorAll('#production-content .item').length===1);
  assert.equal(await page.getByLabel('Quantidade atribuída',{exact:true}).inputValue(),'4');
  await page.screenshot({path:folder+'/t1-association-'+area+'.png',fullPage:true});
  await page.reload();await page.waitForFunction(()=>document.querySelector('#field-component_ref')?.value);
  await page.locator('#secondary-details>summary').click();await page.locator('#evidence-open').click();
  await page.waitForFunction(()=>/Produção validada no OCR[\s\S]*4/.test(document.querySelector('#evidence')?.textContent||''));
  assert.match(await page.locator('#evidence').innerText(),/Produção validada no OCR[\s\S]*4/);
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e}
 finally{fs.writeFileSync(folder+'/t1-association-'+area+'-browser.json',JSON.stringify(report,null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
