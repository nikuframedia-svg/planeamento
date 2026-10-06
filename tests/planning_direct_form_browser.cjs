const {chromium}=require('./playwright_core.cjs');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated planning server required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),cases:[],errors:[]};
 try{
  for(const area of ['perfis','cantoneiras']){
   const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
   const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area,population:'active',page_size:100}}),data=await response.json();
   const row=data.rows.find(r=>r.plan_key&&!r.need_id);assert(row);
   await page.goto(base+'/planeamento/raw?area='+area+'&need='+encodeURIComponent(row.key));
   const link=page.locator('#drawer').getByRole('link',{name:'Abrir formulário',exact:true});
   const popupPromise=page.waitForEvent('popup');await link.click();const form=await popupPromise;form.on('pageerror',e=>report.errors.push(e.message));
   await form.waitForFunction(()=>document.querySelector('#field-component_ref')?.value||!document.querySelector('#error').hidden);
   assert.equal(await form.locator('#error').isVisible(),false,await form.locator('#error').textContent());
   assert.equal(await form.locator('#field-component_ref').inputValue(),row.values.component_ref);
   assert.equal(Number(await form.locator('#field-length_mm').inputValue()),row.values.length_mm);
   assert.equal(Number(await form.locator('#field-quantity_required').inputValue()),row.values.quantity_required);
   assert.equal(await form.locator('#references-dialog').isVisible(),false);
   const preview=form.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&r.request().postDataJSON()?.source?.id===row.plan_key);
   await form.locator('#field-quantity_required').fill(String(row.values.quantity_required));
   const calculated=await preview;assert.equal(calculated.status(),200);assert.equal((await calculated.json()).saved,false);
   const screenshot='c05-direct-form-'+area+'.png';await form.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.cases.push({area,key:row.key,version:data.version,reference:row.values.component_ref,quantity:row.values.quantity_required,length:row.values.length_mm,screenshot});
   await form.close();await page.close();
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/c05-direct-form-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
