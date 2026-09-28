const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',route=>route.request().method()==='GET'?route.continue():route.abort());
    await page.goto('http://127.0.0.1:8113/planeamento/gantt');
    await page.waitForFunction(()=>document.querySelectorAll('.operation-row').length>0);
    const scenario=page.locator('#scenario option').filter({hasText:'Piloto Perfis'}).first();
    await page.locator('#scenario').selectOption(await scenario.getAttribute('value'));
    await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('Proposta desatualizada'));
    const result={operations:(await page.locator('.operation-row').count()),
      milestone_groups:await page.locator('.milestone-row').count(),
      milestone_markers:await page.locator('.milestone-bucket').count(),
      bars:await page.locator('.bar').count(),
      source_state:await page.locator('#source-state').innerText(),
      notice:await page.locator('#notice').innerText(),
      accept_disabled:await page.locator('#accept').isDisabled(),
      page_errors:errors};
    assert.ok(result.milestone_markers>0);
    assert.equal(result.accept_disabled,true);
    assert.match(result.notice,/Gera uma nova proposta/);
    assert.deepEqual(errors,[]);
    const folder=__dirname;
    await page.screenshot({path:path.join(folder,'ui-fixed.png'),fullPage:true});
    fs.writeFileSync(path.join(folder,'fix-browser-results.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result));
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
