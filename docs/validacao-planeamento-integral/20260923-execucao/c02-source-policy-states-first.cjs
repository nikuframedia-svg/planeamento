const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated planning server required');
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
(async()=>{
 const bytes=fs.readFileSync(folder+'/c02-source-policy-population.json'),fixture=JSON.parse(bytes);
 assert.equal(fixture.result,'passed');
 const report={at:new Date().toISOString(),base,script_sha256:sha(fs.readFileSync(__filename)),fixture_sha256:sha(bytes),cases:[],errors:[]};
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  for(const [area,info] of Object.entries(fixture.areas))for(const [origin,sample] of Object.entries(info.examples)){
   const response=await page.request.post(base+'/planeamento/api/raw/consultas',{data:{area,population:'all',selected:[sample.key]}});
   assert.equal(response.status(),200);const data=await response.json(),row=data.rows.find(r=>r.key===sample.key);
   assert(row);assert.equal(Number(data.version),info.generation);
   const selected=row.calculation.production_sources.find(s=>s.operation===sample.operation);
   for(const field of ['value','origin','ocr','excel','difference','remaining','excess','percent'])assert.equal(selected[field],sample.expected[field],area+' '+origin+' '+field);
   const primary=area==='perfis'?'corte':String(row.values.operation);
   const field=area==='perfis'?(sample.operation==='corte'?'cut':'boc'):(sample.operation===primary?'made':'secondary_remaining');
   await page.goto(base+'/planeamento/raw?area='+area+'&need='+encodeURIComponent(sample.key));
   await page.locator('#drawer').getByRole('button',{name:'Cálculos',exact:true}).click();
   const fields=await page.evaluate(()=>Raw.state.fields),label=fields.find(f=>f.id===field)?.label;
   assert(label);const tr=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:label,exact:true})});
   await tr.scrollIntoViewIfNeeded();const cells=await tr.locator('td').allTextContents();
   assert(cells[4].includes(origin),JSON.stringify({field,cells,origin}));
   assert(!cells[3].includes('[object Object]'));
   if(sample.expected.value===null){assert.notEqual(cells[5],'—');assert(!/^0(?:[.,]0+)?(?:\s|$)/.test(cells[1]));}
   else{assert(cells[1].includes(String(field==='secondary_remaining'?sample.expected.remaining:sample.expected.value)));}
   const screenshot=`c02-source-policy-states-${area}-${report.cases.length}.png`;
   await page.screenshot({path:folder+'/'+screenshot,fullPage:true});
   report.cases.push({area,key:sample.key,version:data.version,operation:sample.operation,origin,expected:sample.expected,selected,field,cells,screenshot});
  }
  assert.equal(report.cases.length,8);assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/c02-source-policy-states-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
