// Production check: read-only preview and queries; no registration/edits.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const base=process.env.PLANNING_CHECK_BASE||'https://louise-pest-performed-atom.trycloudflare.com';
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],failed=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=400)failed.push([r.status(),r.url()])});
 await page.route('**/planeamento/api/**',route=>route.request().method()==='GET'||route.request().url().endsWith('/necessidades/prever')||route.request().url().endsWith('/raw/consultas')?route.continue():route.abort());
 await page.goto(base+'/planeamento/manual?area=perfis');
 await page.waitForFunction(()=>document.querySelector('#field-component_ref'));
 await page.locator('#local-of').fill('265270');
 await page.waitForFunction(()=>document.querySelector('#picking-summary').textContent.includes('17/08/2026'),undefined,{timeout:60000});
 assert.equal(await page.locator('#field-picking_week').inputValue(),'34');
 assert.equal(await page.locator('#field-picking_year').inputValue(),'');
 const sections=await page.locator('#preparation>section>h2').allTextContents();
 assert.deepEqual(sections.slice(0,2),['Dados da peça','Características de corte']);
 await page.screenshot({path:__dirname+'/manual-public.png',fullPage:true});
 await page.locator('#local-of').fill('999999991');
 await page.waitForFunction(()=>document.querySelector('#picking-summary').textContent.includes('Sem data de Picking disponível'),undefined,{timeout:60000});
 assert.equal(await page.locator('#field-picking_week').inputValue(),'');
 await page.locator('#local-of').fill('265270');
 await page.waitForFunction(()=>document.querySelector('#picking-summary').textContent.includes('17/08/2026'),undefined,{timeout:60000});
 await page.setViewportSize({width:390,height:844});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:__dirname+'/manual-mobile-public.png',fullPage:true});
 const rawResponse=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:'perfis',q:'OF265270',population:'active',page_size:500}});
 assert.equal(rawResponse.status(),200);const raw=await rawResponse.json();
 assert.ok(raw.rows.length>0);
 assert.ok(raw.rows.every(r=>r.values.picking_week===34&&r.values.picking_date==='2026-08-17'));
 assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);
 fs.writeFileSync(__dirname+'/public-results.json',JSON.stringify({base,checked_at:new Date().toISOString(),sections,
    raw_generation:raw.version,rows:raw.rows.map(r=>({key:r.key,of:r.values.of,week:r.values.picking_week,date:r.values.picking_date,
    year:r.values.picking_year,origin:r.values.picking_origin})),errors,failed,database_writes:0},null,2)+'\n');
 await browser.close();console.log('Public: manual automatic Picking, changed OF, layout and RAW date verified.');
})().catch(e=>{console.error(e);process.exit(1)});
