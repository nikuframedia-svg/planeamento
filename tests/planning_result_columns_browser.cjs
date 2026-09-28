const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated planning copy required');
(async()=>{
 const fixtures=JSON.parse(fs.readFileSync(folder+'/c04-result-columns-fixture.json','utf8'));
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,scope:'All eight newly exposed result columns, exact/absent weight samples, derived values and readonly UI. Source selection remains a separate gate.',samples:[],errors:[]};let page;
 const display=n=>n===null?'—':new Intl.NumberFormat('pt-PT',{maximumFractionDigits:4}).format(n).replace(/\s/g,'');
 const same=(a,b)=>a===null||b===null?assert.equal(a,b):assert(Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-8));
 try{
  page=await browser.newPage({viewport:{width:1600,height:1100}});page.on('pageerror',e=>report.errors.push(e.message));
  for(const fixture of fixtures){
   const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:fixture.area,population:'all',selected:[fixture.key]}});
   assert(response.ok());const data=await response.json();assert.equal(data.rows.length,1);const row=data.rows[0],v=row.values;
   const q=v.quantity_required,p=v[fixture.area==='perfis'?'cut':'made'];
   const balance=q===null||p===null?null:Math.max(q-p,0);
   const expected={weight_unit:fixture.expected_weight_unit,total_m:q===null||v.length_mm===null?null:q*v.length_mm/1000,production_excess:q===null||p===null?null:Math.max(p-q,0)};
   if(fixture.area==='perfis')expected.section_pending=balance===0?0:balance===null?null:balance*fixture.weight_inputs.area;
   else{
    const code=String(v.operation_detail??'').trim();
    const source=row.calculation.production_sources.find(r=>r.operation===code);
    expected.secondary_remaining=!code||code==='0'?0:q===null||source?.value==null?null:Math.max(q-source.value,0);
   }
   const fields=Object.fromEntries(data.columns.map(f=>[f.id,f]));
   for(const [field,value] of Object.entries(expected)){
    assert(fields[field]&&!fields[field].editable);assert.equal(fields[field].data_type,'number');same(v[field],value);
    assert.equal(fields[field].unit,({weight_unit:'kg',total_m:'m',production_excess:'un.',section_pending:'mm²',secondary_remaining:'un.'})[field]);
   }
   await page.goto(base+'/planeamento/raw?area='+fixture.area+'&q='+encodeURIComponent(fixture.reference));await page.waitForFunction(()=>Raw.state.data);
   await page.locator('#population').selectOption('all');await page.locator('#page-size').selectOption('500');
   const columns=['of','ov','component_ref',...Object.keys(expected)],previous=await page.evaluate(()=>Raw.state.columns);
   await page.locator('#open-columns').click();
   for(const id of new Set([...previous,...columns])){
    const control=page.locator('[data-column-control="'+id+':visible"]');if(await control.isChecked()===columns.includes(id))continue;
    const group=control.locator('xpath=ancestor::details');if(!await group.evaluate(n=>n.open))await group.locator('summary').click();await control.setChecked(columns.includes(id));
   }
   await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
   await page.waitForFunction(()=>Raw.state.data?.rows.length&&document.getElementById('notice').textContent!=='A consultar…');
   while(!await page.evaluate(key=>Raw.state.data.rows.some(r=>r.key===key),fixture.key)){
    assert(!await page.locator('#next').isDisabled());const previous=await page.evaluate(()=>Raw.state.data.page);
    await page.locator('#next').click();await page.waitForFunction(previous=>Raw.state.data.page!==previous&&document.getElementById('notice').textContent!=='A consultar…',previous);
   }
   const index=await page.evaluate(key=>Raw.state.data.rows.findIndex(r=>r.key===key),fixture.key),tr=page.locator('#sheet tbody tr').nth(index);
   for(const [field,value] of Object.entries(expected)){
    const position=await page.evaluate(field=>Raw.state.columns.indexOf(field),field);
    assert.equal((await tr.locator('td').nth(position).innerText()).replace(/\s/g,''),display(value));
   }
   const position=await page.evaluate(()=>Raw.state.columns.indexOf('weight_unit'));
   await tr.locator('td').nth(position).dblclick(); // A derived cell opens evidence, not the editor.
   assert(!await page.locator('#editor').evaluate(n=>n.open));
   await page.locator('#drawer').getByRole('button',{name:'Cálculos',exact:true}).click();
   await page.locator('#drawer').getByRole('columnheader',{name:'Valor atual',exact:true}).waitFor();
   for(const [field,value] of Object.entries(expected)){
    const resultRow=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:fields[field].label,exact:true})});
    await resultRow.scrollIntoViewIfNeeded();
    assert.equal((await resultRow.locator('td').nth(1).innerText()).replace(/\s/g,''),display(value));
   }
   const text=await page.locator('#drawer').innerText();
   if(expected.weight_unit===null)assert(text.includes('Sem peso exato ou comprimento conhecido.'));
   const weightRow=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:fields.weight_unit.label,exact:true})});
   const visibleSource=await weightRow.locator('td').nth(4).innerText();
   if(fixture.area==='cantoneiras'&&expected.weight_unit!==null){
    assert(visibleSource.includes('Tabela pesos!'+fixture.justification.exact_table_entries[0].property.cell));
    assert(visibleSource.includes('15,1 kg/m'));
   }
   if(fixture.area==='perfis')assert(visibleSource.includes('7850'));
   report.samples.push({...fixture,expected,columns:Object.keys(expected),readonly:true,visibleValuesVerified:true,visibleSource});
   await page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:fields.weight_unit.label,exact:true})}).scrollIntoViewIfNeeded();
   await page.screenshot({path:folder+'/c04-result-columns-'+fixture.area+(fixture.expected_weight_unit===null?'-unknown':'-known')+'.png',fullPage:true});
   if(fixture.area==='cantoneiras'){
    await page.locator('#drawer').getByRole('button',{name:'Dados e origem',exact:true}).click();
    const imported=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:fields.weight_unit.label,exact:true})});
    await imported.scrollIntoViewIfNeeded();
    assert.equal((await imported.locator('td').nth(1).innerText()).replace(/\s/g,''),display(fixture.expected_weight_unit));
    assert.equal((await imported.locator('td').nth(2).innerText()).replace(/\s/g,''),display(fixture.cached_excel));
    report.samples.at(-1).importedWeightVisible=fixture.cached_excel;
    await page.screenshot({path:folder+'/c04-result-columns-cantoneiras'+(fixture.expected_weight_unit===null?'-unknown':'-known')+'-origin.png',fullPage:true});
   }
  }
  assert.deepEqual(report.errors,[]);report.result='passed';console.log('Eight result fields accessible in both areas; grid/detail values and readonly behavior passed for',report.samples.length,'samples');
 }catch(e){report.failure={message:e.message,stack:e.stack};if(page)await page.screenshot({path:folder+'/c04-result-columns-failure.png',fullPage:true});throw e;}
 finally{fs.writeFileSync(folder+'/c04-result-columns-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
