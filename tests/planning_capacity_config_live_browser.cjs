const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit full clone required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 const report={at:new Date().toISOString(),base,areas:[],errors:[]};
 try{
  const fixtures=JSON.parse(fs.readFileSync(folder+'/c05-capacity-live-fixtures.json','utf8'));
  for(const fixture of fixtures.areas){
   const [editor,watch,raw]=await Promise.all(Array.from({length:3},()=>browser.newPage({viewport:{width:1440,height:1050}})));
   [editor,watch,raw].forEach(p=>p.on('pageerror',e=>report.errors.push(e.message)));
   const item={area:fixture.area,need_id:fixture.need_id,steps:[]};report.areas.push(item);
   await watch.goto(base+'/planeamento/disponibilidade?area='+fixture.area);
   await watch.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   const name='C05 Ensaio '+fixture.area+' 2';
   await watch.locator('#search').fill(name);await watch.locator('#year').fill('2027');await watch.locator('#week').fill('2');
   await watch.getByRole('button',{name:'Consultar',exact:true}).click();
   await watch.waitForFunction(name=>document.querySelector('#matrix tbody tr')?.textContent.includes(name)&&document.querySelectorAll('#matrix tbody tr').length===1,name);
   await watch.locator('#matrix tbody').getByRole('button',{name,exact:true}).click();
   await watch.getByRole('button',{name:'Calendário e parâmetros',exact:true}).click();
   await raw.goto(base+'/planeamento/raw?area='+fixture.area+'&q='+encodeURIComponent('INTEGRAL-'+fixture.area));
   await raw.waitForFunction(id=>Raw.state.data?.rows.some(r=>r.need_id===id),fixture.need_id);
   await editor.goto(base+'/planeamento/disponibilidade?area='+fixture.area);await editor.locator('#configure').click();
   for(const kind of ['rate','calendar']){
    await editor.locator('#panel-body').getByRole('button',{name:kind==='rate'?'Parâmetros':'Calendários',exact:true}).click();
    await editor.locator('#panel-body').getByRole('button',{name:name+(kind==='rate'?' taxa':' W2'),exact:true}).click();
    const panel=editor.locator('#edit-panel');
    if(kind==='rate')await panel.getByLabel('Taxa / valor',{exact:true}).fill(String(fixture.rate*2));
    else{
     await panel.getByLabel('Turnos na semana',{exact:true}).fill('3');await panel.getByLabel('Horas por turno',{exact:true}).fill('6');
     await panel.getByLabel('Horas indisponíveis / exceções',{exact:true}).fill('2');
    }
    const start=Date.now();const [response]=await Promise.all([editor.waitForResponse(r=>r.url().endsWith('/raw/objects/'+kind)&&r.request().method()==='POST',{timeout:20000}),editor.locator('#save-config').click()]);
    const returned=Date.now(),saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));
    const h=40/(fixture.rate*2),available=kind==='rate'?14:16;
    await Promise.all([
     watch.waitForFunction(({h,available})=>{const r=document.querySelector('#matrix tbody tr');return r?.children[1]?.textContent===String(available)&&r.children[4].textContent===String(h)&&r.children[5].textContent===String(available-h)},{h,available},{timeout:15000}),
     raw.waitForFunction(({id,h,available})=>{const r=Raw.state.data?.rows.find(r=>r.need_id===id);return r?.values.theoretical_hours===h&&Math.abs(r.values.hours_pct-100*h/available)<1e-8&&!Raw.state.data.aggregates_pending},{id:fixture.need_id,h,available},{timeout:15000})
    ]);
    const visible=Date.now();
    const api=await watch.request.post(base+'/planeamento/api/raw/capacidade/consulta',{data:{area:fixture.area,mode:'weekly',year:2027,week:2,q:name}});
    const result=await api.json();assert.equal(api.status(),200);const values=result.rows[0].values;
    assert.equal(values.available_hours,available);assert.equal(values.planned_hours,h);assert.equal(values.free_hours,available-h);
    assert(Math.abs(values.occupancy-h/available*100)<1e-8);assert(Math.abs(values.equivalent_shifts-h/(kind==='rate'?7.5:6))<1e-8);
    assert.equal(values.capacity_total,available*fixture.rate*2);assert.equal(values.capacity_free,(available-h)*fixture.rate*2);
    const history=await editor.request.get(base+'/planeamento/api/raw/objects/'+saved.id+'/historico');const versions=(await history.json()).versions;
    assert(versions.length>=2);assert.equal(versions[0].revision,saved.revision);
    const step={kind,requestMs:returned-start,responseToVisibleMs:visible-returned,saved,values,history:versions};item.steps.push(step);
    assert(step.responseToVisibleMs<=10000,kind+' exceeds10s: '+step.responseToVisibleMs);
   }
   await watch.screenshot({path:folder+'/c09-'+fixture.area+'-config-live.png',fullPage:true});
   await Promise.all([editor,watch,raw].map(p=>p.close()));
   fs.writeFileSync(folder+'/c09-capacity-config-live-browser.json',JSON.stringify(report,null,2));
  }
  assert.deepEqual(report.errors,[]);report.result='passed';console.log('Rate and calendar edits through settings update RAW and capacity without F5; H01/H02/H04-H08 and versioned history match in both areas.');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/c09-capacity-config-live-browser.json',JSON.stringify(report,null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
