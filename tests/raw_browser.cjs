const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(process.env.PLANNING_CHECK_BASE+'/planeamento/raw');await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('linhas'));
assert.equal(await page.locator('#sheet th').count(),43);
const headers=await page.locator('#sheet th').allTextContents();const notes=headers.findIndex(h=>h.startsWith('Observações locais'));
await page.locator('#sheet tbody tr').first().locator('td').nth(notes).press('Enter');await page.locator('#edit-value').fill('Decisão no browser RAW');await page.getByRole('button',{name:'Ver origem e produção',exact:true}).click();await page.locator('#close-panel').click();assert.equal(await page.locator('#edit-value').inputValue(),'Decisão no browser RAW');await page.getByRole('button',{name:'Guardar rascunho',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Rascunho guardado'));
assert.ok((await page.locator('#sheet tbody').innerText()).includes('Decisão no browser RAW'));
await page.locator('#sheet tbody tr').first().getByRole('button',{name:/^Ver/}).click();await page.getByRole('button',{name:'Ver origem e alterações'}).click();await page.waitForFunction(()=>document.querySelector('#panel-content').textContent.includes('preparation_saved'));await page.locator('#close-panel').click();
await page.locator('[name=q]').fill('ausente');await page.getByRole('button',{name:'Filtrar',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#count').textContent.startsWith('0 linhas'));
await page.locator('[name=q]').fill('');await page.getByRole('button',{name:'Filtrar',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#count').textContent.startsWith('0 linhas'));
await page.screenshot({path:'docs/raw-2026-09-22/browser-edicao.png',fullPage:true});
await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'docs/raw-2026-09-22/browser-mobile.png',fullPage:true});
await page.setViewportSize({width:720,height:500});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'docs/raw-2026-09-22/browser-200.png',fullPage:true});
assert.deepEqual(errors,[]);await browser.close();console.log('RAW: edição, histórico, pesquisa, 390 px e 200% passaram.');
})().catch(e=>{console.error(e);process.exit(1)});
