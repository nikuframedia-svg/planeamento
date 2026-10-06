const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.PLANNING_CHECK_BASE;
if(!base||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated server required');
const folder='docs/validacao-planeamento-integral/20260923-execucao';
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),report=[];
  const proof=JSON.parse(fs.readFileSync(folder+'/c09-volume.json','utf8'));
  for(const item of proof.areas){
   await page.goto(base+'/planeamento/disponibilidade?area='+item.area);
   await page.waitForFunction(()=>document.querySelector('#count').textContent.length>0);
   await page.locator('#search').fill(item.values.machine);
   await page.locator('#year').fill(String(item.values.year));
   await page.locator('#week').fill(String(item.values.week));
   const response=page.waitForResponse(r=>r.url().endsWith('/raw/capacidades/consulta')&&r.request().method()==='POST',{timeout:1000}).catch(()=>null);
   await page.getByRole('button',{name:'Consultar',exact:true}).click();
   await page.waitForFunction(name=>document.querySelector('#matrix tbody tr')?.textContent.includes(name)&&document.querySelectorAll('#matrix tbody tr').length===1,item.values.machine);
   const cells=await page.locator('#matrix tbody tr').first().locator('td').allTextContents();
   assert.equal(cells[7],'6');
   await page.screenshot({path:folder+'/c09-'+item.area+'-resultado-6h.png',fullPage:true});
   report.push({area:item.area,year:item.values.year,week:item.values.week,cells});
   await response;
  }
  fs.writeFileSync(folder+'/c09-results-browser.json',JSON.stringify(report,null,2));
  console.log('Both weekly capacity tables display the audited 6-hour corrections.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
