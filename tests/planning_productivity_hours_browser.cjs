const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit isolated full copy required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={base,at:new Date().toISOString(),purpose:'Test declaration in isolated copy, not actual reported factory hours',errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(base+'/planeamento/disponibilidade?area=cantoneiras');
  await page.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
  const get=async path=>page.evaluate(async path=>{const r=await fetch('/planeamento/api/'+path);if(!r.ok)throw Error(await r.text());return r.json()},path);
  const sheets=(await get('raw/horas/folhas')).sheets;
  report.source=sheets.find(s=>s.key==='cantoneiras:85727cd76ce3');
  assert.equal(report.source.machine,'Peddi 8');assert.equal(report.source.hours,null);
  const resourceName='C10 Isolado Peddi 8',hoursName='C10 Isolado Folha 85727cd76ce3';
  await page.locator('#configure').click();const edit=page.locator('#edit-panel');
  if(!(await get('raw/objects/resource')).items.some(r=>r.name===resourceName)){
   await page.locator('#panel-body').getByRole('button',{name:'Adicionar',exact:true}).click();
   await edit.getByLabel('Nome',{exact:true}).fill(resourceName);
   await edit.getByLabel('Nomes equivalentes').fill('cantoneiras:Peddi 8');
   await edit.getByLabel('Operações suportadas').fill('112,119');
   await edit.getByLabel('Janela de produtividade histórica (dias)').fill('90');
   await edit.getByLabel('Horas por turno de referência').fill('8');
   await edit.getByLabel('Origem / justificação').fill('Ensaio C10 exclusivamente na cópia isolada');
   await edit.getByRole('checkbox').check();
   await page.locator('#save-config').click();await edit.waitFor({state:'hidden'});
  }
  if(!(await get('raw/objects/worked_hours')).items.some(r=>r.name===hoursName)){
   await page.locator('#panel-body').getByRole('button',{name:'Horas reais',exact:true}).click();
   await page.locator('#panel-body').getByRole('button',{name:'Adicionar',exact:true}).click();
   await edit.getByLabel('Nome',{exact:true}).fill(hoursName);
   await edit.getByLabel(/^Máquina física/).selectOption({label:resourceName});
   await edit.getByLabel(/^Âmbito das horas/).selectOption('sheet').catch(async e=>{throw Error(e.message+' UI: '+await edit.innerText())});
   await edit.getByLabel(/^Folha/).selectOption(report.source.key);
   await edit.getByLabel('Horas reais (h)',{exact:true}).fill('4');
   await edit.getByLabel('Operação (vazio se o tempo abranger várias operações)',{exact:true}).fill('112');
   await edit.getByLabel('Origem / justificação').fill('Teste isolado H09: 460,902 m validados / 4 h de ensaio = 115,2255 m/h. Não é declaração real de fábrica.');
   await edit.getByRole('button',{name:'Conferir declarações'}).click();
   await edit.locator('#hours-evidence tbody tr').waitFor();
   await edit.getByLabel('Substituir integralmente').check();
   await edit.getByLabel('Confirmo as horas reais').check();
   await page.screenshot({path:folder+'/c10-cantoneiras-horas.png',fullPage:true});
   await page.locator('#save-config').click();await edit.waitFor({state:'hidden'});
  }
  report.resource=(await get('raw/objects/resource')).items.find(r=>r.name===resourceName);
  report.saved=(await get('raw/objects/worked_hours')).items.find(r=>r.name===hoursName);
  assert.equal(report.saved.definition.hours,4);assert.equal(report.saved.definition.operation,'112');
  assert.equal(report.saved.definition.sheet_key,report.source.key);
  assert.deepEqual(report.errors,[]);
  fs.writeFileSync(folder+'/c10-hours-browser.json',JSON.stringify(report,null,2));
  console.log('Manual test declaration 4h, stable validated Cantoneiras sheet, 90-day window saved through browser.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
