const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated planning server required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const fixture=JSON.parse(fs.readFileSync(folder+'/c02-source-policy-swap-fixture.json'));
 const report={at:new Date().toISOString(),base,fixture,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),steps:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  // Discard uncommitted operation drafts when changing the operation again.
  page.on('dialog',d=>d.accept());
  await page.goto(base+'/planeamento/preparar?area=cantoneiras&of='+encodeURIComponent(fixture.of));
  await page.locator('#references-open').click();await page.locator('#reference-query').fill(fixture.reference);
  await page.locator('#references').getByRole('button').filter({hasText:fixture.reference+' ·'}).first().click();
  for(const code of ['112','119','112']){
   const response=page.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&r.request().postDataJSON()?.values?.operation===code&&r.request().postDataJSON()?.source?.id===fixture.plan_key);
   await page.locator('#field-operation').selectOption(code);
   const received=await response,data=await received.json();assert.equal(received.status(),200,JSON.stringify(data));
   report.lastResponse={request:received.request().postDataJSON(),values:data.row?.values,source:data.row?.raw,operations:data.row?.operations};assert.equal(data.saved,false);assert.equal(data.row.calculation.contract,'planning-integral-20260923-v5');
   const source=data.row.calculation.production_sources.find(s=>s.operation===code);
   assert.equal(data.row.values.made,code==='112'?Number(fixture.accumulated):null);
   assert.equal(data.row.values.remaining,code==='112'?fixture.quantity-Number(fixture.accumulated):null);
   assert.equal(source.origin,code==='112'?'Excel provisório':'Indisponível');
   if(code==='119')assert(source.reason.includes('operação 112'));
   await page.waitForFunction(expected=>document.querySelector('#preview-results tr[data-preview-field=made] td:nth-child(2)')?.textContent===expected,code==='112'?fixture.accumulated:'—');
   await page.locator('#calculation-preview details').evaluate(n=>n.open=true);
   await page.locator('#preview-results tr[data-preview-field=made]').scrollIntoViewIfNeeded();
   const screenshot=`c02-source-policy-preview-${report.steps.length}-${code}.png`;
   await page.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.steps.push({operation:code,values:{made:data.row.values.made,remaining:data.row.values.remaining},source,screenshot});
  }
  const unchanged=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:'cantoneiras',population:'all',selected:[fixture.row_key]}});
  const published=await unchanged.json();assert.equal(published.rows[0].values.operation,'112');assert.equal(published.rows[0].values.made,Number(fixture.accumulated));
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/c02-source-policy-preview-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
