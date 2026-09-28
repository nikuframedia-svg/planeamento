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
   const pages=await Promise.all(Array.from({length:4},()=>browser.newPage({viewport:{width:1440,height:1050}})));
   pages.forEach(p=>p.on('pageerror',e=>report.errors.push(e.message)));
   const [form,raw,oldCap,newCap]=pages;
   const item={area:fixture.area,need_id:fixture.need_id};report.areas.push(item);
   async function capacityPage(page,index,week){
    await page.goto(base+'/planeamento/disponibilidade?area='+fixture.area);
    await page.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
    await page.locator('#search').fill('C05 Ensaio '+fixture.area+' '+(index+1));
    await page.locator('#year').fill('2027');await page.locator('#week').fill(String(week));
    const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/raw/capacidade/consulta')&&r.request().postDataJSON().year==='2027'),page.getByRole('button',{name:'Consultar',exact:true}).click()]);
    assert.equal(response.status(),200);
    await page.waitForFunction(name=>document.querySelector('#matrix tbody tr')?.textContent.includes(name)&&document.querySelectorAll('#matrix tbody tr').length===1,'C05 Ensaio '+fixture.area+' '+(index+1));
    await page.locator('#matrix tbody tr').getByRole('button',{name:'C05 Ensaio '+fixture.area+' '+(index+1),exact:true}).click();
    await page.locator('#panel-body table').waitFor();
   }
   await capacityPage(oldCap,0,1);await capacityPage(newCap,1,2);
   assert.equal((await oldCap.locator('#matrix tbody tr td').allTextContents())[4],String(20/fixture.rate));
   assert.equal((await newCap.locator('#matrix tbody tr td').allTextContents())[4],'0');
   await raw.goto(base+'/planeamento/raw?area='+fixture.area+'&q='+encodeURIComponent('INTEGRAL-'+fixture.area));
   await raw.waitForFunction(id=>Raw.state.data?.rows.some(r=>r.need_id===id),fixture.need_id);
   await form.goto(base+'/planeamento/preparar?area='+fixture.area+'&necessidade='+fixture.need_id);
   await form.locator('#field-quantity_required').waitFor();
   await form.locator('#field-quantity_required').fill('40');
   await form.locator('#field-machine').selectOption(fixture.machines[1]);
   await form.locator('#field-expected_date').fill('2027-01-11');
   const started=Date.now();
   const [response]=await Promise.all([form.waitForResponse(r=>r.url().endsWith('/necessidades/registar')&&r.request().method()==='POST',{timeout:60000}),form.locator('button[name=draft]').click()]);
   const returned=Date.now(),saved=await response.json();assert.equal(response.status(),200,JSON.stringify(saved));
   item.requestMs=returned-started;item.saved=saved;
   await raw.waitForFunction(({id})=>Raw.state.data?.rows.find(r=>r.need_id===id)?.values.remaining===40,{id:fixture.need_id},{timeout:12000});
   item.rawResponseToVisibleMs=Date.now()-returned;
   const expected=40/fixture.rate;
   await Promise.all([
    raw.waitForFunction(({id,h,pct})=>{const r=Raw.state.data?.rows.find(r=>r.need_id===id);return r?.values.theoretical_hours===h&&Math.abs(r?.values.hours_pct-pct)<1e-8&&!Raw.state.data.aggregates_pending;},{id:fixture.need_id,h:expected,pct:expected*100/14},{timeout:15000}),
    oldCap.waitForFunction(()=>document.querySelector('#matrix tbody tr')?.children[4]?.textContent==='0'&&document.querySelectorAll('#panel-body tbody tr').length===0,null,{timeout:15000}),
    newCap.waitForFunction(h=>document.querySelector('#matrix tbody tr')?.children[4]?.textContent===String(h)&&[...document.querySelectorAll('#panel-body tbody tr')].some(r=>r.children[5]?.textContent==='40'&&r.children[6]?.textContent===String(h)),expected,{timeout:15000})
   ]);
   item.aggregatesResponseToVisibleMs=Date.now()-returned;
   item.raw=await raw.evaluate(id=>Raw.state.data.rows.find(r=>r.need_id===id),fixture.need_id);
   item.oldCells=await oldCap.locator('#matrix tbody tr td').allTextContents();item.newCells=await newCap.locator('#matrix tbody tr td').allTextContents();
   await newCap.screenshot({path:folder+'/c05-'+fixture.area+'-capacity-incremental.png',fullPage:true});
   assert(item.rawResponseToVisibleMs<=2000,'RAW response-to-visible exceeds2s: '+item.rawResponseToVisibleMs);
   assert(item.aggregatesResponseToVisibleMs<=10000,'Aggregates response-to-visible exceeds10s: '+item.aggregatesResponseToVisibleMs);
   await Promise.all(pages.map(p=>p.close()));
   fs.writeFileSync(folder+'/c05-capacity-incremental-browser.json',JSON.stringify(report,null,2));
  }
  assert.deepEqual(report.errors,[]);report.result='passed';console.log('Both areas: old/new machine-weeks and open capacity details update without F5; RAW<=2s and aggregates<=10s after save response.');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/c05-capacity-incremental-browser.json',JSON.stringify(report,null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
