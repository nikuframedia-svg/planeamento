const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
if(!base || process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
const output='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={environment:base,at:new Date().toISOString(),areas:[],errors:[]};
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));
  for(const area of ['perfis','cantoneiras']){
   await page.goto(base+'/planeamento/disponibilidade?area='+area);
   await page.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   const options=await page.evaluate(async()=> (await (await fetch('/planeamento/api/raw/horas/folhas')).json()).sheets);
   const source=options.find(s=>s.area===area&&s.machine&&s.date&&(area!=='perfis'||s.hours!==null));
   const start=new Date(source.date+'T12:00:00Z');start.setUTCDate(start.getUTCDate()-(start.getUTCDay()+6)%7);
   const end=new Date(start);end.setUTCDate(end.getUTCDate()+6);
   const startDate=start.toISOString().slice(0,10),endDate=end.toISOString().slice(0,10);
   await page.locator('#configure').click();
   const edit=page.locator('#edit-panel');
   const resources=await page.evaluate(async()=> (await (await fetch('/planeamento/api/raw/objects/resource')).json()).items);
   const existing=resources.find(r=>r.name.startsWith('C09 Isolado '+area)&&r.definition.aliases.some(a=>a.area===area&&a.name===source.machine));
   const resourceName=existing?.name || 'C09 Isolado '+area+' '+Date.now();
   if(!existing){
   await page.locator('#panel-body').getByRole('button',{name:'Adicionar',exact:true}).click();
   await edit.getByLabel('Nome',{exact:true}).fill(resourceName);
   await edit.getByLabel('Nomes equivalentes').fill(area+':'+source.machine);
   await edit.getByLabel('Operações suportadas').fill(area==='perfis'?'corte':'112');
   await edit.getByLabel('Horas por turno de referência').fill('8');
   await edit.getByLabel('Origem / justificação').fill('Ensaio na cópia isolada; sem alterar fontes');
   await edit.getByRole('checkbox').check();
   await page.locator('#save-config').click();await edit.waitFor({state:'hidden',timeout:5000}).catch(async e=>{throw Error(e.message+' UI: '+await page.locator('#edit-error').textContent())});
   }
   await page.locator('#panel-body').getByRole('button',{name:'Horas reais',exact:true}).click();
   await page.locator('#panel-body').getByRole('button',{name:'Adicionar',exact:true}).click();
   const hoursName='C09 Horas '+area+' '+Date.now();
   await edit.getByLabel('Nome',{exact:true}).fill(hoursName);
   await edit.getByLabel(/^Máquina física/).selectOption({label:resourceName});
   await edit.getByLabel('Desde',{exact:true}).fill(startDate);
   await edit.getByLabel('Até (mesma semana ISO)',{exact:true}).fill(endDate);
   await edit.getByLabel('Horas reais (h)',{exact:true}).fill('7');
   await edit.getByLabel('Origem / justificação').fill('Teste C09: declaração semanal substitui o conjunto conferido na cópia isolada');
   await edit.getByRole('button',{name:'Conferir declarações'}).click();
   await edit.locator('#hours-evidence tbody tr').first().waitFor();
   await edit.getByLabel('Substituir integralmente').check();
   await edit.getByLabel('Confirmo as horas reais').check();
   await page.screenshot({path:output+'/c09-'+area+'-conferencia.png',fullPage:true});
   await page.locator('#save-config').click();await edit.waitFor({state:'hidden',timeout:5000}).catch(async e=>{throw Error(e.message+' UI: '+await page.locator('#edit-error').textContent())});
   await page.reload();await page.locator('#configure').click();
   await page.locator('#panel-body').getByRole('button',{name:'Horas reais',exact:true}).click();
   await page.locator('#panel-body').getByRole('button',{name:hoursName,exact:true}).click();
   assert.equal(await edit.getByLabel('Horas reais (h)',{exact:true}).inputValue(),'7');
   await edit.getByLabel('Horas reais (h)',{exact:true}).fill('6');
   await page.locator('#save-config').click();await edit.waitFor({state:'hidden',timeout:5000}).catch(async e=>{throw Error(e.message+' UI: '+await page.locator('#edit-error').textContent())});
   const objects=await page.evaluate(async()=> (await (await fetch('/planeamento/api/raw/objects/worked_hours')).json()).items);
   const saved=objects.find(o=>o.name===hoursName);
   assert.equal(saved.revision,2);assert.equal(saved.definition.hours,6);assert.equal(saved.definition.origin,'Manual');
   const history=await page.evaluate(async id=>(await(await fetch('/planeamento/api/raw/objects/'+id+'/historico')).json()).versions,saved.id);
   assert.deepEqual(history.map(v=>v.definition.hours),[6,7]);
   await page.screenshot({path:output+'/c09-'+area+'-guardado.png',fullPage:true});
   report.areas.push({area,source,saved,history});
  }
  assert.deepEqual(report.errors,[]);
  fs.writeFileSync(output+'/c09-browser.json',JSON.stringify(report,null,2));
  console.log('Machine configuration and manual weekly hours created, reviewed, reloaded and revised in both areas; OCR sources retained.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
