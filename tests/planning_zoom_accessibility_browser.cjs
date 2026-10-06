// C08: native browser zoom, viewport reachability and rendered font evidence.
const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated Planeamento required');
const prefix=process.env.PLANNING_CHECK_PREFIX||'c08-real-zoom';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid prefix');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const report={at:new Date().toISOString(),script_sha256:sha(__filename),application_files:Object.fromEntries(['app/web/static/raw_workspace.js','app/web/static/raw_workspace.css','app/web/static/planning_typography.css'].map(p=>[p,sha(p)])),cases:[],failures:[],errors:[],result:'running'};
const executablePath=process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const extension=fs.mkdtempSync(path.join(os.tmpdir(),'planning-c08-zoom-'));
fs.writeFileSync(path.join(extension,'manifest.json'),JSON.stringify({manifest_version:3,name:'Isolated Planning Zoom Verification',version:'1.0',permissions:['tabs'],background:{service_worker:'background.js'}}));
fs.writeFileSync(path.join(extension,'background.js'),'chrome.runtime.onInstalled.addListener(() => {});');
let context;
function check(condition,detail){if(!condition)report.failures.push(detail);}
async function controls(page,selector){return page.locator(selector).evaluateAll(ns=>ns.filter(n=>n.getClientRects().length).map(n=>{
 const r=n.getBoundingClientRect(),s=getComputedStyle(n),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
 return {id:n.id||n.dataset.columnControl||n.textContent.trim().slice(0,70),tag:n.tagName,rect:r.toJSON(),font:s.fontFamily,size:s.fontSize,
  bounded:r.left>=-.6&&r.top>=-.6&&r.right<=innerWidth+.6&&r.bottom<=innerHeight+.6,hit:!!hit&&(hit===n||n.contains(hit))};
}));}
async function reachableControls(page,selector){
 const result=[];
 for(const control of await page.locator(selector).all()){
  if(!await control.isVisible())continue;
  await control.scrollIntoViewIfNeeded();
  result.push(await control.evaluate(n=>{const r=n.getBoundingClientRect(),s=getComputedStyle(n);return {id:n.id||n.textContent.trim().slice(0,70),tag:n.tagName,rect:r.toJSON(),size:s.fontSize,bounded:r.left>=-.6&&r.top>=-.6&&r.right<=innerWidth+.6&&r.bottom<=innerHeight+.6};}));
 }
 return result;
}
async function screenshot(page,name,realZoom){
 if(realZoom){const cdp=await context.newCDPSession(page);const r=await cdp.send('Page.captureScreenshot',{captureBeyondViewport:false});fs.writeFileSync(folder+'/'+name+'.png',Buffer.from(r.data,'base64'));await cdp.detach();}
 else await page.screenshot({path:folder+'/'+name+'.png'});
}
(async()=>{
for(const scenario of [{width:1440,height:1000,zoom:1},{width:1024,height:1000,zoom:1},{width:390,height:1000,zoom:1},{width:1440,height:1000,zoom:2}]){
 const key=scenario.width+'-zoom'+scenario.zoom;
 context=await chromium.launchPersistentContext('',{executablePath,headless:true,viewport:scenario.zoom===2?null:{width:scenario.width,height:scenario.height},
 args:['--no-sandbox',`--window-size=${scenario.width},${scenario.height}`,'--disable-extensions-except='+extension,'--load-extension='+extension]});
 try{
  const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker');
  for(const area of ['perfis','cantoneiras']){
   const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>report.errors.push({area,key,error:e.message}));
   await page.goto(base+'/planeamento/raw?area='+area);await page.waitForFunction(()=>window.Raw?.state.data&&document.querySelector('#count').textContent.includes('linhas'));
   await page.locator('#page-size').selectOption('500');await page.waitForFunction(()=>Raw.state.data.rows.length===500);
   const before=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,outer:outerWidth,scale:visualViewport.scale}));
   const nativeZoom=await worker.evaluate(async({url,zoom})=>{const t=(await chrome.tabs.query({})).find(t=>t.url===url);await chrome.tabs.setZoom(t.id,zoom);return chrome.tabs.getZoom(t.id);},{url:page.url(),zoom:scenario.zoom});
   await page.waitForFunction(zoom=>devicePixelRatio===zoom,scenario.zoom);
   const entry={area,key,scenario,before,nativeZoom,dimensions:await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,outer:outerWidth,scale:visualViewport.scale})),menus:[]};report.cases.push(entry);
   check(nativeZoom===scenario.zoom,{area,key,issue:'native zoom mismatch'});
   if(scenario.zoom===2)check(entry.dimensions.width===720&&entry.dimensions.outer===1440&&entry.dimensions.scale===1,{area,key,issue:'200% is not native page zoom',dimensions:entry.dimensions});
   entry.toolbar=await controls(page,'.appbar a,.appbar button,.toolbar button,.toolbar select,.toolbar input,.subbar button,.subbar select,.subbar input,.horizontal-control button,.horizontal-control input,.pager button,.pager select');
   for(const c of entry.toolbar){check(c.bounded,{area,key,issue:'control clipped',control:c});check(Math.abs(parseFloat(c.size)-14.6667)<.02,{area,key,issue:'not 11pt',control:c});}
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),{area,key,issue:'document horizontal overflow'});
   await page.locator('#open-columns').click();
   for(const group of await page.locator('.columns-group').all())await group.locator('summary input').check();
   await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
   entry.columnCount=await page.locator('#sheet th').count();
   entry.loadedRows=await page.locator('#sheet tbody tr').count();
   entry.pinsBefore=await page.evaluate(()=>[...Raw.state.pinned]);
   const slider=page.locator('#horizontal-position');await slider.focus();await slider.press('Home');
   const sr=await slider.boundingBox();await page.mouse.move(sr.x+8,sr.y+sr.height/2);await page.mouse.down();await page.mouse.move(sr.x+sr.width-1,sr.y+sr.height/2,{steps:12});await page.mouse.up();
   entry.drag=await page.locator('#grid').evaluate(n=>({x:n.scrollLeft,max:n.scrollWidth-n.clientWidth}));
   check(Math.abs(entry.drag.x-entry.drag.max)<2,{area,key,issue:'horizontal pointer drag failed',drag:entry.drag});
   await slider.focus();await slider.press('Home');
   for(const end of ['last','first']){
    await page.locator('#scroll-'+end).click();
    await page.waitForFunction(end=>{const n=document.querySelector('#grid');return end==='first'?n.scrollLeft===0:Math.abs(n.scrollLeft-(n.scrollWidth-n.clientWidth))<2;},end);
    const th=page.locator('#sheet th')[end==='first'?'first':'last']();
    entry[end]=await th.evaluate(n=>{const r=n.getBoundingClientRect(),x=Math.max(0,r.left)+Math.min(r.width,innerWidth)/2,y=r.top+r.height/2,hit=document.elementFromPoint(Math.min(innerWidth-2,x),y);return {rect:r.toJSON(),label:n.textContent,hit:!!hit&&n.contains(hit),scroll:document.querySelector('#grid').scrollLeft};});
    check(entry[end].hit,{area,key,issue:end+' column covered',column:entry[end]});
   }
   entry.columnReachability=await page.evaluate(async()=>{
    const grid=document.querySelector('#grid'),headers=[...document.querySelectorAll('#sheet th')],out=[];
    for(const th of headers){
     th.scrollIntoView({block:'nearest',inline:'center'});await new Promise(requestAnimationFrame);
     const r=th.getBoundingClientRect(),g=grid.getBoundingClientRect(),left=Math.max(r.left,g.left),right=Math.min(r.right,g.right);
     const hit=document.elementFromPoint((left+right)/2,r.top+r.height/2);
     out.push({label:th.querySelector('.label').title,visibleWidth:right-left,hit:!!hit&&th.contains(hit)});
    }
    return out;
   });
   for(const c of entry.columnReachability)check(c.visibleWidth>0&&c.hit,{area,key,issue:'column inaccessible',column:c});
   for(const button of ['open-columns','more','view-actions','formula','chat','sources']){
    await page.locator('#'+button).click();await page.locator('#drawer[open]').waitFor();
    const menu={button,controls:[]};entry.menus.push(menu);
    if(button==='open-columns'){
     await page.locator('details[data-group="identity"] summary span').click();
     const row=page.locator('[data-column-id="of"]');await row.scrollIntoViewIfNeeded();
     menu.controls=await controls(page,'[data-column-id="of"] button,[data-column-id="of"] select,[data-column-id="of"] input');
     const down=page.locator('[data-column-control="of:1"]');await down.focus();await down.press('Enter');
     check(await down.evaluate(n=>document.activeElement===n),{area,key,issue:'column move keyboard focus lost'});
     const up=page.locator('[data-column-control="of:-1"]');await up.focus();await up.press('Enter');
    }else{
     if(button==='sources')await page.getByRole('link',{name:'Consultar OCR original separadamente',exact:true}).waitFor();
     menu.controls=await reachableControls(page,'#drawer button,#drawer input,#drawer select,#drawer textarea,#drawer a');
    }
    for(const c of menu.controls)check(c.bounded,{area,key,issue:'menu control clipped',menu:button,control:c});
    await screenshot(page,prefix+'-'+area+'-'+key+'-'+button,scenario.zoom===2);
    await page.locator('#close-drawer').click();
   }
   const editable=page.locator('#sheet tbody tr').first().locator('td.editable').first();
   await editable.focus();await editable.press('Enter');await page.locator('#editor[open]').waitFor();
   entry.editor=await controls(page,'#editor input:not([hidden]),#editor select,#editor button');
   for(const c of entry.editor)check(c.bounded,{area,key,issue:'editor control clipped',control:c});
   check(await page.locator('#edit-value').evaluate(n=>n===document.activeElement),{area,key,issue:'editor input focus lost'});
   await page.locator('#cancel-edit').click();
   check(await editable.evaluate(n=>n===document.activeElement),{area,key,issue:'cell focus not restored after cancel'});
   await editable.press('ArrowRight');
   entry.keyboardCell=await page.evaluate(()=>{const n=document.activeElement,r=n.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {tag:n.tagName,column:n.dataset.col,hit:!!hit&&n.contains(hit)};});
   check(entry.keyboardCell.tag==='TD'&&entry.keyboardCell.hit,{area,key,issue:'keyboard target cell covered',cell:entry.keyboardCell});
   const range=page.locator('#horizontal-position');await range.focus();await range.press('End');await range.press('Home');
   check(await range.evaluate(n=>n===document.activeElement),{area,key,issue:'horizontal keyboard focus lost'});
   entry.pinsAfter=await page.evaluate(()=>[...Raw.state.pinned]);
   check(JSON.stringify(entry.pinsBefore)===JSON.stringify(entry.pinsAfter),{area,key,issue:'responsive pins changed saved choices'});
   const cdp=await context.newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
   const {root}=await cdp.send('DOM.getDocument');const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.nodeId,selector:'#sheet th .label'});
   entry.renderedFonts=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId})).fonts;await cdp.detach();
   await screenshot(page,prefix+'-'+area+'-'+key,scenario.zoom===2);await page.close();
  }
 }finally{await context.close();context=null;}
}
check(report.errors.length===0,{issue:'JavaScript errors',errors:report.errors});
report.renderedFontVerified=report.cases.every(c=>c.renderedFonts?.some(f=>f.glyphCount>0));
check(report.renderedFontVerified,{issue:'No rendered font evidence'});
report.requirement='11pt; substitute font accepted by user';
report.result=report.failures.length?'failed':'passed';
console.log(JSON.stringify({cases:report.cases.length,failures:report.failures.length,renderedFontVerified:report.renderedFontVerified,result:report.result}));
if(report.failures.length)process.exitCode=1;
})().catch(e=>{report.result='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{
 fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));if(context)await context.close();fs.rmSync(extension,{recursive:true,force:true});
});
