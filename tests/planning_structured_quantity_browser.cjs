const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated copy required');
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(folder+'/c04-structured-quantity-final.json','utf8'));
 const report={at:new Date().toISOString(),base,method:'Read-only browser checks every N/AH disagreement after restart; column selection and history/search use the UI.',rows:[],errors:[]};
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));
  const keys=fixture.source_disagreements.map(r=>'macro:'+r.plan_key);
  const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:'perfis',population:'history',selected:keys}});assert(response.ok());
  const api=await response.json();assert.equal(api.rows.length,keys.length);
  const rows=Object.fromEntries(api.rows.map(r=>[r.key,r]));
  await page.goto(base+'/planeamento/raw?area=perfis&q='+encodeURIComponent(api.rows[0].values.of));await page.waitForFunction(()=>Raw.state.data);
  await page.locator('#population').selectOption('history');await page.locator('#page-size').selectOption('500');
  const columns=['of','ov','component_ref','quantity_required','cut','remaining','section_total'];
  const previous=await page.evaluate(()=>Raw.state.columns);await page.locator('#open-columns').click();
  for(const id of new Set([...previous,...columns])){
   const control=page.locator('[data-column-control="'+id+':visible"]');if(await control.isChecked()===columns.includes(id))continue;
   const group=control.locator('xpath=ancestor::details');if(!await group.evaluate(n=>n.open))await group.locator('summary').click();await control.setChecked(columns.includes(id));
  }
  await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
  for(const source of fixture.source_disagreements){
   const key='macro:'+source.plan_key,expected=rows[key].values;
   await page.locator('#search').fill(expected.of);await page.locator('#search').press('Enter');
   await page.waitForFunction(({key,of})=>Raw.state.q===of&&Raw.state.data?.rows.some(r=>r.key===key),{key,of:expected.of});
   await page.waitForFunction(()=>document.getElementById('notice').textContent!=='A consultar…');
   const visible=await page.evaluate(key=>{
    const i=Raw.state.data.rows.findIndex(r=>r.key===key),row=document.querySelector('#sheet tbody').rows[i];
    return Object.fromEntries(['quantity_required','section_total'].map(field=>[field,row.cells[Raw.state.columns.indexOf(field)].textContent]));
   },key);
   const display=n=>new Intl.NumberFormat('pt-PT',{maximumFractionDigits:4}).format(n).replace(/\s/g,'');
   assert.equal(visible.quantity_required.replace(/\s/g,''),display(source.expected));
   assert.equal(visible.section_total.replace(/\s/g,''),display(source.cached_AP));
   assert.equal(rows[key].raw.QTD,Number(source.legacy_N));assert.equal(rows[key].raw['QTD [un,]'],source.structured_AH);
   assert.equal(expected.planning_active,false);
   report.rows.push({key,of:expected.of,reference:expected.component_ref,excel_row:source.excel_row,legacy_N:source.legacy_N,expected_AH:source.expected,expected_AP:source.cached_AP,visible});
   if(source.excel_row===43)await page.screenshot({path:folder+'/c04-structured-quantity-browser.png',fullPage:true});
  }
  assert.deepEqual(report.errors,[]);report.result='passed';console.log(report.rows.length,'historical rows: quantity AH and area AP visible; original N preserved');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/c04-structured-quantity-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
