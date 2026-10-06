// C07: real browser layout actions; fixtures and writes restricted to port 18113.
const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Use the isolated Planeamento service only');
const folder='docs/validacao-planeamento-integral/20260923-execucao';
const prefix=process.env.PLANNING_CHECK_PREFIX||'c07-complete-browser';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid output prefix');
const fixture=JSON.parse(fs.readFileSync(folder+'/c07-complete-fixture.json'));
const layoutKeys=['columns','column_order','column_groups','pinned','widths'];
const report={at:new Date().toISOString(),base,areas:{},errors:[],requests:[],result:'running'};
const run=Date.now();
let browser;
async function loaded(page,area){
 await page.waitForFunction(area=>window.Raw?.state.data&&Raw.state.area===area&&document.querySelector('#count').textContent.includes('linhas'),area);
}
async function layout(page){return page.evaluate(()=>{const c=Raw.config();return Object.fromEntries(['columns','column_order','column_groups','pinned','widths'].map(k=>[k,c[k]]));});}
async function grid(page,expected){
 const observed=await page.locator('#sheet th .label').evaluateAll(nodes=>nodes.map(n=>n.title));
 const labels=await page.evaluate(()=>Object.fromEntries(Raw.state.fields.map(f=>[f.id,f.label])));
 assert.deepEqual(observed,expected.map(k=>labels[k]));
}
async function openGroup(page,id){
 const group=page.locator(`details[data-group="${id}"]`);
 if(!await group.evaluate(n=>n.open))await group.locator('summary span').click();
 return group;
}
async function reset(page,area){
 await page.locator('#open-columns').click();
 await page.getByRole('button',{name:'Repor vista de '+(area==='perfis'?'Perfis':'Cantoneiras'),exact:true}).click();
 await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
}
async function selectView(page,id){
 const response=page.waitForResponse(r=>r.url().endsWith('/raw/consultas')&&r.request().method()==='POST');
 await page.locator('#views').selectOption(id);assert.equal((await response).status(),200);
 await page.waitForFunction(id=>Raw.state.view?.id===id,id);
 await page.waitForFunction(()=>!document.querySelector('#drawer').open);
}
async function nativeDrag(page,source,target,last){
 // dragTo scrolls both distant elements before pressing: in a long dialog that
 // can put another row under its cached source point. Start before scrolling.
 await source.scrollIntoViewIfNeeded();const start=await source.boundingBox();
 await page.mouse.move(start.x+5,start.y+5);await page.mouse.down();
 await page.mouse.move(start.x+15,start.y+15,{steps:3});
 await target.scrollIntoViewIfNeeded();const end=await target.boundingBox();
 await page.mouse.move(end.x+5,end.y+(last?end.height-2:2),{steps:5});
 await page.mouse.move(end.x+6,end.y+(last?end.height-2:2));await page.mouse.up();
}
(async()=>{
 browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(e.message));
 page.on('request',r=>{if(r.method()!=='GET')report.requests.push({method:r.method(),url:r.url()});});
 for(const area of ['perfis','cantoneiras']){
  const result=report.areas[area]={steps:[],arrow_moves:[],resize:[]};
  await page.goto(base+'/planeamento/raw?area='+area);await loaded(page,area);
  const url=page.url(),initial=await layout(page);
  const catalog=await (await page.request.get(base+'/planeamento/api/raw/colunas?area='+area)).json();
  const expectedIds=catalog.columns.map(f=>f.id);
  await page.locator('#open-columns').click();await openGroup(page,'identity');
  for(const id of ['of','ov','component_ref']){
   await page.locator(`[data-column-control="${id}:pin"]`).click();
   assert(!await page.locator(`[data-column-control="${id}:pin"]`).getAttribute('aria-label').then(x=>x.startsWith('Desafixar')));
  }
  assert.equal(await page.locator('#sheet th.fixed').count(),0);
  for(const searching of [false,true]){
   await page.getByLabel('Procurar uma coluna',{exact:true}).fill(searching?'o':'');
   for(let round=0;round<10;round++)for(const delta of [1,-1]){
    const control=page.locator(`[data-column-control="of:${delta}"]`);
    await control.focus();
    await page.locator('#drawer').evaluate(n=>{n.scrollTop=40;});
    const before=await page.evaluate(()=>({scroll:document.querySelector('#drawer').scrollTop,order:[...Raw.state.column_order]}));
    const displayed=await page.locator('details[data-group=identity] [data-column-id]').evaluateAll(ns=>ns.map(n=>n.dataset.columnId));
    const destination=displayed[displayed.indexOf('of')+delta];assert(destination,'Every arrow activation must move a column');
    const expected=before.order.filter(x=>x!=='of'),index=expected.indexOf(destination)+(delta>0?1:0);expected.splice(index,0,'of');
    await control.press('Enter');
    const after=await page.evaluate(()=>({scroll:document.querySelector('#drawer').scrollTop,order:Raw.state.column_order,focus:document.activeElement.dataset.columnControl,open:document.querySelector('details[data-group=identity]').open}));
    assert.deepEqual(after.order,expected);assert.equal(after.scroll,before.scroll);assert(before.scroll>0);
    assert.equal(after.focus,'of:'+delta);assert(after.open);assert.equal(page.url(),url);
    result.arrow_moves.push({searching,delta,before,after});
   }
  }
  await page.getByLabel('Procurar uma coluna',{exact:true}).fill('');
  // Make all contract columns visible, then prove order against rendered headers.
  for(const group of await page.locator('details[data-group]').all())await group.locator('summary input').check();
  assert.deepEqual((await page.locator('[data-column-id]').evaluateAll(ns=>ns.map(n=>n.dataset.columnId))).sort(),[...expectedIds].sort());
  let expected=(await layout(page)).column_order;
  assert.equal(new Set(expected).size,expectedIds.length);await grid(page,expected);
  // Native drag events, crossing groups, to both the first and last position.
  await openGroup(page,'production');await openGroup(page,'identity');
  await page.evaluate(()=>{window.columnDragTrace=[];for(const name of ['dragstart','drop','dragend'])document.addEventListener(name,e=>window.columnDragTrace.push({type:e.type,id:e.target.closest('[data-column-id]')?.dataset.columnId,trusted:e.isTrusted,x:e.clientX,y:e.clientY}),true);});
  for(const last of [false,true]){
   const targets=await page.locator('details[data-group=production] [data-column-id]').evaluateAll(ns=>ns.map(n=>n.dataset.columnId).filter(x=>x!=='of'));
   const targetId=last?targets.at(-1):targets[0];
   const target=page.locator(`[data-column-id="${targetId}"]`),source=page.locator('[data-column-id=of]');
   await nativeDrag(page,source,target,last);
   result.drag_trace=await page.evaluate(()=>window.columnDragTrace);
   expected=expected.filter(x=>x!=='of');expected.splice(expected.indexOf(targetId)+(last?1:0),0,'of');
   assert.deepEqual((await layout(page)).column_order,expected);
   assert.equal(await page.locator('details[data-group=production] [data-column-id=of]').count(),1);
   await grid(page,expected);result.steps.push('native drag '+(last?'last':'first'));
  }
  // Preserve a non-default group and a hidden field in the saved layout.
  await page.locator('[data-column-control="notes:visible"]').uncheck();
  expected=expected.filter(x=>x!=='notes');await grid(page,expected);
  await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
  const handle=page.getByRole('separator',{name:'Largura de OV',exact:true});
  await handle.scrollIntoViewIfNeeded();const box=await handle.boundingBox();
  const beforeWidth=await handle.evaluate(n=>n.parentElement.getBoundingClientRect().width);
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+37,box.y+box.height/2,{steps:5});await page.mouse.up();
  const pointerWidth=await handle.evaluate(n=>n.parentElement.getBoundingClientRect().width);
  assert(Math.abs(pointerWidth-beforeWidth-37)<1);result.resize.push({method:'pointer',beforeWidth,afterWidth:pointerWidth});
  await handle.focus();await handle.press('ArrowRight');
  assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),'Largura de OV');
  const keyboardWidth=await handle.evaluate(n=>n.parentElement.getBoundingClientRect().width);
  assert(Math.abs(keyboardWidth-pointerWidth-10)<1);result.resize.push({method:'keyboard',beforeWidth:pointerWidth,afterWidth:keyboardWidth});
  const savedLayout=await layout(page);result.layout=savedLayout;
  await page.reload();await loaded(page,area);assert.deepEqual(await layout(page),savedLayout);await grid(page,savedLayout.columns);
  await page.locator('#open-columns').click();assert.equal(await page.locator('details[data-group=production] [data-column-id=of]').count(),1);
  await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
  await page.locator('#view-actions').click();await page.getByLabel('Nome da vista',{exact:true}).fill('C07 complete '+area+' '+run);
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/raw/objects/view')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Criar vista',exact:true}).click();const saved=await (await saveResponse).json();
  await page.waitForFunction(()=>!document.querySelector('#drawer').open);result.saved=saved;
  for(const k of layoutKeys)assert.deepEqual(saved.definition[k],savedLayout[k]);
  await page.screenshot({path:folder+'/'+prefix+'-'+area+'.png',fullPage:true});
  // A new browser context proves server persistence independent of localStorage.
  const fresh=await browser.newContext({viewport:{width:1440,height:1000}}),other=await fresh.newPage();
  other.on('pageerror',e=>report.errors.push(e.message));
  await other.goto(base+'/planeamento/raw?area='+area);await loaded(other,area);await selectView(other,saved.id);
  assert.deepEqual(await layout(other),savedLayout);await grid(other,savedLayout.columns);result.steps.push('saved view recovered in fresh context');
  // Load genuine old JSON stored without column_order/pinned/groups/population.
  await selectView(other,fixture.views[area].id);
  const legacy=await layout(other);result.legacy=legacy;
  assert.deepEqual(legacy.columns,catalog.columns.filter(f=>f.group!=='technical').map(f=>f.id));
  assert.deepEqual(legacy.pinned,['of','ov','component_ref']);assert.equal(legacy.widths.of,177);
  await grid(other,legacy.columns);
  assert.equal(await other.evaluate(()=>Raw.state.population),'active');
  await reset(other,area);
  const resetLayout=await layout(other);result.reset=resetLayout;
  assert.deepEqual(resetLayout.columns,catalog.default_columns);assert.deepEqual(resetLayout.widths,catalog.default_widths);
  assert.deepEqual(resetLayout.column_groups,{});assert.deepEqual(resetLayout.pinned,['of','ov','component_ref']);
  await grid(other,resetLayout.columns);
  await other.reload();await loaded(other,area);assert.deepEqual(await layout(other),resetLayout);
  await fresh.close();result.steps.push('legacy view and persisted reset');
  assert.notDeepEqual(savedLayout,initial);
 }
 // Switching areas in one page must recover each independent local layout.
 for(const area of ['perfis','cantoneiras']){
  const response=page.waitForResponse(r=>r.url().endsWith('/raw/consultas')&&r.request().postDataJSON()?.area===area);
  await page.locator('#area').selectOption(area);await response;await loaded(page,area);
  assert.deepEqual(await layout(page),report.areas[area].layout);
 }
 assert.deepEqual(report.errors,[]);
 assert(report.requests.every(x=>x.url.startsWith(base+'/planeamento/api/raw/consultas')||x.url.startsWith(base+'/planeamento/api/raw/objects/view')));
 report.result='passed';console.log('C07 complete: both areas, 80 real arrow moves, native drag, widths, old/saved views, reset and area separation passed.');
})().catch(e=>{report.result='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{
 fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));if(browser)await browser.close();
});
