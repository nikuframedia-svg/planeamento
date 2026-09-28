const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit full clone required');
const close=(actual,expected)=>assert(Math.abs(actual-expected)<1e-8,`${actual} != ${expected}`);
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,areas:[],errors:[]};
 try{
  const fixtures=JSON.parse(fs.readFileSync(folder+'/c05-capacity-live-fixtures.json','utf8'));
  for(const fixture of fixtures.areas){
   const page=await browser.newPage({viewport:{width:1440,height:1050}});
   page.on('pageerror',e=>report.errors.push(e.message));
   const first=page.waitForResponse(r=>r.url().endsWith('/necessidades/prever'));
   await page.goto(base+'/planeamento/preparar?area='+fixture.area+'&necessidade='+fixture.need_id);
   const initial=await (await first).json();
   assert(initial.capacity_preview?.available,JSON.stringify(initial.capacity_preview));
   const before=await page.evaluate(async id=>(await(await fetch('/planeamento/api/necessidades/'+id)).json()).need,fixture.need_id);
   assert.equal(before.quantity_required,40);
   const item={area:fixture.area,need_id:fixture.need_id,before_revision:before.revision,steps:[]};report.areas.push(item);
   async function edit(q,machine,date,rate,available){
    const start=Date.now();
    const response=page.waitForResponse(r=>{
     if(!r.url().endsWith('/necessidades/prever'))return false;
     const v=r.request().postDataJSON().values;
     return Number(v.quantity_required)===q&&v.machine===machine&&v.expected_date===date;
    });
    await page.locator('#field-quantity_required').fill(String(q));
    await page.locator('#field-machine').selectOption(machine);
    await page.locator('#field-expected_date').fill(date);
    const received=await response,returned=Date.now(),data=await received.json();
    assert.equal(received.status(),200,JSON.stringify(data));
    assert.equal(data.saved,false);assert.equal(data.capacity_preview?.available,true,JSON.stringify(data.capacity_preview));
    close(data.row.values.theoretical_hours,q/rate);close(data.row.values.hours_pct,100*q/rate/available);
    const field=page.locator('#preview-results tr[data-preview-field=hours_pct]');
    await page.waitForFunction(value=>document.querySelector('#preview-results tr[data-preview-field=hours_pct] td:nth-child(2)')?.textContent===String(value)+' %',data.row.values.hours_pct);
    const visible=Date.now();assert((await field.textContent()).includes('carga total da máquina/semana'));
    const step={proposed:{q,machine,date},expected:{hours:q/rate,occupancy:100*q/rate/available},
     requestPlusDebounceMs:returned-start,responseToVisibleMs:visible-returned,values:data.row.values,capacity:data.capacity_preview};
    item.steps.push(step);return data;
   }
   await edit(60,fixture.machines[1],'2027-01-11',fixture.rate*2,16);
   const moved=await edit(60,fixture.machines[0],'2027-01-04',fixture.rate,14);
   const previous=moved.capacity_preview.weekly.find(r=>r.key===fixture.resources[1].resource.id+'|2027|2');
   assert.equal(previous.values.planned_hours,0);
   // A delayed F12 response for Q61 cannot replace the subsequent Q62 simulation.
   let started,finished,release;const olderStarted=new Promise(r=>started=r),olderFinished=new Promise(r=>finished=r),releaseOlder=new Promise(r=>release=r);
   await page.route('**/necessidades/prever',async route=>{
    if(Number(route.request().postDataJSON().values.quantity_required)!==61)return route.continue();
    started();const response=await route.fetch();await releaseOlder;await route.fulfill({response});finished();
   });
   await page.locator('#field-quantity_required').fill('61');await olderStarted;
   const newest=page.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&Number(r.request().postDataJSON().values.quantity_required)===62);
   await page.locator('#field-quantity_required').fill('62');const data=await(await newest).json();
   close(data.row.values.hours_pct,6200/fixture.rate/14);
   await page.waitForFunction(value=>document.querySelector('#preview-results tr[data-preview-field=hours_pct] td:nth-child(2)')?.textContent===String(value)+' %',data.row.values.hours_pct);
   release();await olderFinished;
   assert.equal(await page.locator('#preview-results tr[data-preview-field=hours_pct] td:nth-child(2)').textContent(),String(data.row.values.hours_pct)+' %');
   item.delayedResponsePreserved=data.row.values.hours_pct;
   await page.unroute('**/necessidades/prever');
   const after=await page.evaluate(async id=>(await(await fetch('/planeamento/api/necessidades/'+id)).json()).need,fixture.need_id);
   assert.equal(after.revision,before.revision);assert.equal(after.quantity_required,before.quantity_required);
   item.after_revision=after.revision;item.persisted_quantity=after.quantity_required;
   await page.locator('#calculation-preview details').evaluate(n=>n.open=true);
   await page.locator('#calculation-preview').scrollIntoViewIfNeeded();
   await page.screenshot({path:folder+'/c05-f12-'+fixture.area+'-preview.png',fullPage:true});
   await page.close();
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
  console.log('F12 quantity, machine/week, previous load removal and delayed responses passed in both areas; no saves.');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/c05-f12-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
