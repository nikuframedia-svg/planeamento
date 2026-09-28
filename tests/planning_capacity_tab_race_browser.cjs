// Delay the real pieces response to reproduce switching tabs during a request.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao',prefix=process.env.PLANNING_CHECK_PREFIX||'c09-tab-race';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1'||!/^[a-z0-9-]+$/.test(prefix))throw Error('Isolated test only');
const report={at:new Date().toISOString(),areas:[],errors:[]};let browser;
(async()=>{
 browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 for(const area of ['perfis','cantoneiras']){
  const p=await browser.newPage({viewport:{width:1440,height:1050}});p.on('pageerror',e=>report.errors.push(e.message));
  await p.goto(base+'/planeamento/disponibilidade?area='+area);await p.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
  const name='C05 Ensaio '+area+' 1';await p.locator('#search').fill(name);await p.locator('#year').fill('2027');await p.locator('#week').fill('1');
  const updated=p.waitForResponse(r=>r.url().endsWith('/raw/capacidade/consulta')&&r.request().postDataJSON()?.q===name&&String(r.request().postDataJSON()?.year)==='2027');
  await p.getByRole('button',{name:'Consultar',exact:true}).click();await updated;await p.waitForFunction(()=>document.querySelector('#period-state').textContent.includes('2027'));
  let release,arrived;const gate=new Promise(r=>release=r),ready=new Promise(r=>arrived=r);let original;
  await p.route('**/raw/capacidade/pecas',async route=>{original=await route.fetch();arrived();await gate;await route.fulfill({response:original});});
  await p.locator('#matrix tbody').getByRole('button',{name,exact:true}).click();await ready;
  await p.getByRole('button',{name:'Calendário e parâmetros',exact:true}).click();
  const before=await p.locator('#panel-body').innerText();assert(before.includes('Capacidade física total'));
  const received=p.waitForResponse(r=>r.url().endsWith('/raw/capacidade/pecas'));release();await received;
  // Await response handlers and a rendering frame after delivery of real data.
  await p.waitForTimeout(300);
  const after=await p.locator('#panel-body').innerText();
  report.areas.push({area,source_status:original.status(),before,after});
  assert(after.includes('Capacidade física total'),'Late pieces response replaced the selected parameters tab');
  assert.deepEqual(after,before);
  await p.screenshot({path:folder+'/'+prefix+'-'+area+'.png'});await p.close();
 }
 assert.deepEqual(report.errors,[]);report.result='passed';console.log('Late real pieces response cannot overwrite selected parameters tab in either area.');
})().catch(e=>{report.result='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));if(browser)await browser.close();});
