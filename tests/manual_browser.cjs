// Registo manual (/planeamento/manual) contra o serviço em 127.0.0.1:8113, sem gravar nada (06/10/2026).
// Todas as chamadas que não são GET são intercetadas: a pré-visualização devolve uma resposta de ensaio e o
// «Guardar» é recusado depois de se verificar o pedido.
// MANUAL_FIXTURE (opcional): JSON com o arranjo novo dos campos e as sugestões, para ensaiar o JS novo antes do
// reinício do serviço (catálogo antigo e endpoint de sugestões ainda sem rota). Depois do reinício corre sem ele.
const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE||'http://127.0.0.1:8113';
const fixture=process.env.MANUAL_FIXTURE?JSON.parse(fs.readFileSync(process.env.MANUAL_FIXTURE,'utf8')):null;
const FIELDS={
 perfis:['Data Corte','Referência','Tipo de Material','Designação Perfil','QTD','Ø Externo (mm)','Largura (mm)','Altura (mm)','Espessura (mm)','Comp. (mm)','Ang. (°)','Qual.','Abocardar','Picking semana','Picking ano','Equipa','Pav.','Máquina'],
 cantoneiras:['Data Corte','Ref.','Tipo de material','QTD','Des. Material','Comp. (mm)','1.ª Oper.','2.ª Oper.','Equipa','Pav.','Máquina']};
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const writes=[];
 try{
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  await context.route('**/*',async route=>{
   const req=route.request();
   if(req.method()!=='GET'){
    writes.push({url:req.url(),body:req.postDataJSON?.()??null});
    if(req.url().includes('/necessidades/prever'))return route.fulfill({json:{preview:true,saved:false,results:[],row:{values:{section_unit:522.9,weight_unit:3.25}}}});
    return route.fulfill({status:503,json:{error:'Gravação intercetada pelo teste.'}});
   }
   if(fixture&&req.url().includes('/planeamento/api/catalogos')){
    const response=await route.fetch(),json=await response.json(),arranged=fixture.catalog[json.area]||{};
    for(const f of json.fields)Object.assign(f,arranged[f.id]||{});
    return route.fulfill({response,json});
   }
   const m=req.url().match(/\/api\/ordens\/([^/?]+)\/sugestoes\?(.*)$/);
   if(fixture&&m){
    const response=await route.fetch();
    if(response.status()!==404)return route.fulfill({response});
    const byRef=fixture.suggestions[decodeURIComponent(m[1])]||{},ref=new URLSearchParams(m[2]).get('ref')||'';
    return route.fulfill({json:{fields:byRef[ref]||byRef['NOVA-REF']||byRef['']||{}}});
   }
   return route.continue();
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const labels=()=>page.locator('#piece-fields > .field:not([hidden]) label').allTextContents();
  const value=id=>page.locator('#field-'+id).inputValue();

  // PERFIS, OF existente: peça nova → Equipa, Pav. e Data Corte sugeridos pelas outras linhas da OF.
  await page.goto(base+'/planeamento/manual?of=OF266404');
  await page.locator('#catalog-fields').waitFor({state:'visible'});
  assert.equal(await page.locator('#area').inputValue(),'perfis');
  assert.deepEqual(await labels(),FIELDS.perfis);
  assert.equal(await page.locator('#piece-fields p.help').count(),0);
  assert.deepEqual(await page.locator('#preparation details.section').evaluateAll(n=>n.map(d=>d.open)),[false,false,false,false]);
  assert.equal(await page.locator('#preparation button[type=submit]:visible').count(),1);
  await page.locator('#field-component_ref').fill('ENSAIO-NOVA');
  await page.waitForFunction(()=>document.querySelector('#field-team')?.classList.contains('suggested'));
  assert.equal(await value('team'),'Colunas');assert.equal(await value('pavilion'),'6');assert.equal(await value('cut_date'),'2026-10-23');
  assert.match(await page.locator('#field-team').getAttribute('title'),/^sugerido: outras linhas da OF/);
  // Escrever por cima: deixa de ser sugerido e o Pav. segue a Equipa escrita (quando a sugestão vem do serviço).
  await page.locator('#field-team').fill('Equipa 5');
  assert.equal(await page.locator('#field-team').evaluate(n=>n.classList.contains('suggested')),false);
  await page.locator('#field-quantity_required').fill('2,5');
  await page.locator('#error-quantity_required').filter({hasText:'inteiro'}).waitFor();
  await page.locator('#field-quantity_required').fill('25');

  // PERFIS, linha do Excel clicada: nada do Excel é sobreposto; a Máquina vazia é sugerida.
  page.once('dialog',d=>d.accept());
  await page.goto(base+'/planeamento/manual?of=OF266404');
  await page.locator('#references button').first().waitFor();
  await page.locator('#references button').first().click();
  await page.waitForFunction(()=>document.querySelector('#field-component_ref')?.value);
  await page.waitForFunction(()=>document.querySelector('#field-machine')?.value);
  for(const id of ['team','pavilion','machine','cut_date','profile','length_mm','quantity_required'])assert.ok(await value(id),'perfis sem '+id);
  assert.equal(await page.locator('#field-team').evaluate(n=>n.classList.contains('suggested')),false,'a Equipa veio do Excel');
  await page.locator('#piece-calc').filter({hasText:'Área de secção'}).waitFor();
  await page.locator('button[name=ready]').click();
  await page.locator('#error').filter({hasText:'intercetada'}).waitFor();
  const saved=writes.find(w=>w.url.includes('/necessidades/registar'));
  assert.ok(saved,'pedido de gravação');assert.equal(saved.body.record_status,'ready');
  assert.ok(saved.body.values.machine&&saved.body.values.team&&saved.body.values.pavilion);

  // CANTONEIRAS, OF existente.
  await page.evaluate(()=>{window.onbeforeunload=null});
  const fresh=await context.newPage();fresh.on('pageerror',e=>errors.push(e.message));
  await fresh.goto(base+'/planeamento/manual?of=OF265002');
  await fresh.locator('#catalog-fields').waitFor({state:'visible'});
  assert.equal(await fresh.locator('#area').inputValue(),'cantoneiras');
  assert.deepEqual(await fresh.locator('#piece-fields > .field:not([hidden]) label').allTextContents(),FIELDS.cantoneiras);
  await fresh.locator('#references button').first().click();
  await fresh.waitForFunction(()=>document.querySelector('#field-component_ref')?.value&&document.querySelector('#field-machine')?.value);
  for(const id of ['team','pavilion','machine','cut_date','profile','length_mm','operation','quantity_required'])assert.ok(await fresh.locator('#field-'+id).inputValue(),'cantoneiras sem '+id);
  // 390 px sem deslocamento horizontal.
  await fresh.setViewportSize({width:390,height:844});
  assert.ok(await fresh.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'390 px com scroll horizontal');
  if(process.env.MANUAL_PROOF)await fresh.screenshot({path:process.env.MANUAL_PROOF,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);
  assert.ok(writes.every(w=>/necessidades\/(prever|registar)/.test(w.url)),JSON.stringify(writes.map(w=>w.url)));
  console.log(JSON.stringify({perfis:true,cantoneiras:true,suggested:true,saveIntercepted:true,mobile390:true,fixture:Boolean(fixture),writes:writes.length}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
