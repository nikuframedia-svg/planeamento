// C03 end-to-end registration, scoped strictly to the full isolated copy.
const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated Planeamento required');
const prefix=process.env.PLANNING_CHECK_PREFIX||'c03-complete-browser';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid prefix');
const runFile=folder+'/c03-complete-run.json';
const fixture=fs.existsSync(runFile)?JSON.parse(fs.readFileSync(runFile)):{run:Date.now(),areas:{}};
const checkpoint=()=>fs.writeFileSync(runFile,JSON.stringify(fixture,null,2));
const report={at:new Date().toISOString(),base,areas:{},errors:[],result:'running'};
let browser;
const close=(a,b)=>assert(typeof a==='number'&&Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-8),`${a} != ${b}`);
async function detail(page,id){const r=await page.request.get(base+'/planeamento/api/necessidades/'+id);assert.equal(r.status(),200);return r.json();}
async function fill(page,id,value){const n=page.locator('#field-'+id);await n.waitFor();if(await n.evaluate(n=>n.tagName)==='SELECT')await n.selectOption(String(value));else await n.fill(String(value));}
async function formReady(page){await page.locator('#field-component_ref').waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('#error').hidden||document.querySelector('#preparation').hidden===false);assert.equal(await page.locator('#error').isVisible(),false,await page.locator('#error').textContent());}
async function rowVisible(raw,id,q){await raw.waitForFunction(({id,q})=>Raw.state.data?.rows.some(r=>r.need_id===id&&r.values.remaining===q),{id,q},{timeout:12000});return raw.evaluate(id=>Raw.state.data.rows.find(r=>r.need_id===id),id);}
async function save(form,raw,area,q){
 const start=Date.now();const response=form.waitForResponse(r=>r.url().endsWith('/necessidades/registar')&&r.request().method()==='POST',{timeout:60000});
 await form.locator('button[name=draft]').click();const received=await response,returned=Date.now(),body=await received.json();
 assert.equal(received.status(),200,JSON.stringify(body));assert(body.need_id,JSON.stringify(body));
 const visible=await rowVisible(raw,body.need_id,q);const visibleAt=Date.now();
 await form.waitForFunction(()=>!document.querySelector('#after-save').hidden||!document.querySelector('#error').hidden);
 assert.equal(await form.locator('#error').isVisible(),false,await form.locator('#error').textContent());
 return {request:received.request().postDataJSON(),response:body,request_ms:returned-start,response_to_raw_ms:visibleAt-returned,row:visible};
}
async function verifyResults(raw,id,area,q,length){
 const rate=area==='perfis'?10:20;
 await raw.waitForFunction(({id,q,rate})=>{const r=Raw.state.data?.rows.find(x=>x.need_id===id);return r?.values.quantity_required===q&&Math.abs(r.values.theoretical_hours-q/rate)<1e-8&&!Raw.state.data.aggregates_pending;},{id,q,rate},{timeout:15000});
 const row=await raw.evaluate(id=>Raw.state.data.rows.find(x=>x.need_id===id),id),v=row.values;
 close(v.quantity_required,q);close(v.remaining,q);close(v.quantity_to_plan,q);close(v.total_length,q*length);
 close(v[area==='perfis'?'cut':'made'],0);close(v.theoretical_hours,q/rate);assert.equal(v.rate_source,'Manual');
 const unit=area==='perfis'?Math.PI*100/1e6*length/1000*7850:3.77*length/1000;
 close(v.weight_unit,unit);close(v.weight,q*unit);
 if(area==='perfis')close(v.bars,Math.ceil(q/Math.floor(12000/length)));
 assert.equal(v.preparation_status,'Rascunho');assert.equal(v.planning_active,true);
 assert(row.calculation.production_sources.some(p=>p.origin==='Condição inicial local'));
 assert(row.calculation.production_sources.every(p=>!p.events?.length));
 return row;
}
(async()=>{
 browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 for(const [i,area] of ['perfis','cantoneiras'].entries()){
  const entry=fixture.areas[area]||={order:'OF98'+String(fixture.run).slice(-6)+i,pieces:[]};checkpoint();
  const context=await browser.newContext({viewport:{width:1440,height:1050}}),form=await context.newPage(),raw=await context.newPage();
  for(const page of [form,raw])page.on('pageerror',e=>report.errors.push(e.message));
  const result=report.areas[area]={order:entry.order,pieces:[],partial_edit:null,conflict:null};
  const cat=await (await form.request.get(base+'/planeamento/api/catalogos?contrato=3&area='+area)).json();
  const fields=await (await form.request.get(base+'/planeamento/api/raw/colunas?area='+area)).json();
  await raw.goto(base+'/planeamento/raw?area='+area+'&q='+entry.order);
  await raw.waitForFunction(()=>Raw.state.data&&document.querySelector('#count').textContent.includes('linhas'));
  for(let index=0;index<2;index++){
   const existing=entry.pieces[index];
   if(existing){await form.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+existing.id);await formReady(form);}
   else if(index===0){
    await form.goto(base+'/planeamento/manual?area='+area);await formReady(form);
    assert.equal(await form.locator('#search').isVisible(),false);
    await form.locator('#local-of').fill(entry.order);
    for(const [k,v] of Object.entries({ov:'OV-C03-'+area,customer:'Cliente C03 isolado',designation:'Obra C03 '+area,delivery_date:'2027-01-15'}))await form.locator('#local-'+k).fill(v);
   }else{
    await form.locator('#another-piece').click();
    await form.waitForFunction(()=>document.querySelector('#field-component_ref')?.value===''&&!document.querySelector('#preparation').hidden);
    await formReady(form);
    assert.equal(await form.locator('#field-component_ref').inputValue(),'');
   }
   const controls=await form.locator('#preparation [id^="field-"]').evaluateAll(ns=>ns.map(n=>n.id.slice(6)));
   const editable=fields.columns.filter(f=>f.editable).map(f=>f.id);
   assert.deepEqual(editable.filter(k=>!controls.includes(k)),[]);
   result.parity={raw_editable:editable,form_controls:controls,missing:[]};
   if(area==='cantoneiras')await fill(form,'operation','112');
   await fill(form,'component_ref','C03-'+area+'-'+(index+1));
   await fill(form,'material_type',area==='perfis'?'Varão redondo':'Cantoneira');
   await fill(form,'profile',area==='perfis'?'20':'L50X50X5');
   if(area==='perfis')await fill(form,'outer_diameter_mm',20);
   else for(const [k,v] of Object.entries({width_mm:50,height_mm:50,thickness_mm:5}))await fill(form,k,v);
   const q=index?8:12,length=index?1500:2000;
   for(const [k,v] of Object.entries({grade:'S355JR',length_mm:length,quantity_required:q,stock_length_mm:12000,
     angle_deg:0,expected_date:'2027-01-04',planned_week:1,planned_year:2027,picking_week:40,picking_year:2026,
     cut_date:'2026-09-24',pavilion:'C03',material_requested:'false',machine:area==='perfis'?'Serrote Doall Pav.1':'Ficep Rapid 20T'}))await fill(form,k,v);
   const team=cat.teams[0];if(team)await fill(form,'team',typeof team==='string'?team:team.value);
   if(area==='cantoneiras')await fill(form,'operation_detail','0');
   const notes='C03 preservação '+area+' peça '+(index+1);
   const previewResponse=form.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&r.request().postDataJSON()?.values.notes===notes);
   await fill(form,'notes',notes);const preview=await (await previewResponse).json();
   assert.equal(preview.saved,false);close(preview.row.values.remaining,q);
   await form.waitForFunction(q=>document.querySelector('[data-preview-field=remaining] td:nth-child(2)')?.textContent===q+' un.',q);
   const saved=await save(form,raw,area,q);const id=saved.response.need_id;
   if(!existing){entry.pieces[index]={id,creation:saved};checkpoint();}else assert.equal(id,existing.id);
   const actual=await verifyResults(raw,id,area,q,length);
   const replay=await form.request.post(base+'/planeamento/api/necessidades/registar',{data:saved.request});assert.equal(replay.status(),200);assert.deepEqual(await replay.json(),saved.response);
   const stored=await detail(form,id);assert.equal(stored.local_order.values_json.ov,'OV-C03-'+area);
   assert.equal(stored.local_order.values_json.customer,'Cliente C03 isolado');assert.equal(stored.need.specification.length_mm,length);
   assert.equal(stored.need.specification.quantity_required,q);assert.equal(stored.records[0].values_json.stock_length_mm,12000);
   assert.equal(stored.records[0].values_json.notes,notes);assert.equal(stored.records[0].values_json.material_requested,false);
   assert.equal(stored.records[0].values_json.machine,area==='perfis'?'Serrote Doall Pav.1':'Ficep Rapid 20T');
   assert.equal(stored.records[0].record_status,'draft');
   for(const [field,value] of Object.entries(saved.request.values)){
    if(value===''||value===null||value===undefined)continue;
    const typed=cat.fields.find(f=>f.id===field),actual=stored.records[0].values_json[field];
    if(field==='abocardar')assert.equal(actual,value?'X':'-');
    else if(typed?.type==='number')close(actual,Number(value));else assert.deepEqual(actual,value,'persisted '+field);
   }
   const reopened=await context.newPage();await reopened.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+id);await formReady(reopened);
   assert.equal(await reopened.locator('#field-notes').inputValue(),notes);
   assert.equal(await reopened.locator('#local-ov').inputValue(),'OV-C03-'+area);await reopened.close();
   result.pieces.push({id,preview,save:saved,actual,detail:stored,idempotency:'same response, same piece'});
  }
  assert.notEqual(entry.pieces[0].id,entry.pieces[1].id);
  const id=entry.pieces[0].id;
  // Real browser edit followed by a deliberately partial API edit.
  await form.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+id);await formReady(form);
  await fill(form,'quantity_required',15);await fill(form,'length_mm',2500);
  const edited=await save(form,raw,area,15);const editedRow=await verifyResults(raw,id,area,15,2500);
  const before=await detail(form,id),revision=before.need.revision;
  const partial={request_id:crypto.randomUUID(),area,need_id:id,expected_revision:revision,
   production_order_no:entry.order,catalog_version:cat.version,record_status:'draft',values:{notes:'C03 edição parcial '+area,operation:area==='perfis'?'corte':'112'}};
  const response=await form.request.post(base+'/planeamento/api/necessidades/registar',{data:partial});assert.equal(response.status(),200,await response.text());
  const partialSaved=await response.json(),after=await detail(form,id);
  assert.deepEqual(after.need.specification,before.need.specification);
  const expected={...before.records[0].values_json,notes:partial.values.notes};assert.deepEqual(after.records[0].values_json,expected);
  assert.deepEqual(after.local_order,before.local_order);
  const stale={...partial,request_id:crypto.randomUUID(),values:{...partial.values,quantity_required:99}};
  const rejected=await form.request.post(base+'/planeamento/api/necessidades/registar',{data:stale});assert.equal(rejected.status(),409);
  assert.deepEqual(await detail(form,id),after);
  result.edit={save:edited,row:editedRow};result.partial_edit={request:partial,response:partialSaved,before,after};result.conflict={status:409,body:await rejected.json(),preserved:true};
  await form.reload();await formReady(form);assert.equal(await form.locator('#field-notes').inputValue(),partial.values.notes);
  assert.equal(await form.locator('#field-length_mm').inputValue(),'2500');assert.equal(await form.locator('#field-quantity_required').inputValue(),'15');
  const all=await (await form.request.get(base+'/planeamento/api/necessidades/lista?of='+entry.order)).json();
  assert.deepEqual(all.needs.map(n=>n.id).sort(),entry.pieces.map(n=>n.id).sort());
  await raw.waitForFunction(()=>Raw.state.data.rows.length===2);
  await form.screenshot({path:folder+'/'+prefix+'-'+area+'-form.png',fullPage:true});
  await raw.screenshot({path:folder+'/'+prefix+'-'+area+'-raw.png',fullPage:true});
  result.final_rows=await raw.evaluate(()=>Raw.state.data.rows);await context.close();
 }
 assert.deepEqual(report.errors,[]);report.result='passed';console.log('C03: two pieces per new local OF in both areas; draft load, preview, persistence, edits, idempotency and conflicts passed.');
})().catch(e=>{report.result='failed';report.failure=String(e.stack||e);console.error(e);process.exitCode=1;}).finally(async()=>{
 fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));checkpoint();if(browser)await browser.close();
});
