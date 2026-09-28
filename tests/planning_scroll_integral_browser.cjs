const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
if(!base || !process.env.PLANNING_TEST_ISOLATED)throw Error('Isolated server required');
const output='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),report=[];
  for(const area of ['perfis','cantoneiras']){
   await page.goto(base+'/planeamento/raw?area='+area);await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('linhas'));
   await page.locator('#open-columns').click();
   for(const group of await page.locator('.columns-group').all()) await group.locator('summary input').check();
   await page.getByRole('button',{name:'Aplicar e fechar'}).click();
   for(const width of [1440,1024,390,720]){
    await page.setViewportSize({width,height:width===720?500:1000});
    await page.waitForTimeout(100);
    const range=page.locator('#horizontal-position');
    assert.equal(await range.isVisible(),true);
    const rect=await range.boundingBox();assert.ok(rect.y>=0&&rect.y+rect.height<=(width===720?500:1000));
    await range.focus();await range.press('End');
    await page.waitForTimeout(50);
    const end=await page.locator('#grid').evaluate(n=>({x:n.scrollLeft,max:n.scrollWidth-n.clientWidth}));
    assert.ok(end.max>0);assert.ok(Math.abs(end.x-end.max)<2,JSON.stringify({area,width,end,range:await range.inputValue(),max:await range.getAttribute('max')}));
    await range.press('Home');
    assert.equal(await page.locator('#grid').evaluate(n=>n.scrollLeft),0);
    const size=await page.locator('#sheet th .label').first().evaluate(n=>getComputedStyle(n).fontSize);
    assert.ok(Math.abs(parseFloat(size)-14.6667)<.01,size);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('#scroll-last').click();
    await page.screenshot({path:output+'/c08-'+area+'-'+width+'.png',fullPage:true});
    report.push({area,width,range:rect,end,fontSize:size});
   }
  }
  const cdp=await page.context().newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
  const {root}=await cdp.send('DOM.getDocument');const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId,selector:'#sheet th .label'});
  const fonts=await cdp.send('CSS.getPlatformFontsForNode',{nodeId});
  fs.writeFileSync(output+'/c08-browser.json',JSON.stringify({report,fonts,calibriVerified:fonts.fonts.some(f=>f.familyName==='Calibri'),zoom200:'720 CSS px em janela 1440; zoom real ainda por verificar'},null,2));
  console.log('Visible horizontal control, first/last scroll and 11pt declarations passed; real Calibri and true 200% zoom reported separately');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
