const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE;
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated planning server required');
const output='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={environment:base,at:new Date().toISOString(),script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),scopes:[],errors:[],writes:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))report.writes.push(r.url());});
  await page.goto(base+'/planeamento');
  await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('Ativos'));
  assert.equal(await page.locator('#population').inputValue(),'active');
  for(const [scope,label] of [['active','Ativos'],['history','Histórico / fechados'],['all','Todos']]){
   await page.locator('#population').selectOption(scope);
   const response=page.waitForResponse(r=>r.url().includes('/api/ordens?')&&new URL(r.url()).searchParams.get('populacao')===scope);
   await page.locator('#filters button[type=submit]').click();
   const data=await (await response).json();
   await page.waitForFunction(label=>document.querySelector('#count').textContent.includes(label),label);
   assert.equal(data.population,scope);assert.ok(data.total>0);
   assert.equal(await page.locator('#orders .open-order').count(),data.orders.length);
   assert.equal(await page.locator('#count').textContent(),`${data.total} ordens · ${label} · ${data.mode==='direct'?'CPIS direto':'cópia importada da macro'}`);
   report.scopes.push({scope,total:data.total,version:data.version,orders:data.orders.map(r=>({of:r.of,plan:r.plan,counts:r.population_counts}))});
   await page.screenshot({path:`${output}/c06-legacy-${scope}.png`,fullPage:true});
  }
  // A known historical OF can be mixed; choose an order with no active pieces.
  const closed=report.scopes.find(r=>r.scope==='history').orders.find(r=>r.counts.active===0&&r.counts.history>0);
  assert.ok(closed,'Need an entirely closed order in the historical sample');
  await page.locator('#query').fill(closed.of);
  await page.locator('#population').selectOption('active');
  const search=page.waitForResponse(r=>r.url().includes('/api/ordens?')&&new URL(r.url()).searchParams.get('q')===closed.of);
  await page.locator('#filters button[type=submit]').click();
  const found=await (await search).json();
  assert.ok(!found.orders.some(r=>r.of===closed.of));
  const detail=await (await page.request.get(base+'/planeamento/api/ordens/'+closed.of)).json();
  assert.equal(detail.context.of,closed.of);
  assert.equal(detail.plan_lines.length,closed.counts.history);
  for(const [area,count] of Object.entries(closed.plan)){
   const history=await (await page.request.get(base+'/planeamento/api/linhas?'+new URLSearchParams({area,of:closed.of,populacao:'history'}))).json();
   const active=await (await page.request.get(base+'/planeamento/api/linhas?'+new URLSearchParams({area,of:closed.of,populacao:'active'}))).json();
   assert.equal(history.lines.length,count);assert.equal(active.lines.length,0);
   assert.ok(history.lines.every(line=>detail.plan_lines.some(p=>p.plan_key===line.plan_key)));
  }
  report.historicalDetail={of:closed.of,planLines:detail.plan_lines.length,production:detail.production.length,documents:detail.documents.length};
  // Hold a real active response while a newer historical request completes.
  let release, captured;
  const gate=new Promise(resolve=>{release=resolve;});
  const ready=new Promise(resolve=>{captured=resolve;});
  let hold=true;
  await page.route('**/planeamento/api/ordens?*',async route=>{
   if(hold&&new URL(route.request().url()).searchParams.get('populacao')==='active'){
    hold=false;const response=await route.fetch();captured();await gate;await route.fulfill({response});
   }else await route.continue();
  });
  await page.locator('#query').fill('');
  await page.locator('#filters button[type=submit]').click();
  await ready;
  await page.locator('#population').selectOption('history');
  const current=page.waitForResponse(r=>r.url().includes('/api/ordens?')&&new URL(r.url()).searchParams.get('populacao')==='history');
  await page.locator('#filters button[type=submit]').click();
  await current;
  await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('Histórico / fechados'));
  const historicalLabel=await page.locator('#count').textContent();
  const delayed=page.waitForResponse(r=>r.url().includes('/api/ordens?')&&new URL(r.url()).searchParams.get('populacao')==='active');
  release();await delayed;
  await page.waitForTimeout(300);
  assert.equal(await page.locator('#count').textContent(),historicalLabel);
  assert.equal(await page.locator('#population').inputValue(),'history');
  report.delayedActiveResponseIgnored=true;
  await page.unroute('**/planeamento/api/ordens?*');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('Ativos'));
  assert.equal(await page.locator('#population').inputValue(),'active');
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.writes,[]);
  report.passed=true;
 }catch(error){report.failure=error.stack;throw error;}
 finally{fs.writeFileSync(output+'/c06-legacy-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
