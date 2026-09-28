const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
const prefix=process.env.PLANNING_PROOF||'c04-operation-rate-browser';
if(!/^c04-[a-z-]+$/.test(prefix))throw Error('Simple proof prefix required');
const fixture=JSON.parse(fs.readFileSync(folder+'/c04-operation-rate-fixture.json'));
const units={area_hour:'mm²/h',metres_hour:'m/h',units_hour:'un./h',minutes_unit:'min/un.',fixed_minutes:'min'};
const display=n=>n==null?'—':new Intl.NumberFormat('pt-PT',{maximumFractionDigits:4}).format(n);
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),fixture_sha256:crypto.createHash('sha256').update(fs.readFileSync(folder+'/c04-operation-rate-fixture.json')).digest('hex'),samples:[],errors:[],post_paths:[]};
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')report.post_paths.push(new URL(r.url()).pathname)});
  for(const sample of fixture.samples){
   const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:sample.area,population:'all',selected:[sample.key]}});
   assert.equal(response.status(),200);const api=await response.json();assert.equal(api.rows.length,1);const row=api.rows[0];
   const primary=sample.area==='perfis'?'corte':String(row.values.operation||'');assert.equal(sample.operation,primary,'Primary result fixture');
   for(const [field,expected] of Object.entries(sample.expected)){
    const value=row.values[field];if(expected===null)assert.equal(value,null,field);else assert.ok(Math.abs(value-expected)<=Math.max(1e-6,Math.abs(expected)*1e-8),field);
   }
   assert.equal(row.values.rate_source,sample.source);
   await page.goto(base+'/planeamento/raw?area='+sample.area+'&q='+encodeURIComponent(row.values.of||row.values.component_ref));
   await page.waitForFunction(()=>Raw.state.data);
   await page.locator('#population').selectOption('all');await page.waitForFunction(()=>Raw.state.data.population==='all');
   await page.locator('#page-size').selectOption('500');
   await page.waitForFunction(()=>Raw.state.data.page_size===500&&!document.querySelector('#notice').textContent);
   const visitedPages=[1];
   while(!await page.evaluate(key=>Raw.state.data.rows.some(r=>r.key===key),sample.key)){
    assert.ok(!await page.locator('#next').isDisabled(),'Target must exist in the filtered population');
    const nextPage=await page.evaluate(()=>Raw.state.data.page+1);await page.locator('#next').click();
    await page.waitForFunction(n=>Raw.state.data.page===n&&!document.querySelector('#notice').textContent,nextPage);visitedPages.push(nextPage);
   }
   const index=await page.evaluate(key=>({row:Raw.state.data.rows.findIndex(r=>r.key===key),column:Raw.state.columns.indexOf('of'),version:Raw.state.data.version}),sample.key);
   assert.equal(String(index.version),String(api.version));
   await page.locator('#sheet tbody tr').nth(index.row).locator('td').nth(index.column).dblclick();
   await page.locator('#drawer').getByRole('button',{name:'Taxas e horas',exact:true}).click();
   const heading=page.locator('#drawer h3').filter({hasText:new RegExp('^'+sample.operation+' · ')});
   assert.equal(await heading.count(),1);
   const cells=await heading.locator('xpath=following-sibling::div[1]').locator('tbody td').allTextContents();
   assert.equal(cells[1],display(sample.expected.theoretical_hours));assert.equal(cells[2],sample.source||'');
   assert.equal(cells[3],display(sample.expected.applied_rate_value));assert.equal(cells[4],units[sample.method]||'');
   if(sample.expected.theoretical_hours===null)assert.ok(cells[5].length>5);
   const operationText=await page.locator('#drawer').innerText();
   await page.locator('#drawer').getByRole('button',{name:'Cálculos',exact:true}).click();
   const label=api.columns.find(f=>f.id==='theoretical_hours').label;
   const calculation=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:label,exact:true})});
   await calculation.scrollIntoViewIfNeeded();const detail=await calculation.locator('td').allTextContents();
   assert.equal(detail[1],display(sample.expected.theoretical_hours));assert.ok(!detail[3].includes('[object Object]'));
   const screenshot=prefix+'-'+report.samples.length+'.png';await page.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.samples.push({...sample,reference:row.values.component_ref,version:api.version,visitedPages,shown:cells,calculation:detail,operationText,screenshot});
  }
  assert.deepEqual(report.errors,[]);assert.ok(report.post_paths.every(p=>p==='/planeamento/api/raw/consultas'));
  report.result='passed';console.log(report.samples.length,'operation/rate browser cases passed');
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
