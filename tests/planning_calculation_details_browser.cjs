const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
const prefix=process.env.PLANNING_PROOF||'c04-derived-details-browser';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1'||!/^c04-[a-z-]+$/.test(prefix))throw Error('Isolated planning proof required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),cases:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  for(const [area,q,key] of [['perfis','CI5421A3004','macro:mtg2_bf1cd6a25986791e:plan:5589'],['cantoneiras','C03-cantoneiras-2','5881f704-89c8-4e16-81e9-6d7797a0a436']]){
   await page.goto(base+'/planeamento/raw?area='+area+'&q='+encodeURIComponent(q));
   await page.waitForFunction(()=>Raw.state.data);
   await page.locator('#population').selectOption('all');await page.locator('#page-size').selectOption('500');
   await page.waitForFunction(key=>Raw.state.data?.population==='all'&&Raw.state.data.rows.some(r=>r.key===key)&&document.querySelector('#notice').textContent==='',key);
   const data=await page.evaluate(key=>({index:Raw.state.data.rows.findIndex(r=>r.key===key),ofColumn:Raw.state.columns.indexOf('of'),row:Raw.state.data.rows.find(r=>r.key===key),fields:Raw.state.fields,version:Raw.state.data.version}),key);
   assert.equal(data.row.calculation.contract,'planning-integral-20260923-v5');
   await page.locator('#sheet tbody tr').nth(data.index).locator('td').nth(data.ofColumn).dblclick();
   await page.locator('#drawer').getByRole('button',{name:'Cálculos',exact:true}).click();
   const details={};
   for(const field of ['remaining','production_excess','quantity_to_plan','total_m','section_unit','section_total','section_pending','stock_length_mm','bars','weight_unit','weight','expected_week','expected_year',...(area==='perfis'?['cut','boc','cut_pct','boc_pct','boc_remaining','final_pct']:['made','made_pct','secondary_remaining','ocr_quantity'])]){
    const label=data.fields.find(f=>f.id===field)?.label || ({section_unit:'Área unitária (mm²)',section_total:'Área total (mm²)',section_pending:'Área pendente (mm²)',bars:'Perfis inteiros necessários (un.)',expected_year:'Ano ISO previsto'})[field] || field;
    const tr=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:label,exact:true})});
    await tr.scrollIntoViewIfNeeded();const cells=await tr.locator('td').allTextContents();
    assert.ok(cells[3].length>1);assert.ok(!cells[3].includes('[object Object]'),'Nested inputs must be readable: '+cells[3]);
    if(data.row.values[field]!=null) assert.notEqual(cells[4],'—',field);
    if(data.row.values[field]==null) assert.notEqual(cells[5],'—',field+' unavailable reason');
    details[field]={inputs:cells[3],source:cells[4],value:cells[1]};
   }
   assert.ok(details.quantity_to_plan.inputs.includes('Produção selecionada (un.)='));
   assert.ok(details.total_m.inputs.includes('Comprimento da peça (mm)='));
   assert.ok(details.weight_unit.inputs.includes(area==='perfis'?'Densidade (kg/m³)=':'Peso por metro (kg/m)='));
   const production=details[area==='perfis'?'cut':'made'];
   assert.ok(production.inputs.includes('Total OCR da operação (un.)='));
   assert.ok(production.inputs.includes('Acumulado Excel (un.)='));
   if(data.row.calculation.rules[area==='perfis'?'cut':'made'].inputs.ocr_events.length){
    assert.ok(production.inputs.includes('Quantidade (un.)='));
    assert.ok(production.inputs.includes('Registo='));
   }
   const weightLabel=data.fields.find(f=>f.id==='weight_unit').label;
   await page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:weightLabel,exact:true})}).scrollIntoViewIfNeeded();
   report.cases.push({area,key,version:data.version,details});
   await page.screenshot({path:folder+'/'+prefix+'-'+area+'.png',fullPage:true});
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
