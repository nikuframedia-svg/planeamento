const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Full isolated clone required');
const mutate=(area,action)=>JSON.parse(execFileSync('.venv/bin/python',['scripts/planning_original_live_trial.py',area,action,'--local-c03'],{env:{...process.env,PYTHONPATH:'.'},encoding:'utf8'}));
async function settled(area){const end=Date.now()+30000;while(!mutate(area,'inspect').settled){assert(Date.now()<end);await new Promise(r=>setTimeout(r,200));}}
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 const report={at:new Date().toISOString(),base,areas:[],errors:[]};
 try{
  for(const area of ['perfis','cantoneiras']){
   await settled(area);const initial=mutate(area,'inspect');mutate(area,'insert');await settled(area);
   const form=await browser.newPage(),raw=await browser.newPage();for(const page of [form,raw])page.on('pageerror',e=>report.errors.push(e.message));
   await raw.goto(base+'/planeamento/raw?area='+area+'&q='+encodeURIComponent(initial.values_before.component_ref));
   await raw.waitForFunction(key=>Raw.state.data?.rows.some(r=>r.key===key),initial.key);
   await form.goto(base+'/planeamento/preparar?area='+area+'&necessidade='+initial.key+'&ocr_source=original');
   await form.waitForFunction(()=>document.querySelector('#field-component_ref')?.value);
   await form.locator('#evidence-open').click();await form.locator('#production-open').click();
   await form.locator('#production-dialog').waitFor({state:'visible'});
   let delayedResolve;const delayed=new Promise(r=>delayedResolve=r);
   await form.route('**/producao/pendencias?**',async route=>{
    if(new URL(route.request().url()).searchParams.get('estado')==='all'){
     const response=await route.fetch();await new Promise(r=>setTimeout(r,400));await route.fulfill({response});delayedResolve();
    }else await route.continue();
   });
   await form.locator('#production-filter').selectOption('all');
   await form.locator('#production-filter').selectOption('associated');
   await delayed;
   await form.waitForFunction(()=>!document.querySelector('#production-content').textContent.includes('A carregar'));
   assert.equal(await form.locator('#production-content .item').count(),0);
   await form.unroute('**/producao/pendencias?**');
   await form.locator('#production-filter').selectOption('all');
   const item=report.areas[report.areas.push({area,key:initial.key,stale_response_preserved:true,steps:[]})-1];
   for(const quantity of [5,10]){
    await form.waitForFunction(()=>document.querySelectorAll('#production-content .item').length===1);
    const row=form.locator('#production-content .item').first();
    await row.getByLabel('Quantidade atribuída',{exact:true}).fill(String(quantity));
    await row.getByLabel('Justificação',{exact:true}).fill('C05 associação original na cópia integral: '+quantity+'/10');
    const response=form.waitForResponse(r=>r.url().endsWith('/api/associacoes')&&r.request().method()==='POST');
    await row.getByRole('button',{name:'Guardar associação',exact:true}).click();
    const saved=await response,received=Date.now(),result=await saved.json();assert.equal(saved.status(),200,JSON.stringify(result));
    assert.equal(result.publication.status,'published');
    const remaining=quantity===10?initial.values_before.quantity_required-10:null;
    const published=Number(result.publication.areas[area].version);
    await raw.waitForFunction(({key,remaining,published})=>Number(Raw.state.data?.version)>=published&&Raw.state.data.rows.find(r=>r.key===key)?.values.remaining===remaining,{key:initial.key,remaining,published},{timeout:15000});
    const step={quantity,request_ms:saved.request().timing().responseEnd,response_to_raw_ms:Date.now()-received,revision:result.revision};
    assert(step.response_to_raw_ms<=2000);
    await raw.waitForFunction(()=>!Raw.state.data.aggregates_pending,{timeout:15000});
    const current=await raw.evaluate(key=>Raw.state.data.rows.find(r=>r.key===key),initial.key);
    const c=await raw.request.post(base+'/planeamento/api/raw/consultas',{data:{area,dataset:'capacity_items',filters:[{field:'component_ref',op:'eq',value:initial.values_before.component_ref}]}});
    assert.equal(c.status(),200);const capacity=(await c.json()).rows;assert.equal(capacity.length,1);
    assert.equal(capacity[0].values.quantity,remaining);
    const unit=initial.values_before.applied_rate_unit,rate=initial.values_before.applied_rate_value;
    assert(['min/un.','un./h'].includes(unit),'Fixture must use a confirmed simple manual rate');
    const hours=remaining===null?null:unit==='min/un.'?remaining*rate/60:remaining/rate;
    assert.equal(current.values.theoretical_hours,hours);assert.equal(capacity[0].values.planned_hours,hours);
    step.response_to_aggregates_ms=Date.now()-received;assert(step.response_to_aggregates_ms<=10000);
    step.remaining=remaining;step.hours=hours;item.steps.push(step);
    console.log(area,quantity,step.request_ms,step.response_to_raw_ms,step.response_to_aggregates_ms);
   }
   await form.reload();await form.waitForFunction(()=>document.querySelector('#field-component_ref')?.value);
   await form.locator('#evidence-open').click();await form.locator('#production-open').click();await form.locator('#production-filter').selectOption('associated');
   await form.waitForFunction(()=>document.querySelectorAll('#production-content .item').length===1);
   assert.equal(await form.getByLabel('Quantidade atribuída',{exact:true}).inputValue(),'10');
   await form.screenshot({path:folder+'/t4-full-association-'+area+'.png',fullPage:true});
   mutate(area,'release');mutate(area,'remove');await settled(area);mutate(area,'cleanup');await settled(area);
   await raw.waitForFunction(({key,q})=>Raw.state.data.rows.find(r=>r.key===key)?.values.remaining===q,{key:initial.key,q:initial.values_before.remaining});
   await form.close();await raw.close();
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/t4-full-association-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
