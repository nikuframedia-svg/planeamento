// Read-only validation of the deployed source plan. Never solve/save/accept in production.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const base=process.env.PLANNING_CHECK_BASE||'http://127.0.0.1:8113';
  const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],bad=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.url().includes('/api/raw/gantt')&&r.status()>=400)bad.push(r.status()+' '+r.url())});
  await page.route('**/api/raw/gantt/**',route=>route.request().method()==='GET'?route.continue():route.abort());
  await page.goto(base+'/planeamento/gantt');
  await page.waitForFunction(()=>document.querySelector('#pending-count').textContent.includes('operações'));
  const response=await page.request.get(base+'/planeamento/api/raw/gantt/operations');assert.equal(response.status(),200);
  const snapshot=await response.json(),plan=snapshot.source_plan;
  assert.equal(await page.locator('#compare').inputValue(),'source');
  assert.equal(await page.locator('.capacity-card').count(),Object.keys(snapshot.resources).length);
  assert.equal(plan.entries.length+plan.pending.length+plan.completed,snapshot.operations.length);
  assert.equal(await page.locator('#accept').isDisabled(),true);
  function countWindow(first){const start=Date.parse(first),end=start+12*7*86400000;return plan.entries.filter(e=>Date.parse(e.end_date_exclusive)>start&&Date.parse(e.start_date)<end).length}
  const current=await page.locator('#source-week').inputValue();
  assert.equal(await page.locator('.forecast-bar').count(),countWindow(current));
  const initialBars=await page.locator('.forecast-bar').count();
  const resource=snapshot.source_plan.entries.find(e=>e.start_date>=current)?.resource_id;
  if(resource){
    await page.locator('#source-machine-filter').selectOption(resource);
    assert.equal(await page.locator('.source-machine').count(),1);
    assert.equal((await page.locator('#pending-count').innerText()).split(' de ')[1].split(' ')[0],String(snapshot.operations.length));
    await page.locator('#source-machine-filter').selectOption('');
    assert.equal(await page.locator('.forecast-bar').count(),initialBars);
  }
  await page.screenshot({path:__dirname+'/source-plan-live.png',fullPage:true});
  const target=plan.entries.find(e=>e.hours>0);assert.ok(target);
  const monday=new Date(target.start_date+'T12:00:00Z');monday.setUTCDate(monday.getUTCDate()-((monday.getUTCDay()+6)%7));
  const chosen=monday.toISOString().slice(0,10);
  await page.locator('#source-week').selectOption(chosen);
  assert.equal(await page.locator('.forecast-bar').count(),countWindow(chosen));
  await page.locator('.forecast-bar').first().click();assert.ok(await page.locator('#selected-key').inputValue());
  await page.locator('#search').fill('Vanguard');
  assert.equal(await page.locator('.forecast-bar').count(),countWindow(chosen),'list filter does not remove work from the chart');
  await page.locator('#scale').selectOption('week');
  assert.equal(await page.locator('.forecast-bar').count(),countWindow(chosen));
  await page.locator('#search').fill('');
  await page.locator('#source-today').click();
  assert.equal(await page.locator('#source-week').inputValue(),current);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:__dirname+'/source-plan-mobile.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  const options=await page.locator('#scenario option').count();
  if(options>1){
    await page.locator('#scenario').selectOption(await page.locator('#scenario option').nth(options-1).getAttribute('value'));
    await page.waitForTimeout(1500);
    await page.locator('#compare').selectOption('source');
    assert.equal(await page.locator('.forecast-bar').count(),countWindow(current),'current plan survives historical scenario loading');
  }
  assert.deepEqual(errors,[]);assert.deepEqual(bad,[]);
  const result={operations:snapshot.operations.length,machines:Object.values(snapshot.resources).map(r=>r.name),
    forecasts:plan.entries.length,forecasts_with_duration:plan.entries.filter(e=>e.hours>0).length,
    pending:plan.pending.length,completed:plan.completed,initial_bars:initialBars,
    week:current,source_references:snapshot.source_references,errors,bad,database_writes:0};
  fs.writeFileSync(__dirname+'/source-plan-browser-results.json',JSON.stringify(result,null,2)+'\n');
  await browser.close();console.log(JSON.stringify(result,null,2));
})().catch(error=>{console.error(error);process.exit(1)});
