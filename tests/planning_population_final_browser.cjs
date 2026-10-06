const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
const audit=JSON.parse(fs.readFileSync(folder+'/c06-dossiers-current-population.json'));
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),areas:[],errors:[],requests:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))report.requests.push({method:r.method(),url:r.url()});});
  for(const area of ['perfis','cantoneiras']){
   await page.goto(base+'/planeamento/raw?area='+area);
   await page.waitForFunction(()=>window.Raw?.state.data?.total>0);
   const result={area,scopes:{}};
   for(const scope of ['active','history','all']){
    await page.locator('#population').selectOption(scope);
    await page.waitForFunction(s=>Raw.state.data.population===s&&document.querySelector('#notice').textContent==='',scope);
    const snap=await page.evaluate(()=>({version:Raw.state.data.version,total:Raw.state.data.total,rows:Raw.state.data.rows.map(r=>({key:r.key,active:r.values.planning_active,reference:r.values.component_ref})),label:document.querySelector('#count').textContent}));
    const expected=scope==='all'?audit.areas[area].compared:audit.areas[area].expected_from_sources[scope];
    assert.equal(snap.total,expected);assert.equal(Number(snap.version),audit.areas[area].version);
    if(scope!=='all')assert.ok(snap.rows.every(r=>r.active===(scope==='active')));
    result.scopes[scope]=snap;
    await page.screenshot({path:`${folder}/c06-final-${area}-${scope}.png`,fullPage:true});
   }
   const closed=result.scopes.history.rows[0];
   const checks=await page.evaluate(async({area,closed})=>{
    const active=await Raw.api('raw/consultas',{area,selected:[closed.key],population:'active',state:'all'});
    const history=await Raw.api('raw/consultas',{area,selected:[closed.key],population:'history'});
    const exports={};
    for(const scope of ['active','history']){
     const response=await fetch('/planeamento/api/raw/exportar/csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({area,population:scope,selected:[closed.key],columns:['component_ref']})});
     if(!response.ok)throw Error(await response.text());exports[scope]=await response.text();
    }
    return {active:active.total,history:history.total,keys:history.rows.map(r=>r.key),exports};
   },{area,closed});
   assert.equal(checks.active,0);assert.equal(checks.history,1);assert.deepEqual(checks.keys,[closed.key]);
   assert.equal(checks.exports.active.trim().split(/\r?\n/).length,1);
   assert.equal(checks.exports.history.trim().split(/\r?\n/).length,2);
   assert.ok(checks.exports.history.includes(closed.reference));
   result.closedSelection=checks;report.areas.push(result);
  }
  assert.deepEqual(report.errors,[]);
  assert.ok(report.requests.every(r=>r.method==='POST'&&['/planeamento/api/raw/consultas','/planeamento/api/raw/exportar/csv'].includes(new URL(r.url).pathname)));
  report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/c06-final-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
