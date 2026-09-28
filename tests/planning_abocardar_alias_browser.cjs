const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated copy required');
(async()=>{
 const fixed=[{row:5588,id:34512,length:2750,cut:840,boc:null,aboc:false},
              {row:5589,id:34513,length:2050,cut:840,boc:765,aboc:true,record:2066},
              {row:5590,id:34514,length:2300,cut:840,boc:668,aboc:true,record:2065}];
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,method:'OF264774 three distinct geometries; totals from independently reconciled central event IDs, arithmetic Q=840. Browser/API and operation evidence.',samples:[],errors:[]};
 const display=n=>n===null?'—':new Intl.NumberFormat('pt-PT',{maximumFractionDigits:4}).format(n).replace(/\s/g,'');
 const same=(a,b)=>a===null||b===null?assert.equal(a,b):assert(Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-8));
 let page;
 try{
  page=await browser.newPage({viewport:{width:1600,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));
  const sourceProof=JSON.parse(fs.readFileSync(folder+'/c02-selected-ocr-final.json','utf8'));assert.equal(sourceProof.result,'passed_in_stated_scope');
  const keys=fixed.map(r=>'macro:mtg2_bf1cd6a25986791e:plan:'+r.row);
  const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area:'perfis',population:'active',selected:keys}});assert(response.ok());
  const api=await response.json();assert.equal(api.rows.length,3);const rows=Object.fromEntries(api.rows.map(r=>[r.key,r]));
  await page.goto(base+'/planeamento/raw?area=perfis&q=OF264774');await page.waitForFunction(()=>Raw.state.data);
  const expectedFields=['cut','boc','remaining','boc_remaining','cut_pct','final_pct','bars','weight','total_length'];
  const columns=['of','ov','component_ref','id','profile','length_mm',...expectedFields];
  const previous=await page.evaluate(()=>Raw.state.columns);await page.locator('#open-columns').click();
  for(const id of new Set([...previous,...columns])){
   const control=page.locator('[data-column-control="'+id+':visible"]');
   if(await control.isChecked()===columns.includes(id))continue;
   const group=control.locator('xpath=ancestor::details');if(!await group.evaluate(n=>n.open))await group.locator('summary').click();await control.setChecked(columns.includes(id));
  }
  await page.getByRole('button',{name:'Aplicar e fechar',exact:true}).click();
  await page.waitForFunction(()=>Raw.state.data?.rows.length===3&&document.getElementById('notice').textContent!=='A consultar…');
  for(const fixture of fixed){
   const key='macro:mtg2_bf1cd6a25986791e:plan:'+fixture.row,row=rows[key],v=row.values;
   const expected={cut:fixture.cut,boc:fixture.boc,remaining:0,boc_remaining:fixture.aboc?840-fixture.boc:0,
                   cut_pct:100,final_pct:fixture.aboc?100*fixture.boc/840:100,bars:0,weight:0,total_length:840*fixture.length};
   assert.equal(v.id,fixture.id);assert.equal(v.length_mm,fixture.length);assert.equal(v.planning_active,true);
   for(const code of fixture.aboc?['corte','abocardar']:['corte']){
    const proof=sourceProof.selected.find(r=>r.key===key&&r.operation===code);assert(proof&&proof.result==='passed');
    same(proof.expected,code==='corte'?fixture.cut:fixture.boc);
    const source=row.calculation.production_sources.find(r=>r.operation===code);assert.equal(source.origin,'OCR validado');assert.deepEqual(source.coverage_reasons,[]);
   }
   const index=await page.evaluate(key=>Raw.state.data.rows.findIndex(r=>r.key===key),key),tr=page.locator('#sheet tbody tr').nth(index);
   const visible={};
   for(const [field,value] of Object.entries(expected)){
    same(v[field],value);const position=await page.evaluate(field=>Raw.state.columns.indexOf(field),field);
    const cell=tr.locator('td').nth(position);await cell.scrollIntoViewIfNeeded();visible[field]=await cell.innerText();assert.equal(visible[field].replace(/\s/g,''),display(value));
   }
   const position=await page.evaluate(()=>Raw.state.columns.indexOf('remaining'));await tr.locator('td').nth(position).dblclick();
   await page.locator('#drawer').getByRole('button',{name:'Produção por operação',exact:true}).click();
   if(fixture.record){const cell=page.locator('#drawer').getByRole('cell',{name:String(fixture.record),exact:true}).first();await cell.scrollIntoViewIfNeeded();assert(await cell.isVisible());}
   await page.screenshot({path:folder+'/c02-abocardar-'+fixture.id+'.png',fullPage:true});
   await page.locator('#close-drawer').click();
   report.samples.push({area:'perfis',key,reference:v.component_ref,expected,visible,id:fixture.id,length:fixture.length,production_record:fixture.record,version:api.version});
  }
  assert.deepEqual(report.errors,[]);report.result='passed';console.log('Three distinct OF264774 geometries verified in API/grid/operation detail; 2065/2066 visible');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/c02-abocardar-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
