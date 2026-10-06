const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
const output=process.env.PLANNING_CHECK_OUTPUT || 'docs/validacao-planeamento-integral/20260923-execucao';
if(!base || !process.env.PLANNING_TEST_ISOLATED) throw Error('An explicitly isolated server is required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],report={base,areas:{}};
  page.on('pageerror',e=>errors.push(e.message));
  for(const area of ['perfis','cantoneiras']){
   await page.goto(base+'/planeamento/raw?area='+area);
   await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('linhas'));
   const url=page.url();
   await page.locator('#open-columns').click();
   const group=page.locator('details[data-group=identity]');
   await group.locator('summary').click();
   const row=page.locator('[data-column-id=of]');
   await row.getByRole('button',{name:'Desafixar OF',exact:true}).click();
   assert.equal(await page.locator('#sheet th.fixed').count(),2);
   for(const searching of [false,true]){
    await page.getByLabel('Procurar uma coluna',{exact:true}).fill(searching?'o':'');
    const arrows=row.getByRole('button',{name:'↓',exact:true});
    for(let i=0;i<10;i++){
     await arrows.click();
     assert.equal(await group.evaluate(n=>n.open),true);
     assert.equal(page.url(),url);
     assert.equal(await page.evaluate(()=>document.activeElement.dataset.columnControl),'of:1');
    }
    for(let i=0;i<10;i++){
     await row.getByRole('button',{name:'↑',exact:true}).click();
     assert.equal(await group.evaluate(n=>n.open),true);
     assert.equal(page.url(),url);
     assert.equal(await page.evaluate(()=>document.activeElement.dataset.columnControl),'of:-1');
    }
   }
   await page.getByLabel('Procurar uma coluna',{exact:true}).fill('');
   await row.getByRole('combobox',{name:'Grupo de OF',exact:true}).selectOption('quantity');
   assert.equal(await page.locator('details[data-group=quantity] [data-column-id=of]').count(),1);
   const dataTransfer=await page.evaluateHandle(()=>new DataTransfer());
   await row.dispatchEvent('dragstart',{dataTransfer});
   await page.locator('details[data-group=identity] [data-column-id=ov]').dispatchEvent('drop',{dataTransfer,clientY:0});
   assert.equal(await page.locator('details[data-group=identity] [data-column-id=of]').count(),1);
   assert.equal(await page.evaluate(()=>Raw.state.column_order.indexOf('of')+1===Raw.state.column_order.indexOf('ov')),true);
   await row.dispatchEvent('dragstart',{dataTransfer});
   await page.locator('details[data-group=identity] [data-column-id=component_ref]').dispatchEvent('drop',{dataTransfer,clientY:0});
   assert.equal(await page.evaluate(()=>Raw.state.column_order.indexOf('of')+1===Raw.state.column_order.indexOf('component_ref')),true);
   const config=await page.evaluate(()=>Raw.config());
   assert.equal(new Set(config.column_order).size,config.column_order.length);
   assert.equal(config.column_order.length,await page.locator('.column-row').count());
   await page.getByRole('button',{name:'Aplicar e fechar'}).click();
   await page.reload();await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('linhas'));
   assert.deepEqual(await page.evaluate(()=>Raw.state.columns),config.columns);
   assert.deepEqual(await page.evaluate(()=>Raw.state.pinned),config.pinned);
   await page.locator('#view-actions').click();
   await page.getByLabel('Nome da vista',{exact:true}).fill('C07 '+area);
   await page.getByRole('button',{name:'Criar vista',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Vista guardada'));
   const saved=await page.evaluate(()=>Raw.state.views.find(v=>v.name==='C07 '+Raw.state.area));
   assert.deepEqual(saved.definition.column_order,config.column_order);
   assert.deepEqual(saved.definition.pinned,config.pinned);
   await page.locator('#open-columns').click();
   await page.screenshot({path:output+'/c07-'+area+'.png',fullPage:true});
   report.areas[area]={config,saved};
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(output+'/c07-browser.json',JSON.stringify(report,null,2));
  console.log('C07: arrows, focus, groups, URL, drag, unpinning and persistence passed in both areas');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
