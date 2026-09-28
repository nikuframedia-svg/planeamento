const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Disposable server required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),environment:'Disposable SQLite/PostgreSQL fixture; not real Windows ingestion',script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(base+'/planeamento/ocr-original');await page.locator('#rows article').nth(1).waitFor();
  assert.equal(await page.locator('#rows article').count(),2);
  assert((await page.locator('#source').innerText()).includes('Revisão atual aplicada ao planeamento'));
  const text=await page.locator('#rows').innerText();
  assert(text.includes('Identidade técnica única'));assert(text.includes('Sem peça compatível identificada'));
  assert(text.includes('Quantidade: Por confirmar'));assert(text.includes('Operação: corte'));
  const data=await(await page.request.get(base+'/planeamento/api/ocr-original/registos')).json();
  assert(data.records.every(r=>r.source_event_key.startsWith('original:')&&r.planning.length));
  assert(data.source.included_in_planning_balances);assert.deepEqual(report.errors,[]);
  report.source=data.source;report.records=data.records;report.result='passed';
  await page.screenshot({path:folder+'/c01-original-source-browser.png',fullPage:true});
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/c01-original-source-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
