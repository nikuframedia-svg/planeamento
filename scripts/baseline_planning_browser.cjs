// Read-only baseline: column changes here are transient and never saved.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE || 'http://127.0.0.1:8113';
const output='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
  const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const report={base,observed_at:new Date().toISOString(),areas:{}};
    for(const area of ['perfis','cantoneiras']){
      await page.goto(base+'/planeamento/raw?area='+area);
      await page.waitForFunction(()=>document.querySelector('#count')?.textContent.includes('linhas'));
      const cdp=await page.context().newCDPSession(page);
      await cdp.send('DOM.enable');await cdp.send('CSS.enable');
      const {root}=await cdp.send('DOM.getDocument');
      const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId,selector:'#sheet th .label'});
      const fonts=await cdp.send('CSS.getPlatformFontsForNode',{nodeId});
      const metrics=await page.locator('#grid').evaluate(n=>({clientWidth:n.clientWidth,scrollWidth:n.scrollWidth,clientHeight:n.clientHeight,scrollHeight:n.scrollHeight,cssFont:getComputedStyle(n).fontFamily,cssSize:getComputedStyle(n).fontSize}));
      await page.screenshot({path:output+'/baseline-'+area+'.png',fullPage:true});
      await page.locator('#open-columns').click();
      await page.getByText('Identificação',{exact:true}).click();
      const url=page.url();
      const group=page.locator('details.columns-group').filter({has:page.getByText('Identificação',{exact:true})});
      const before=await group.getAttribute('open');
      await group.getByRole('button',{name:'↓',exact:true}).first().click();
      const after=await group.getAttribute('open');
      report.areas[area]={metrics,fonts,arrow:{before,after,urlChanged:url!==page.url()},draggables:await page.locator('.column-row[draggable=true]').count()};
      await page.screenshot({path:output+'/baseline-'+area+'-columns.png',fullPage:true});
      await cdp.detach();
    }
    await page.goto(base+'/planeamento/manual?area=cantoneiras');
    report.manual={requiresSearch:await page.locator('#search').isVisible(),formHidden:!(await page.locator('#preparation').isVisible())};
    await page.screenshot({path:output+'/baseline-manual.png',fullPage:true});
    fs.writeFileSync(output+'/baseline-browser.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
