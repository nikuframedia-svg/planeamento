// Registo manual só com o essencial (07/10/2026), contra uma base descartável e um arquivo de PDF temporário.
// Um só «Guardar», avisos discretos só depois de mexer no campo (ou de guardar), «Mais opções» só com
// Observações, «Qtd em falta», PDF de outra OF sem bloqueio e aviso de saída só com algo escrito.
const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),base=process.env.PLANNING_CHECK_BASE,errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR',e.message)});
 const notes=()=>page.locator('#preparation .field-note').evaluateAll(n=>n.map(x=>x.textContent).filter(Boolean));
 const previewDone=()=>page.waitForFunction(()=>!/A calcular/.test(document.querySelector('#preview-status')?.textContent||''));
 await page.goto(base+'/planeamento/manual?of=OF4200&area=perfis&new=1');
 await page.locator('#field-component_ref').waitFor({state:'visible'});
 assert.equal(await page.locator('#local-of').inputValue(),'OF4200');
 // Ecrã simples: «Dados da peça» aberta; o resto em blocos fechados; as colunas do Excel sem o Picking ano.
 assert.deepEqual(await page.locator('#preparation h2').allTextContents(),['Dados da peça','Características de corte']);
 assert.deepEqual(await page.locator('#preparation details.section>summary').allTextContents(),['Mais opções','Trabalho a preparar','Pré-visualização dos cálculos','Produção e histórico']);
 assert.deepEqual(await page.locator('#preparation details.section').evaluateAll(n=>n.map(d=>d.open)),[false,false,false,false]);
 assert.deepEqual(await page.locator('#piece-fields > .field:not([hidden]) label').allTextContents(),['Data Corte','Referência','Tipo de Material','Designação Perfil','QTD','Ø Externo (mm)','Largura (mm)','Altura (mm)','Espessura (mm)','Comp. (mm)','Ang. (°)','Qual.','Abocardar','Picking semana','Equipa','Pav.','Máquina']);
 assert.deepEqual(await page.locator('#extra-fields > .field label').allTextContents(),['Observações']);
 assert.deepEqual(await page.locator('#operation-fields > .field label').allTextContents(),['Operação','Qtd em falta (un.)']);
 assert.equal(await page.locator('#piece-fields p.help:not(.field-note)').count(),0,'sem textos de ajuda na primeira secção');
 for(const id of ['quantity_to_plan','expected_date','planned_week','picking_year','material_requested','stock_length_mm','custom_profile','geometry','identity_discriminator'])assert.equal(await page.locator('#field-'+id).count(),0,id);
 for(const gone of ['#pdf-conflict','#duplicates','#conference-dialog','#conference-open','button[name=draft]'])assert.equal(await page.locator(gone).count(),0,gone);
 assert.equal(await page.locator('#preparation button[type=submit]').count(),1);
 assert.equal(await page.locator('button[name=ready]').textContent(),'Guardar');
 assert.ok(!await page.locator('#field-abocardar').isChecked());
 // Nenhum aviso antes de escrever.
 await previewDone();assert.deepEqual(await notes(),[]);
 await page.locator('#field-component_ref').fill('BROWSER-NEW');
 await page.locator('#field-material_type').fill('Tubo redondo');
 await page.locator('#field-profile').fill('88.9x3');
 await page.locator('#field-outer_diameter_mm').fill('88,9');
 await page.locator('#field-thickness_mm').fill('3');
 await page.locator('#field-angle_deg').fill('0');
 assert.equal(await page.locator('#field-operation').inputValue(),'corte');
 await page.locator('#field-length_mm').fill('1000');
 // QTD fora de inteiro: aviso discreto ao lado do campo, sem marcar o campo como erro.
 await page.locator('#field-quantity_required').fill('2,5');
 await page.locator('#note-quantity_required').filter({hasText:'número inteiro'}).waitFor();
 assert.equal(await page.locator('#field-quantity_required').getAttribute('aria-invalid'),null);
 await page.locator('#field-quantity_required').fill('100');
 await page.waitForFunction(()=>!document.querySelector('#note-quantity_required').textContent);
 // Máquina vazia: sem aviso enquanto ninguém lhe mexe nem guarda.
 await previewDone();assert.equal(await page.locator('#note-machine').textContent(),'');
 // Sair com algo escrito pede uma escolha; continuar mantém tudo.
 await page.locator('#pdf-link').click();await page.locator('#leave-dialog').waitFor({state:'visible'});
 assert.match(await page.locator('#leave-dialog').innerText(),/Guarda antes de continuar/);
 await page.getByRole('button',{name:'Continuar a editar',exact:true}).click();assert.equal(await page.locator('#field-length_mm').inputValue(),'1000');
 await page.locator('#more-options>summary').click();await page.locator('#field-notes').fill('Conservar esta observação.');
 await page.locator('#work-details>summary').click();await page.locator('#field-remaining_declared').fill('70');
 await page.locator('#field-abocardar').check();
 const sent=page.waitForRequest(r=>r.url().endsWith('/necessidades/registar'));
 await page.locator('button[name=ready]').click();
 const body=(await sent).postDataJSON();
 assert.equal(body.record_status,'ready');assert.ok(Array.isArray(body.changed_fields)&&body.changed_fields.includes('remaining_declared'));
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Registo guardado'));
 const needId=new URL(page.url()).searchParams.get('necessidade');assert.ok(needId);
 // Depois de guardar, os avisos essenciais aparecem em todos os campos.
 await page.locator('#note-machine').filter({hasText:'Sem máquina: será usada a sugerida ao planear'}).waitFor();
 assert.equal(await page.locator('#field-notes').inputValue(),'Conservar esta observação.');
 assert.equal(await page.locator('#field-remaining_declared').inputValue(),'70');
 assert.ok(await page.locator('#field-abocardar').isChecked());
 await page.locator('#secondary-details>summary').click();
 assert.equal(await page.getByRole('button',{name:'Confirmar quantidade em falta'}).count(),0);
 await page.getByRole('button',{name:'Ver origem e alterações',exact:true}).click();await page.locator('#history-dialog').waitFor({state:'visible'});
 assert.match(await page.locator('#history-content').innerText(),/Utilizador não identificado/);await page.locator('#history-dialog [data-close]').click();
 await page.getByRole('button',{name:'Ver produção registada',exact:true}).click();await page.locator('#evidence-dialog').waitFor({state:'visible'});
 assert.equal(await page.locator('#evidence-operation option').filter({hasText:'Abocardar'}).count(),1);
 await page.locator('#evidence-dialog [data-close]').click();
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 // A 720 CSS-pixel viewport represents desktop at 200%; it must reflow.
 await page.setViewportSize({width:720,height:525});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.setViewportSize({width:1440,height:1050});
 // PDF de outra OF: usa a OF do PDF e avisa, sem bloquear; a mesma peça é reconhecida.
 await page.goto(base+'/planeamento/preparar?document=browser-doc&piece=browser-piece&of=OF9999');
 await page.locator('#field-component_ref').waitFor({state:'visible'});
 assert.match(await page.locator('#status').textContent(),/O PDF é da OF OF4200 \(pediste OF9999\)/);
 assert.equal(await page.locator('#field-component_ref').inputValue(),'BROWSER-NEW');
 await page.locator('button[name=ready]').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Registo guardado'));
 assert.equal(new URL(page.url()).searchParams.get('necessidade'),needId);
 assert.equal(await page.locator('#field-notes').inputValue(),'Conservar esta observação.');
 const list=await page.request.get(base+'/planeamento/api/necessidades/lista?of=OF4200').then(r=>r.json());assert.equal(list.needs.length,1);
 // Reabrir o PDF ligado mostra os valores humanos, sem os substituir pelo PDF.
 await page.locator('#more-options>summary').click();await page.locator('#field-notes').fill('Decisão humana depois do PDF.');
 await page.locator('button[name=ready]').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Registo guardado'));
 await page.goto(base+'/planeamento/preparar?document=browser-doc&piece=browser-piece');await page.locator('#field-component_ref').waitFor({state:'visible'});
 assert.equal(await page.locator('#field-notes').inputValue(),'Decisão humana depois do PDF.');
 assert.equal(await page.locator('.field-attention').count(),0,'sem caixas amarelas do PDF');
 await page.locator('button[name=ready]').click();await page.getByRole('button',{name:'Abrir peça seguinte do PDF'}).waitFor({state:'visible'});await page.getByRole('button',{name:'Abrir peça seguinte do PDF'}).click();
 await page.waitForFunction(()=>document.querySelector('#field-component_ref')?.value==='SECOND-PIECE');
 // Abrir uma peça não conta como alteração: sair não pergunta nada.
 await page.locator('#manual-link').click();await page.waitForURL(/\/planeamento\/manual/);
 assert.ok(!await page.locator('#leave-dialog').isVisible());
 // Com algo escrito, descartar sai sem gravar.
 await page.goto(base+'/planeamento/preparar?document=browser-doc&piece=second-piece');
 await page.waitForFunction(()=>document.querySelector('#field-component_ref')?.value==='SECOND-PIECE');
 await page.locator('#field-length_mm').fill('1200');
 await page.locator('#manual-link').click();await page.locator('#leave-dialog').waitFor({state:'visible'});await page.getByRole('button',{name:'Descartar alterações'}).click();
 await page.locator('#area').waitFor({state:'visible'});
 // Unknown area: the last sector used (or MTG3) is chosen at once, so the page never shows a different form.
 await page.route('**/api/ordens/OF4200',async route=>{const response=await route.fetch();const json=await response.json();json.context.sources=[];await route.fulfill({response,json})});
 await page.goto(base+'/planeamento/manual?of=OF4200&new=1');await page.locator('#area').waitFor({state:'visible'});await page.locator('#catalog-fields').waitFor({state:'visible'});assert.equal(await page.locator('#area').inputValue(),'perfis');
 assert.ok(await page.locator('#field-angle_deg').isVisible());assert.ok(await page.locator('#field-grade').isVisible());assert.ok(await page.locator('#field-length_mm').isVisible());
 assert.deepEqual(errors,[]);console.log(JSON.stringify({manual:true,pdf:true,sharedNeed:true,notesAfterEdit:true,declaredRemaining:true,history:true,mobile:true,zoomReflow:true,leaveOnlyWhenTyped:true,pdfOfMismatch:true,unknownArea:true,errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
