// Read-only acceptance at the published Planning address. No production edits.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_PUBLIC_BASE,F=process.env.PLANNING_PUBLIC_EVIDENCE_DIR||'docs/separacao-2026-09-24';
fs.mkdirSync(F,{recursive:true});
if(!base||(!base.startsWith('https://')&&base!=='http://127.0.0.1:8113'))throw Error('Explicit published address required');
const report={at:new Date().toISOString(),base,mode:'Read-only browser; column changes stay in this browser session',areas:[],pages:[],errors:[],console_errors:[],request_failures:[],network_retries:[]};let browser;
async function navigate(page,url){for(let attempt=1;attempt<=3;attempt++){try{return await page.goto(url)}catch(e){if((!String(e).includes('net::ERR_NETWORK_CHANGED')&&!String(e).includes('chrome-error://chromewebdata/'))||attempt===3)throw e;report.network_retries.push({url,attempt,error:e.message});await page.waitForTimeout(250);}}}
(async()=>{
 browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.console_errors.push(m.text())});page.on('requestfailed',r=>report.request_failures.push({url:r.url(),error:r.failure()?.errorText}));
 for(const area of ['perfis','cantoneiras']){
  console.log('Checking area',area);
  const response=await navigate(page,base+'/planeamento/raw?area='+area);assert.equal(response.status(),200);
  await page.waitForFunction(()=>window.Raw?.state.data?.rows.length>0&&!Raw.state.data.aggregates_pending&&!Raw.state.data.source_refresh_pending,null,{timeout:180000});
  console.log('Loaded area',area);
  const active=await page.evaluate(()=>({version:Raw.state.data.version,total:Raw.state.data.total,valid:Raw.state.data.rows.every(r=>r.values.planning_active===true)}));assert(active.valid);
  await page.locator('#population').selectOption('history');await page.waitForFunction(()=>Raw.state.data.population==='history'&&Raw.state.data.rows.length>0);
  const history=await page.evaluate(()=>({total:Raw.state.data.total,valid:Raw.state.data.rows.every(r=>r.values.planning_active===false)}));assert(history.valid);
  await page.locator('#population').selectOption('all');await page.waitForFunction(()=>Raw.state.data.population==='all');
  const all=await page.evaluate(()=>Raw.state.data.total);assert.equal(all,active.total+history.total);
  await page.locator('#open-columns').click();
  const of=page.locator('[data-column-id="of"]'),group=of.locator('xpath=ancestor::details[1]');if(!await group.evaluate(n=>n.open))await group.locator('summary').click();
  const order=await page.evaluate(()=>[...Raw.state.column_order]);
  const down=of.getByRole('button',{name:'↓',exact:true});await down.click();assert.equal(await group.evaluate(n=>n.open),true);
  await of.getByRole('button',{name:'↑',exact:true}).click();assert.deepEqual(await page.evaluate(()=>Raw.state.column_order),order);
  // Cantoneiras' compact initial columns fit 1440px. Show all columns to exercise overflow.
  for(const section of await page.locator('.columns-group').all())await section.locator('summary input').check();
  await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
  // A focus operation can leave the grid at its last column. Establish the starting edge.
  if(await page.locator('#scroll-first').isEnabled())await page.locator('#scroll-first').click();
  assert.equal(await page.locator('#grid').evaluate(n=>n.scrollLeft),0);
  await page.locator('#scroll-last').click();const last=await page.locator('#grid').evaluate(n=>({left:n.scrollLeft,max:n.scrollWidth-n.clientWidth}));assert(last.max>0&&Math.abs(last.left-last.max)<3);
  await page.locator('#scroll-first').click();assert.equal(await page.locator('#grid').evaluate(n=>n.scrollLeft),0);
  const size=await page.locator('#sheet td').first().evaluate(n=>getComputedStyle(n).fontSize);assert(Math.abs(parseFloat(size)-14.6667)<.03);
  await page.locator('#sources').click();await page.locator('#drawer-body').getByText('Atualizar lista consulta os dados disponíveis. Não força a leitura direta do CPIS.',{exact:true}).waitFor();assert.equal(await page.locator('#drawer-body table').count(),3);await page.screenshot({path:F+'/published-sources-'+area+'.png',fullPage:true});await page.locator('#close-drawer').click();
  const sources=await page.evaluate(async()=>{const r=await fetch('/planeamento/api/raw/workspace/fontes');return (await r.json()).sources.filter(x=>['perfis','cantoneiras','capacity','documents'].includes(x.source))});assert.equal(sources.length,4);assert(sources.every(x=>x.available&&!x.stale&&!x.error));
  const row={area,active,history,total:all,scroll:last,font_size:size,sources};
  if(area==='perfis'){
   await page.locator('#search').fill('OF264774');await page.locator('#search-form').evaluate(n=>n.requestSubmit());
   await page.waitForFunction(()=>Raw.state.q==='OF264774'&&Raw.state.data.rows.length&&Raw.state.data.rows.every(r=>r.values.of==='OF264774'));
   row.OF264774=await page.evaluate(()=>Raw.state.data.rows.map(r=>({key:r.key,revision:r.revision,values:r.values,contract:r.calculation.contract})));
  }
  await page.screenshot({path:F+'/published-raw-'+area+'.png',fullPage:true});report.areas.push(row);
 }
 for(const path of ['/planeamento','/planeamento/manual?area=perfis','/planeamento/manual?area=cantoneiras','/planeamento/capacidades?area=perfis']){
  const response=await navigate(page,base+path);assert.equal(response.status(),200);await page.waitForLoadState('networkidle');
  const style=await page.locator('body').evaluate(n=>({size:getComputedStyle(n).fontSize,family:getComputedStyle(n).fontFamily}));assert(Math.abs(parseFloat(style.size)-14.6667)<.03);
  await page.locator('body a,body button,body label').first().evaluate(n=>n.dataset.fontProbe='true');
  const session=await page.context().newCDPSession(page);await session.send('DOM.enable');await session.send('CSS.enable');const {root}=await session.send('DOM.getDocument');const {nodeId}=await session.send('DOM.querySelector',{nodeId:root.nodeId,selector:'[data-font-probe]'});const fonts=await session.send('CSS.getPlatformFontsForNode',{nodeId});await session.detach();assert(fonts.fonts.some(x=>x.glyphCount>0));
  report.pages.push({path,...style,fonts:fonts.fonts});
 }
 assert.deepEqual(report.errors,[]);report.result='passed';console.log('Passed published browser');
})().catch(e=>{report.result='failed';report.error=e.stack;console.error(e);process.exitCode=1;}).finally(async()=>{fs.writeFileSync(F+'/public-browser.json',JSON.stringify(report,null,2));if(browser)await browser.close();});
