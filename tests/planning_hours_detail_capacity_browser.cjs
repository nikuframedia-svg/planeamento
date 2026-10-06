const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 const report={base,at:new Date().toISOString(),script_sha256:require('node:crypto').createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),areas:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>report.errors.push(e.message));
  const audit=JSON.parse(fs.readFileSync(folder+'/c04-semantic-capacity-parity.json','utf8'));
  for(const area of ['perfis','cantoneiras']){
   const sample=audit.areas[area].historical_sample;assert(sample,'Historical sample in '+area);
   await page.goto(base+'/planeamento/raw?area='+area+'&need='+encodeURIComponent(sample.key));
   await page.getByRole('button',{name:'Taxas e horas',exact:true}).click();
   const drawer=page.locator('#drawer');await drawer.getByText('Histórico',{exact:true}).first().waitFor();
   const response=page.waitForResponse(r=>r.url().includes('/raw/produtividade/')&&r.status()===200);
   await drawer.getByRole('button',{name:'Histórico usado / exclusões',exact:true}).first().click();
   const evidence=await(await response).json();assert.equal(evidence.hash,sample.applied_rate.history_hash);
   assert(evidence.sheet_count>0&&evidence.event_count>0&&evidence.hours>0);
   assert(Math.abs(evidence.value-evidence.volume/evidence.hours)<1e-7);
   if(area==='cantoneiras')assert(Math.abs(evidence.value-115.2255)<1e-7);
   await drawer.getByText('Coorte',{exact:true}).waitFor();
   const text=await drawer.innerText();assert(text.includes('Excluída'));
   await page.screenshot({path:folder+'/c04-hours-detail-'+area+'-raw-historico.png',fullPage:true});
   // Read the same selected rate through the capacity support UI.
   await page.goto(base+'/planeamento/disponibilidade?area='+area);
   await page.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   await page.locator('#search').fill(sample.capacity.machine);
   if(sample.capacity.year&&sample.capacity.week){
    await page.locator('#year').fill(String(sample.capacity.year));
    await page.locator('#week').fill(String(sample.capacity.week));
   }else await page.locator('#unscheduled').check();
   const overviewResponse=page.waitForResponse(r=>r.url().endsWith('/raw/capacidade/consulta')&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Consultar',exact:true}).click();
   await overviewResponse;
   let machineRow=page.locator('#matrix tbody tr').filter({has:page.getByRole('button',{name:sample.capacity.machine,exact:true})});
   if(!sample.capacity.year)machineRow=machineRow.filter({hasText:sample.capacity.week?'W'+sample.capacity.week+' · ano por confirmar':'Por calendarizar'});
   await machineRow.first().getByRole('button',{name:sample.capacity.machine,exact:true}).click();
   const panel=page.locator('#panel-body');
   let found=false;
   for(let index=0;index<35;index++){
    await panel.getByText('A carga prevista usa taxa manual aplicável',{exact:false}).waitFor();
    const target=panel.locator('tr').filter({hasText:sample.capacity.of}).getByRole('button',{name:sample.values.component_ref,exact:true});
    if(await target.count()){await target.first().click();found=true;break}
    const next=panel.getByRole('button',{name:'Seguinte →',exact:true});
    if(await next.isDisabled())break;
    await next.click();
   }
   assert(found,'Sample present in capacity pieces');
   const expectedVolume=sample.capacity.quantity*(area==='perfis'?sample.values.section_unit:sample.values.length_mm/1000);
   const displayed=await panel.locator('tr').filter({has:page.getByRole('cell',{name:'Volume pendente usado',exact:true})}).locator('td').nth(1).innerText();
   const expectedText=new Intl.NumberFormat('pt-PT',{maximumFractionDigits:2}).format(expectedVolume);
   assert.equal(displayed,expectedText+(area==='perfis'?' mm²':' m'));
   assert((await panel.locator('tr').filter({has:page.getByRole('cell',{name:'Fórmula aplicada',exact:true})}).innerText()).includes(area==='perfis'?'área unitária':'comprimento'));
   await panel.getByRole('cell',{name:'Preparação aplicada (min)',exact:true}).waitFor();
   const capResponse=page.waitForResponse(r=>r.url().includes('/raw/produtividade/')&&r.status()===200);
   await panel.getByRole('button',{name:'Histórico usado / exclusões',exact:true}).click();
   const capEvidence=await(await capResponse).json();assert.equal(capEvidence.hash,evidence.hash);
   await panel.getByText('Produtividade histórica',{exact:false}).waitFor();
   await page.screenshot({path:folder+'/c04-hours-detail-'+area+'-capacidade-historico.png',fullPage:true});
   report.areas.push({area,key:sample.key,source:'Histórico',evidence,rawText:text,capacityText:await panel.innerText(),expectedVolume,displayedVolume:displayed});
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
  fs.writeFileSync(folder+'/c04-hours-detail-capacity-browser.json',JSON.stringify(report,null,2));
  console.log('RAW and capacity display the same traceable historical estimates in both areas.');
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}finally{fs.writeFileSync(folder+'/c04-hours-detail-capacity-browser.json',JSON.stringify(report,null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
