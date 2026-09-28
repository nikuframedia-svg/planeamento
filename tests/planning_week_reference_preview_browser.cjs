const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated service required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,areas:[],errors:[],method:'Open weekly reference preview with existing manual worked-hours declarations; no save or data mutation.'};
 try{
  for(const area of ['perfis','cantoneiras']){
   const page=await browser.newPage({viewport:{width:1440,height:1000}});
   page.on('pageerror',e=>report.errors.push(e.message));
   const sampleResponse=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area,dataset:'capacity_items',filters:[{field:'year',op:'known'},{field:'week',op:'known'}]}});
   assert.equal(sampleResponse.status(),200);const sample=(await sampleResponse.json()).rows[0];assert(sample,'A scheduled operation is required');
   const {year,week}=sample.values;
   await page.goto(base+'/planeamento/disponibilidade?area='+area);
   await page.locator('#matrix tbody tr').first().waitFor();
   await page.locator('#year').fill(String(year));await page.locator('#week').fill(String(week));
   const loaded=page.waitForResponse(r=>r.url().endsWith('/raw/capacidade/consulta')&&r.ok());
   await page.getByRole('button',{name:'Consultar',exact:true}).click();
   const generation=(await (await loaded).json()).version;
   const response=page.waitForResponse(r=>r.url().endsWith('/raw/capacidade/referencia/preview'));
   await page.locator('#new-reference').click();const result=await response;
   const preview=await result.json();assert.equal(result.status(),200,JSON.stringify(preview));
   assert(preview.count>0);assert(preview.token);
   await page.getByRole('button',{name:'Confirmar e guardar referência',exact:true}).waitFor();
   assert.match(await page.locator('#panel-body').innerText(),new RegExp(preview.count+' operações'));
   report.areas.push({area,year,week,sample:sample.key,generation,preview});
   await page.screenshot({path:folder+'/c09-reference-hours-'+area+'.png',fullPage:true});await page.close();
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.failure=e.message;throw e;}
 finally{fs.writeFileSync(folder+'/c09-reference-hours-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
