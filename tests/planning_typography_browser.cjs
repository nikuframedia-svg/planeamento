const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
const prefix=process.env.PLANNING_CHECK_PREFIX||'t9-typography';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid prefix');
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),cases:[],errors:[]};
 try{
  const page=await browser.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  for(const width of [1440,1024,390])for(const path of ['/planeamento','/planeamento/manual?area=perfis','/planeamento/manual?area=cantoneiras','/planeamento/dossies','/planeamento/capacidades?area=perfis','/planeamento/disponibilidade?area=cantoneiras','/planeamento/ocr-original']){
   await page.setViewportSize({width,height:1050});const response=await page.goto(base+path);assert.equal(response.status(),200,path);
   await page.waitForLoadState('networkidle');
   const styles=await page.evaluate(()=>{
    const nodes=[...document.querySelectorAll('body *')].filter(n=>n.getClientRects().length&&['INPUT','TEXTAREA','SELECT','BUTTON'].includes(n.tagName)||n.getClientRects().length&&[...n.childNodes].some(c=>c.nodeType===3&&c.textContent.trim()));
    const leaf=nodes.find(n=>n.childElementCount===0&&n.textContent.trim());if(leaf)leaf.dataset.fontProbe='true';
    return {count:nodes.length,failures:nodes.map(n=>({tag:n.tagName,id:n.id,size:getComputedStyle(n).fontSize,family:getComputedStyle(n).fontFamily})).filter(n=>Math.abs(parseFloat(n.size)-14.6667)>0.02),scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth};
   });
   const session=await page.context().newCDPSession(page);await session.send('DOM.enable');await session.send('CSS.enable');const {root}=await session.send('DOM.getDocument'),{nodeId}=await session.send('DOM.querySelector',{nodeId:root.nodeId,selector:'[data-font-probe]'});const fonts=await session.send('CSS.getPlatformFontsForNode',{nodeId});await session.detach();
   assert(fonts.fonts.some(f=>f.glyphCount>0),'No rendered font evidence');
   const screenshot=`${prefix}-${report.cases.length}-${width}.png`;await page.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.cases.push({path,width,...styles,fonts:fonts.fonts,screenshot});
   assert(styles.count>0);assert.deepEqual(styles.failures,[],path);assert(styles.scrollWidth<=width+1,path+' document overflows');
  }
  assert.deepEqual(report.errors,[]);report.result='passed_typography_and_reflow';report.requirement='11pt; substitute font accepted by user';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
