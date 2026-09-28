const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated planning copy required');
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(folder+'/c04-imported-lengths-final.json','utf8'));
 assert.equal(fixture.result,'passed_in_stated_scope');
 const report={at:new Date().toISOString(),base,apiRows:0,samples:[],errors:[]};
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 let page;
 try{
  page=await browser.newPage({viewport:{width:1600,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));
  const sources=fixture.rows.filter(r=>r.expected_length!==null&&!r.need_id);
  const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:'cantoneiras',population:'all',selected:sources.map(r=>r.key),page_size:500}});
  assert(response.ok());const api=await response.json();assert.equal(api.rows.length,sources.length);
  const byKey=Object.fromEntries(api.rows.map(r=>[r.key,r]));
  for(const source of sources){
   const row=byKey[source.key];assert.equal(row.values.length_mm,source.expected_length);
   assert.equal(row.raw['Comp.'],source.original);
   assert.equal(row.values.total_length,source.quantity*source.expected_length);
   report.apiRows++;
  }
  // Select actual source states; do not manufacture production or closure
  // merely to populate a browser fixture.
  const samples=[sources[0],sources[Math.floor(sources.length/2)],sources.at(-1)];
  assert.equal(new Set(samples.map(r=>r.key)).size,3);
  await page.goto(base+'/planeamento/raw?area=cantoneiras');await page.waitForFunction(()=>Raw.state.data);
  await page.locator('#population').selectOption('all');await page.locator('#page-size').selectOption('500');
  const columns=['of','ov','component_ref','quantity_required','length_mm','total_length','remaining','remaining_m'];
  const previous=await page.evaluate(()=>Raw.state.columns);await page.locator('#open-columns').click();
  for(const id of new Set([...previous,...columns])){
   const control=page.locator('[data-column-control="'+id+':visible"]');if(await control.isChecked()===columns.includes(id))continue;
   const group=control.locator('xpath=ancestor::details');if(!await group.evaluate(n=>n.open))await group.locator('summary').click();await control.setChecked(columns.includes(id));
  }
  await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
  for(const source of samples){
   await page.locator('#search').fill(source.of);await page.locator('#search').press('Enter');
   await page.waitForFunction(of=>Raw.state.q===of&&Raw.state.data?.rows.length&&document.getElementById('notice').textContent!=='A consultar…',source.of);
   while(!await page.evaluate(key=>Raw.state.data.rows.some(r=>r.key===key),source.key)){
    assert(!await page.locator('#next').isDisabled(),'Source piece is present in paginated search');
    const previous=await page.evaluate(()=>Raw.state.data.page);
    await page.locator('#next').click();
    await page.waitForFunction(previous=>Raw.state.data.page!==previous&&document.getElementById('notice').textContent!=='A consultar…',previous);
   }
   const index=await page.evaluate(key=>Raw.state.data.rows.findIndex(r=>r.key===key),source.key);
   const tr=page.locator('#sheet tbody tr').nth(index);
   const display=n=>new Intl.NumberFormat('pt-PT',{maximumFractionDigits:4}).format(n).replace(/\s/g,'');
   for(const field of ['length_mm','total_length']){
    const position=await page.evaluate(field=>Raw.state.columns.indexOf(field),field);
    assert.equal((await tr.locator('td').nth(position).innerText()).replace(/\s/g,''),display(byKey[source.key].values[field]));
   }
   await tr.locator('.row-action').click();
   await page.locator('#drawer').getByRole('button',{name:'Cálculos',exact:true}).click();
   const heading=page.locator('#drawer').getByRole('columnheader',{name:'Motivo de indisponibilidade',exact:true});await heading.waitFor();
   const reasonRows=[];
   for(const [field,rule] of Object.entries(byKey[source.key].calculation.rules)){
    if(!rule.reason)continue;
    const label=await page.evaluate(field=>Raw.state.fields.find(f=>f.id===field)?.label||field,field);
    const row=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:label,exact:true})});
    await row.getByRole('cell',{name:rule.reason,exact:true}).waitFor();reasonRows.push({field,reason:rule.reason});
   }
   assert(reasonRows.length>0,'Unavailable results expose their reasons');
   report.samples.push({key:source.key,of:source.of,excel_row:source.excel_row,original:source.original,length:source.expected_length,total:byKey[source.key].values.total_length,reasonRows});
   if(report.samples.length===1)await page.screenshot({path:folder+'/c04-imported-lengths-reasons-browser.png',fullPage:true});
   await page.locator('#close-drawer').click();
  }
  assert.deepEqual(report.errors,[]);report.result='passed';console.log(report.apiRows,'grouped lengths verified in API;',report.samples.length,'UI samples including visible unavailability reasons');
 }catch(e){report.failure={message:e.message,stack:e.stack};if(page){report.drawer=await page.locator('#drawer').innerText();await page.screenshot({path:folder+'/c04-imported-lengths-browser-failure.png',fullPage:true});}throw e;}
 finally{fs.writeFileSync(folder+'/c04-imported-lengths-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
