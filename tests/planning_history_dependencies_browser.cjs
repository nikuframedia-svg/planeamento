const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
const prefix=process.env.PLANNING_PROOF_PREFIX||'c10-dependencies';
if(!/^[a-z0-9-]+$/.test(prefix))throw Error('Invalid proof prefix');
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated full clone required');
const fixtures=JSON.parse(fs.readFileSync(folder+'/c10-dependencies-fixtures.json','utf8'));
const kinds={resource:'Máquinas físicas',calendar:'Calendários',rate:'Parâmetros',worked_hours:'Horas reais'};
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 const report={at:new Date().toISOString(),base,areas:[],errors:[],timingFailures:[]};
 try{
  for(const f of fixtures.areas){
   const pages=await Promise.all(Array.from({length:4},()=>browser.newPage({viewport:{width:1440,height:1050}})));
   pages.forEach(p=>p.on('pageerror',e=>report.errors.push(e.message)));
   const [editor,active,closed,cap]=pages,item={area:f.area,steps:[]};report.areas.push(item);
   for(const [page,sample,population] of [[active,f.active,'active'],[closed,f.closed,'history']]){
    await page.goto(base+'/planeamento/raw?area='+f.area+'&q='+encodeURIComponent(sample.values_json.component_ref)+(population==='active'?'&need='+encodeURIComponent(sample.row_key):''));
    await page.waitForFunction(()=>Raw.state.data);
    if(population==='history')await page.locator('#population').selectOption('history');
    await page.waitForFunction(key=>Raw.state.data?.rows.some(r=>r.key===key),sample.row_key);
    if(population==='active')await page.locator('#drawer').waitFor();
    else {
     const index=await page.evaluate(key=>Raw.state.data.rows.findIndex(r=>r.key===key),sample.row_key);
     await page.locator('#sheet tbody tr').nth(index).locator('.row-action').click();
    }
    assert.equal(await page.evaluate(()=>Raw.state.evidence.key),sample.row_key);
    await page.getByRole('button',{name:'Taxas e horas',exact:true}).click();
   }
   let capData;
   cap.on('response',async r=>{if(r.url().endsWith('/raw/capacidade/consulta')&&r.ok())capData=await r.json();});
   await cap.goto(base+'/planeamento/capacidades?area='+f.area);await cap.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   await cap.locator('#search').fill(f.resource.name);await cap.getByRole('button',{name:'Consultar',exact:true}).click();
   await cap.waitForFunction(name=>document.querySelectorAll('#matrix tbody tr').length===1&&document.querySelector('#matrix tbody tr')?.textContent.includes(name),f.resource.name);
   await cap.locator('#matrix tbody').getByRole('button',{name:f.resource.name,exact:true}).click();
   const panel=cap.locator('#panel-body');let found=false;
   for(let i=0;i<35;i++){
    await panel.getByText('A carga prevista usa taxa manual aplicável',{exact:false}).waitFor();
    const target=panel.locator('tr').filter({hasText:f.active.values_json.of}).getByRole('button',{name:f.active.values_json.component_ref,exact:true});
    if(await target.count()){await target.first().click();found=true;break;}
    await panel.getByRole('button',{name:'Seguinte →',exact:true}).click();
   }
   assert(found);await panel.getByText('Taxa aplicada',{exact:true}).waitFor();
   await editor.goto(base+'/planeamento/disponibilidade?area='+f.area);await editor.locator('#configure').click();
   const edit=editor.locator('#edit-panel');
   async function open(kind,name){
    await editor.locator('#panel-body').getByRole('button',{name:kinds[kind],exact:true}).click();
    await editor.locator('#panel-body').getByRole('button',{name:name||'Adicionar',exact:true}).click();
    await edit.waitFor();
   }
   async function save(kind,label,source,rate){
    const before=await active.evaluate(()=>Raw.state.data.version),start=Date.now();
    const [response]=await Promise.all([editor.waitForResponse(r=>r.url().endsWith('/raw/objects/'+kind)&&r.request().method()==='POST'),editor.locator('#save-config').click()]);
    const returned=Date.now(),saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));
    const step={label,kind,saved,expectedSource:source,expectedRate:rate,requestMs:returned-start};item.steps.push(step);
    await Promise.all([[active,f.active,false],[closed,f.closed,true]].map(async([page,sample,historical])=>{
     const v=sample.values_json,volume=v.remaining*(f.area==='perfis'?v.section_unit:v.length_mm/1000),hours=volume/rate;
     await page.waitForFunction(({key,source,rate,hours,before,historical})=>{
      const row=Raw.state.data?.rows.find(r=>r.key===key),tr=document.querySelector('#drawer-body table tbody tr');
      return Number(Raw.state.data?.version)>Number(before)&&!Raw.state.data.aggregates_pending&&row?.values.rate_source===source&&Math.abs(row.values.applied_rate_value-rate)<1e-7&&Math.abs(row.values.theoretical_hours-hours)<1e-7&&(!historical||row.values.hours_pct===null)&&tr?.children[2]?.textContent===source&&tr.children[3]?.textContent===new Intl.NumberFormat('pt-PT',{maximumFractionDigits:4}).format(rate);
     },{key:sample.row_key,source,rate,hours,before,historical},{timeout:90000});
     step[historical?'closedVisibleMs':'activeVisibleMs']=Date.now()-returned;
     step[historical?'closed':'active']=await page.evaluate(key=>Raw.state.data.rows.find(r=>r.key===key),sample.row_key);
    }));
    await cap.waitForFunction(({rate,source})=>[...document.querySelectorAll('#panel-body tr')].some(r=>r.children[0]?.textContent==='Taxa aplicada'&&r.children[1]?.textContent.startsWith(rate.toLocaleString('pt-PT',{maximumFractionDigits:2})+' · ')&&r.children[1]?.textContent.endsWith(' · '+source)),{rate,source},{timeout:90000});
    step.capacityVisibleMs=Date.now()-returned;step.capacityVersion=capData?.version;
    const history=await editor.request.get(base+'/planeamento/api/raw/objects/'+saved.id+'/historico');step.revisions=(await history.json()).versions.map(v=>v.revision);
    assert.equal(step.revisions[0],saved.revision);
    if(Math.max(step.activeVisibleMs,step.closedVisibleMs,step.capacityVisibleMs)>10000)report.timingFailures.push({area:f.area,label,activeMs:step.activeVisibleMs,closedMs:step.closedVisibleMs,capacityMs:step.capacityVisibleMs});
    fs.writeFileSync(folder+'/'+prefix+'-browser.json',JSON.stringify(report,null,2));
    console.log(f.area,label,step.activeVisibleMs,step.closedVisibleMs,step.capacityVisibleMs);
    return saved;
   }
   const hoursName=f.manual_hours?.name||'C10 Dependências '+f.area+' '+f.cohort.sheets[0];
   const existingHours=(await(await editor.request.get(base+'/planeamento/api/raw/objects/worked_hours')).json()).items.find(o=>o.name===hoursName);
   await open('worked_hours',existingHours?.name);
   if(!existingHours){
    await edit.getByLabel('Nome',{exact:true}).fill(hoursName);
    await edit.getByLabel(/^Máquina física/).selectOption(f.resource.id);
    await edit.getByLabel(/^Âmbito das horas/).selectOption('sheet');
    await edit.getByLabel(/^Folha/).selectOption(f.cohort.sheets[0]);
    await edit.getByLabel('Operação (vazio se o tempo abranger várias operações)',{exact:true}).fill(f.active.values_json.operation);
    await edit.getByLabel('Origem / justificação',{exact:true}).fill('Ensaio C10 na cópia isolada; não é declaração real de fábrica.');
   }
   await edit.getByLabel('Horas reais (h)',{exact:true}).fill(String(f.cohort.hours*2));
   await edit.getByRole('button',{name:'Conferir declarações',exact:true}).click();await edit.locator('#hours-evidence tbody tr').waitFor();
   await edit.getByLabel('Substituir integralmente',{exact:false}).check();await edit.getByLabel('Confirmo as horas reais',{exact:false}).check();
   await save('worked_hours','double-hours','Histórico',f.base_rate/2);
   await open('worked_hours',hoursName);await edit.getByLabel('Horas reais (h)',{exact:true}).fill(String(f.cohort.hours));
   await edit.getByRole('button',{name:'Conferir declarações',exact:true}).click();await edit.locator('#hours-evidence tbody tr').waitFor();
   await save('worked_hours','restore-hours','Histórico',f.base_rate);
   for(const days of [1,90]){
    await open('resource',f.resource.name);await edit.getByLabel('Janela de produtividade histórica (dias)',{exact:true}).fill(String(days));
    await save('resource','window-'+days,days===1?'Excel provisório':'Histórico',days===1?f.excel_rate:f.base_rate);
   }
   const rateName='C10 Dependências taxa '+f.area;
   const existingRate=(await(await editor.request.get(base+'/planeamento/api/raw/objects/rate')).json()).items.find(o=>o.name===rateName);
   await open('rate',existingRate?.name);await edit.getByLabel('Nome',{exact:true}).fill(rateName);
   await edit.getByLabel(/^Máquina física/).selectOption(f.resource.id);
   assert.equal(await edit.getByLabel(/^Área/).inputValue(),f.area);
   await edit.getByLabel(/^Operação/).selectOption(f.active.values_json.operation);
   await edit.getByLabel(/^Método e unidade/).selectOption(f.area==='perfis'?'area_hour':'metres_hour');
   await edit.getByLabel('Taxa / valor',{exact:true}).fill(String(f.base_rate*2));
   const today=await active.evaluate(()=>new Intl.DateTimeFormat('en-CA',{timeZone:Raw.state.data.display_timezone}).format(new Date()));
   const yesterday=new Date(Date.parse(today+'T12:00:00Z')-86400000).toISOString().slice(0,10);
   item.validityDates={today,yesterday};
   await edit.getByLabel('Válido desde',{exact:true}).fill('2026-01-01');await edit.getByLabel('Válido até (opcional)',{exact:true}).fill(today);
   await edit.getByLabel('Origem / justificação',{exact:true}).fill('Ensaio isolado da prioridade manual e expiração');await edit.getByRole('checkbox').check();
   await save('rate','manual-current','Manual',f.base_rate*2);
   await open('rate',rateName);await edit.getByLabel('Válido até (opcional)',{exact:true}).fill(yesterday);
   await save('rate','manual-expired','Histórico',f.base_rate);
   // Expiry is relative to each piece's planned date. Disable the test rate
   // too, so it no longer applies to older historical planning dates.
   await open('rate',rateName);await edit.getByRole('checkbox').uncheck();
   await save('rate','manual-disabled','Histórico',f.base_rate);
   if(!f.manual_hours){
    await open('worked_hours',hoursName);await edit.getByLabel('Confirmo as horas reais',{exact:false}).uncheck();
    await save('worked_hours','return-to-ocr-hours','Histórico',f.base_rate);
   }
   await active.screenshot({path:folder+'/'+prefix+'-'+f.area+'-active.png',fullPage:true});
   await closed.screenshot({path:folder+'/'+prefix+'-'+f.area+'-closed.png',fullPage:true});
   await cap.screenshot({path:folder+'/'+prefix+'-'+f.area+'-capacity.png',fullPage:true});
   await Promise.all(pages.map(p=>p.close()));
  }
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.timingFailures,[]);report.result='passed';
 }catch(e){report.failure={message:e.message,stack:e.stack};report.result='failed';throw e;}
 finally{fs.writeFileSync(folder+'/'+prefix+'-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
