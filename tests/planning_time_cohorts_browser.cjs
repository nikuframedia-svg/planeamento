const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated planning server required');
const fixture=JSON.parse(fs.readFileSync(folder+'/c10-cohorts-browser-fixture.json'));
const fmt=n=>n==null?'Por confirmar':new Intl.NumberFormat('pt-PT',{maximumFractionDigits:2}).format(n);
const close=(a,b)=>a===b || typeof a==='number'&&typeof b==='number'&&Math.abs(a-b)<=Math.max(1e-7,Math.abs(b)*1e-9);
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),
  fixture_sha256:crypto.createHash('sha256').update(fs.readFileSync(folder+'/c10-cohorts-browser-fixture.json')).digest('hex'),actual:[],historical:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  for(const sample of fixture.actual){
   await page.goto(base+'/planeamento/disponibilidade?area='+sample.area);
   await page.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   await page.locator('#search').fill(sample.machine);await page.locator('#year').fill(String(sample.year));await page.locator('#week').fill(String(sample.week));
   const response=page.waitForResponse(r=>r.url().endsWith('/raw/capacidade/consulta')&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Consultar',exact:true}).click();await response;
   const row=page.locator('#matrix tbody tr').filter({has:page.getByRole('button',{name:sample.machine,exact:true})});
   await row.first().waitFor();const cells=await row.first().locator('td').allTextContents();
   assert.equal(cells[7].trim(),fmt(sample.expected)+(sample.expected==null?`${sample.coverage.known}/${sample.coverage.total} declarações`:''));
   await row.first().getByRole('button',{name:sample.machine,exact:true}).click();
   await page.getByRole('button',{name:'Produção registada',exact:true}).click();
   const panel=page.locator('#panel-body');await panel.getByRole('cell',{name:'Folhas / período',exact:true}).waitFor();
   const tables=panel.locator('table');const evidence=tables.last();
   const rows=await evidence.locator('tbody tr').allTextContents();assert.equal(rows.length,sample.declarations.length);
   for(const declaration of sample.declarations){
    const expectedSheet=declaration.sheets[0];
    const tr=evidence.locator('tbody tr').filter({hasText:expectedSheet});assert.equal(await tr.count(),1);
    const cells=await tr.locator('td').allTextContents();assert.equal(cells[0],declaration.origin);assert.equal(cells[2],fmt(declaration.hours));
    if(declaration.reason)assert(cells[3].includes(declaration.reason));
   }
   const screenshot=`c10-cohorts-final-${sample.area}-${sample.kind}-hours.png`;
   await evidence.scrollIntoViewIfNeeded();await page.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.actual.push({area:sample.area,key:sample.key,expected:sample.expected,coverage:sample.coverage,cells,evidence:rows,screenshot});
  }
  for(const sample of fixture.historical){
   await page.goto(base+'/planeamento/raw?area='+sample.area+'&need='+encodeURIComponent(sample.key));
   const drawer=page.locator('#drawer');await drawer.getByRole('button',{name:'Taxas e horas',exact:true}).click();
   const response=page.waitForResponse(r=>r.url().endsWith('/raw/produtividade/'+sample.hash)&&r.status()===200);
   // The selected fixture uses a primary historical operation in both areas.
   await drawer.getByRole('button',{name:'Histórico usado / exclusões',exact:true}).first().click();
   const evidence=await(await response).json();assert.equal(evidence.hash,sample.hash);
   for(const key of ['volume','hours','value','sheet_count','event_count'])assert(close(evidence[key],sample.expected[key]),key);
   assert.deepEqual(evidence.excluded,sample.expected.excluded);
   assert.equal(evidence.cohorts.length,sample.expected.cohorts.length);
   for(let i=0;i<evidence.cohorts.length;i++){
    const actual=evidence.cohorts[i],wanted=sample.expected.cohorts[i];
    for(const key of ['hours','volume'])assert(close(actual[key],wanted[key]),key);
    assert.deepEqual(actual.events,wanted.events);assert.deepEqual(actual.sheets,wanted.sheets);
   }
   await drawer.getByRole('columnheader',{name:'Excluída',exact:true}).waitFor();const text=await drawer.innerText();
   for(const excluded of sample.expected.excluded){assert(text.includes(excluded.key));for(const reason of excluded.reasons)assert(text.includes(reason));}
   for(const accepted of sample.expected.cohorts)assert(text.includes(accepted.key));
   const screenshot=`c10-cohorts-final-${sample.area}-historical.png`;
   await drawer.getByRole('columnheader',{name:'Coorte',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.historical.push({area:sample.area,key:sample.key,hash:sample.hash,expected:sample.expected,observed:evidence,screenshot});
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/c10-cohorts-browser-final.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
