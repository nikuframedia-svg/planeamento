const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||chromium.executablePath(),headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:940}}),errors=[],bad=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('response',response=>{if(response.url().includes('/api/raw/gantt')&&response.status()>=400)bad.push(response.status()+' '+response.url())});
  await page.goto(process.env.PLANNING_CHECK_BASE+'/planeamento/gantt/detalhe');
  await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('Fontes publicadas'));
  await page.waitForFunction(()=>document.querySelector('#pending-count').textContent.includes('operações'));
  assert.ok((await page.locator('#pending-count').innerText()).includes('operações'));
  assert.equal(await page.locator('#compare').inputValue(),'source');
  assert.equal(await page.locator('#source-controls').isVisible(),true);
  assert.equal(await page.locator('#accept').isDisabled(),true);
  const available=await (await page.request.get(process.env.PLANNING_CHECK_BASE+'/planeamento/api/raw/gantt/operations')).json();
  assert.equal(await page.locator('.capacity-card').count(),Object.keys(available.resources).length);
  if(available.source_plan.entries.length){
    const day=new Date(available.source_plan.entries[0].start_date+'T12:00:00Z');
    day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
    await page.locator('#source-week').selectOption(day.toISOString().slice(0,10));
    assert.ok(await page.locator('.forecast-bar').count()>0);
    await page.locator('.forecast-bar').first().click();
    assert.ok(await page.locator('#selected-key').inputValue());
  }
  await page.locator('#scenario-name').fill('Piloto Perfis');
  await page.locator('#generate').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('concluída'),undefined,{timeout:60000});
  assert.equal(await page.locator('#accept').isDisabled(),false);
  assert.ok((await page.locator('#summary').innerText()).includes('Calendarizadas'));
  assert.ok(await page.locator('.milestone-bucket').count()>0,'marcos visíveis mesmo para operações sem barra');
  await page.locator('.operation-row').filter({hasText:'corte'}).first().click();
  await page.locator('#urgent').check();
  await page.locator('#picking-year').fill('2026');
  await page.locator('#edit-form .primary').click();
  await page.waitForFunction(()=>document.querySelector('#scenario').selectedOptions[0]?.textContent.includes('r2'));
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('concluída'),undefined,{timeout:60000});
  assert.equal(await page.locator('#accept').isDisabled(),false);
  // Proposta desatualizada (07/10/2026): recalcula sozinha quando as fontes mudaram, no máximo duas vezes por ação;
  // se continuar desatualizada avisa numa frase curta e Aceitar fica desligado.
  let solves=0;
  page.on('request',request=>{if(request.url().endsWith('/api/raw/gantt/solve'))solves++});
  const staleAs=reason=>page.route('**/gantt/jobs/*',async route=>{
    const response=await route.fetch();const result=await response.json();
    await route.fulfill({response,json:{...result,stale:true,stale_reason:reason}});
  });
  await staleAs('fontes');
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>/Gera uma nova proposta/.test(document.querySelector('#notice').textContent),undefined,{timeout:120000});
  assert.equal(solves,2,'duas recalculações automáticas e depois para');
  assert.match(await page.locator('#source-state').innerText(),/desatualizada/);
  assert.equal(await page.locator('#accept').isDisabled(),true);
  await page.unroute('**/gantt/jobs/*');
  // Outra versão do motor (depois de cada atualização da app): ao abrir recalcula sozinha uma vez; se a nova também vier
  // de outra versão, a app e o worker estão em versões diferentes e fica só o aviso. Espera-se pelo aviso final e não
  // pela frase do recálculo: largar a rota a meio de um pedido rebenta o teste («Route is already handled»).
  await staleAs('motor');solves=0;
  await page.evaluate(()=>{window.notices=[];new MutationObserver(records=>{for(const record of records)
    for(const node of record.addedNodes)window.notices.push(node.textContent)}).observe(document.querySelector('#notice'),{childList:true})});
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('calculada com outra versão do motor'),undefined,{timeout:120000});
  assert.equal(solves,1,'uma recalculação automática e depois para');
  assert.ok((await page.evaluate(()=>window.notices)).includes('A proposta era de outra versão do motor: a recalcular sozinha.'));
  assert.equal(await page.locator('#accept').isDisabled(),true);
  await page.unroute('**/gantt/jobs/*');
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelector('#source-state').textContent.includes('Fontes publicadas atuais'));
  await page.waitForFunction(()=>!document.querySelector('#accept').disabled);
  await page.locator('#accept').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('aceite'));
  assert.equal(await page.locator('#accepted-state').innerText(),'Plano aceite atual');
  await page.route('**/gantt/scenarios',async route=>{
    const response=await route.fetch();const result=await response.json();
    await route.fulfill({response,json:{...result,scenarios:result.scenarios.map(item=>({...item,stale:true}))}});
  });
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelector('#accepted-state').textContent.includes('Plano aceite desatualizado'));
  assert.equal(await page.locator('#source-state').innerText(),'Fontes publicadas atuais');
  await page.unroute('**/gantt/scenarios');
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelector('#accepted-state').textContent.includes('Plano aceite atual'));
  await page.locator('#compare').selectOption('accepted');
  await page.locator('#scale').selectOption('week');
  await page.screenshot({path:process.env.GANTT_EVIDENCE+'/gantt-piloto.png',fullPage:true});
  await page.reload();
  await page.locator('#scenario').selectOption(await page.locator('#scenario option').nth(1).getAttribute('value'));
  await page.waitForFunction(()=>document.querySelector('#scenario-name').value==='Piloto Perfis');
  await page.waitForFunction(()=>document.querySelector('#compare').value==='accepted');
  await page.locator('.operation-row').filter({hasText:'corte'}).first().click();
  assert.equal(await page.locator('#urgent').isChecked(),true);
  assert.deepEqual(errors,[]);assert.deepEqual(bad,[]);
  await browser.close();console.log('Gantt: gerar, aceitar, comparar, reabrir e navegar sem erros');
})().catch(error=>{console.error(error);process.exit(1)});
