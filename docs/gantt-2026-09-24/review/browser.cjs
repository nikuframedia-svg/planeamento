const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs');
let browser;
(async()=>{
 browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];let forceStale=false;
 page.on('pageerror',err=>errors.push(err.message));
 await page.route('**/api/**',async route=>{
   if(route.request().method()!=='GET')return route.abort();
   if(forceStale&&route.request().url().includes('/gantt/jobs/')){
     const response=await route.fetch();const json=await response.json();
     return route.fulfill({response,json:{...json,stale:true}});
   }
   await route.continue();
 });
 await page.goto('http://127.0.0.1:8113/planeamento/gantt');
 await page.waitForFunction(()=>document.querySelectorAll('.operation-row').length>0);
 const choice=page.locator('#scenario option').filter({hasText:'Piloto Perfis'}).first();
 const id=await choice.getAttribute('value');
 await page.locator('#scenario').selectOption(id);
 await page.waitForFunction(()=>document.querySelector('#schedule-hint').textContent.includes('sequência inicial'));
 const actual={summary:await page.locator('#summary').innerText(),
   milestones:await page.locator('.milestone').count(),bars:await page.locator('.bar').count(),
   source_state:await page.locator('#source-state').innerText(),
   accept_disabled:await page.locator('#accept').isDisabled()};
 await page.screenshot({path:'/tmp/gantt-review-2026-09-24/ui-current.png',fullPage:true});
 forceStale=true;
 await page.locator('#scenario').selectOption('');
 await page.waitForFunction(()=>document.querySelector('#scenario-name').value==='Plano de Perfis');
 await page.locator('#scenario').selectOption(id);
 await page.waitForFunction(()=>document.querySelector('#schedule-hint').textContent.includes('sequência inicial')&&document.querySelector('#accept').disabled);
 const stale={source_state:await page.locator('#source-state').innerText(),
   notice:await page.locator('#notice').innerText(),accept_disabled:await page.locator('#accept').isDisabled()};
 const result={actual,simulated_stale_job:stale,page_errors:errors};
 fs.writeFileSync('/tmp/gantt-review-2026-09-24/browser-results.json',JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));await browser.close();
})().catch(async err=>{console.error(err);await browser?.close();process.exitCode=1});
