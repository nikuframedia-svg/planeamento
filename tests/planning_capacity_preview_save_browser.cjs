const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Explicit full clone required');
const close=(actual,expected)=>assert(Math.abs(actual-expected)<1e-8,`${actual} != ${expected}`);
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-background-timer-throttling']});
 const report={at:new Date().toISOString(),base,worker:'Isolated real worker; no direct rebuild from test',areas:[],errors:[]};
 try{
  const fixtures=JSON.parse(fs.readFileSync(folder+'/c05-capacity-live-fixtures.json','utf8'));
  for(const fixture of fixtures.areas){
   const pages=await Promise.all(Array.from({length:3},()=>browser.newPage({viewport:{width:1440,height:1050}})));
   pages.forEach(p=>p.on('pageerror',e=>report.errors.push(e.message)));
   const [form,raw,cap]=pages;
   const item={area:fixture.area,need_id:fixture.need_id,steps:[]};report.areas.push(item);
   await raw.goto(base+'/planeamento/raw?area='+fixture.area+'&q='+encodeURIComponent('INTEGRAL-'+fixture.area));
   await raw.waitForFunction(id=>Raw.state.data?.rows.some(r=>r.need_id===id),fixture.need_id);
   await cap.goto(base+'/planeamento/disponibilidade?area='+fixture.area);
   await cap.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   const machineName='C05 Ensaio '+fixture.area+' 2';
   await cap.locator('#search').fill(machineName);await cap.locator('#year').fill('2027');await cap.locator('#week').fill('2');
   await cap.getByRole('button',{name:'Consultar',exact:true}).click();
   await cap.waitForFunction(name=>document.querySelectorAll('#matrix tbody tr').length===1&&document.querySelector('#matrix tbody tr')?.textContent.includes(name),machineName);
   await cap.locator('#matrix tbody tr').getByRole('button',{name:machineName,exact:true}).click();
   await cap.locator('#panel-body table').waitFor();
   await form.goto(base+'/planeamento/preparar?area='+fixture.area+'&necessidade='+fixture.need_id);
   await form.waitForFunction(()=>document.querySelector('#preview-status').textContent.startsWith('Pré-visualização calculada'));
   const initial=Number(await form.locator('#field-quantity_required').inputValue());
   assert([40,60].includes(initial));item.initialQuantity=initial;
   // If an interrupted trial saved Q60, first restore its initial Q40 visibly.
   for(const q of initial===60?[40,60,40]:[60,40]){
    const pendingPreview=form.waitForResponse(r=>r.url().endsWith('/necessidades/prever')&&Number(r.request().postDataJSON().values.quantity_required)===q);
    await form.locator('#field-quantity_required').fill(String(q));const simulated=await(await pendingPreview).json();
    assert.equal(simulated.capacity_preview?.available,true);
    const hours=q/(fixture.rate*2),pct=hours/16*100;
    close(simulated.row.values.theoretical_hours,hours);close(simulated.row.values.hours_pct,pct);
    await form.waitForFunction(value=>document.querySelector('#preview-results tr[data-preview-field=hours_pct] td:nth-child(2)')?.textContent===String(value)+' %',pct);
    const start=Date.now();
    const [received]=await Promise.all([form.waitForResponse(r=>r.url().endsWith('/necessidades/registar')&&r.request().method()==='POST',{timeout:60000}),form.locator('button[name=draft]').click()]);
    const returned=Date.now(),saved=await received.json();assert.equal(received.status(),200,JSON.stringify(saved));
    assert.equal(saved.publication.status,'published');
    const published=saved.publication.rows.find(r=>r.need_id===fixture.need_id);
    assert.equal(published.values.quantity_required,q);assert.equal(published.revision,saved.revision);
    const step={quantity:q,requestMs:returned-start,preview:simulated.row,save:saved};item.steps.push(step);
    await raw.waitForFunction(({id,q,revision})=>{const row=Raw.state.data?.rows.find(r=>r.need_id===id);return row?.values.remaining===q&&row.revision===revision;},{id:fixture.need_id,q,revision:saved.revision},{timeout:12000});
    step.rawResponseToVisibleMs=Date.now()-returned;
    await Promise.all([
     raw.waitForFunction(({id,h,pct})=>{const r=Raw.state.data?.rows.find(r=>r.need_id===id);return r?.values.theoretical_hours===h&&Math.abs(r?.values.hours_pct-pct)<1e-8&&!Raw.state.data.aggregates_pending;},{id:fixture.need_id,h:hours,pct},{timeout:15000}),
     cap.waitForFunction(h=>{const number=text=>Number(String(text).replace(/\s/g,'').replace(',','.'));return number(document.querySelector('#matrix tbody tr')?.children[4]?.textContent)===h&&[...document.querySelectorAll('#panel-body tbody tr')].some(r=>number(r.children[6]?.textContent)===h);},hours,{timeout:15000})
    ]);
    step.aggregatesResponseToVisibleMs=Date.now()-returned;
    step.actual=await raw.evaluate(id=>Raw.state.data.rows.find(r=>r.need_id===id),fixture.need_id);
    for(const r of simulated.results){
     if(typeof r.value==='number')close(step.actual.values[r.field],r.value);
     else assert.deepEqual(step.actual.values[r.field],r.value,r.field);
    }
    const columns=['quantity_required','remaining','theoretical_hours','hours_pct'];
    const params={area:fixture.area,selected:[fixture.need_id],columns};
    const csv=await form.request.post(base+'/planeamento/api/raw/exportar/csv',{data:params});assert.equal(csv.status(),200);
    const csvText=await csv.text(),line=csvText.trim().split(/\r?\n/)[1].split(';').map(v=>Number(v.replace(',','.')));
    line.forEach((value,i)=>close(value,step.actual.values[columns[i]]));step.csv={columns,values:line};
    const xlsx=await form.request.post(base+'/planeamento/api/raw/exportar/xlsx',{data:params});assert.equal(xlsx.status(),200);
    step.xlsx=folder+'/c05-f12-'+fixture.area+'-q'+q+'-r'+saved.revision+'.xlsx';fs.writeFileSync(step.xlsx,await xlsx.body());
    assert(step.rawResponseToVisibleMs<=2000,'RAW response to visible: '+step.rawResponseToVisibleMs);
    assert(step.aggregatesResponseToVisibleMs<=10000,'Capacity response to visible: '+step.aggregatesResponseToVisibleMs);
    await form.waitForFunction(()=>document.querySelector('#status').textContent.includes('Linha atualizada na RAW'));
   }
   await cap.screenshot({path:folder+'/c05-f12-'+fixture.area+'-saved-capacity.png',fullPage:true});
   await Promise.all(pages.map(p=>p.close()));
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
  console.log('Both areas Q40→60→40: preview equals saved RAW, capacity and CSV; XLSX artifacts ready for independent reading.');
 }catch(e){report.failure={message:e.message,stack:e.stack};throw e;}
 finally{fs.writeFileSync(folder+'/c05-f12-save-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
