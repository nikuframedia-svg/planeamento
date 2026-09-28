const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
if(!base || process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
const output='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={environment:base,at:new Date().toISOString(),areas:[],errors:[]};
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>report.errors.push(e.message));
  for(const area of ['perfis','cantoneiras']){
   await page.goto(base+'/planeamento/raw?area='+area);
   await page.waitForFunction(()=>window.Raw?.state.data?.total>0);
   const result={area,scopes:{}};
   for(const scope of ['active','history','all']){
    await page.locator('#population').selectOption(scope);
    await page.waitForFunction(s=>Raw.state.data.population===s&&document.querySelector('#notice').textContent==='',scope);
    const snap=await page.evaluate(()=>({version:Raw.state.data.version,count:Raw.state.data.total,rows:Raw.state.data.rows.map(r=>({key:r.key,active:r.values.planning_active,reason:r.values.closure_reason})),label:document.querySelector('#count').textContent}));
    assert.ok(snap.count>0);
    if(scope!=='all')assert.ok(snap.rows.every(r=>r.active===(scope==='active')));
    result.scopes[scope]=snap;
    await page.screenshot({path:output+'/c06-'+area+'-'+scope+'.png',fullPage:true});
   }
   assert.equal(result.scopes.active.count+result.scopes.history.count,result.scopes.all.count);
   // Closed selection is absent from the active query even when state=all.
   const key=result.scopes.history.rows[0].key;
   const selected=await page.evaluate(async key=>Raw.api('raw/consultas',{area:Raw.state.area,selected:[key],state:'all'}),key);
   assert.equal(selected.total,0);
   await page.locator('#population').selectOption('history');
   await page.waitForFunction(()=>Raw.state.data.population==='history');
   const view=await page.evaluate(async()=>Raw.api('raw/objects/view',Raw.request({area:Raw.state.area,name:'C06 Histórico '+Raw.state.area+' '+Date.now(),definition:Raw.config()})));
   await page.evaluate(()=>Raw.refreshViews());
   await page.locator('#population').selectOption('active');
   await page.waitForFunction(()=>Raw.state.data.population==='active');
   await page.locator('#views').selectOption(view.id);
   await page.waitForFunction(()=>Raw.state.data.population==='history');
   assert.equal(await page.locator('#population').inputValue(),'history');
   assert.equal(await page.evaluate(()=>Raw.state.data.total),result.scopes.history.count);
   result.savedView=view.id;
   await page.locator('#views').selectOption('');
   await page.waitForFunction(()=>Raw.state.data.population==='active');
   assert.equal(await page.locator('#population').inputValue(),'active');
   await page.reload();await page.waitForFunction(()=>Raw.state.data?.population==='active');
   report.areas.push(result);
  }
  assert.deepEqual(report.errors,[]);
  fs.writeFileSync(output+'/c06-browser.json',JSON.stringify(report,null,2));
  console.log('Active/history/all counts, closed selection, persisted history view, reset and reload passed in both areas.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
