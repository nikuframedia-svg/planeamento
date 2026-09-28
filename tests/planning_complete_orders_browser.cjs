const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1')throw Error('Isolated planning server required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),cases:[],errors:[],requests:[]};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))report.requests.push({method:r.method(),url:r.url()});});
  async function search(q,scope='active'){
   await page.goto(base+'/planeamento');
   await page.waitForFunction(()=>document.querySelector('#count').textContent.includes('Ativos'));
   await page.locator('#query').fill(q);await page.locator('#population').selectOption(scope);
   const response=page.waitForResponse(r=>r.url().includes('/api/ordens?')&&new URL(r.url()).searchParams.get('q')===q);
   await page.locator('#filters button[type=submit]').click();
   const data=await(await response).json();
   await page.waitForFunction(total=>document.querySelector('#count').textContent.startsWith(total+' ordens'),data.total);
   return data;
  }
  for(const [of,reference,area] of [['OF987080380','C03-perfis-1','perfis'],['OF987080381','C03-cantoneiras-1','cantoneiras']]){
   const data=await search(reference);assert.equal(data.total,1);assert.equal(data.orders[0].of,of);
   assert.deepEqual(data.orders[0].plan,{[area]:2});
   assert.ok((await page.locator('#orders').innerText()).includes('Manual local'));
   await page.locator('#orders button.open-order').click();
   await page.locator('#detail h2').filter({hasText:of}).waitFor();
   assert.ok((await page.locator('#detail').innerText()).includes('sem estado CPIS confirmado'));
   const links=page.locator('#detail a').filter({hasText:'Abrir registo'});assert.equal(await links.count(),2);
   await links.first().click();
   await page.locator('#field-component_ref').waitFor({state:'visible'});
   await page.waitForFunction(prefix=>document.querySelector('#field-component_ref').value.startsWith(prefix),'C03-'+area+'-');
   await page.locator('#references-open').click();await page.locator('#references-dialog').waitFor({state:'visible'});
   const labels=await page.locator('#references button').allTextContents();assert.equal(labels.length,2);
   assert.ok(labels.every(label=>label.includes('C03-'+area+'-')));
   report.cases.push({of,area,pieces:2,references:labels});
   await page.screenshot({path:folder+'/c06-complete-orders-'+area+'.png',fullPage:true});
  }
  const imported=await search('OF26499','all'),macro=imported.orders.find(r=>r.of==='OF26499');assert.ok(macro);
  assert.equal(macro.cpis_status,null);
  await page.locator('#orders tr').filter({has:page.getByText('OF26499',{exact:true})}).locator('button.open-order').click();
  await page.locator('#detail h2').filter({hasText:'OF26499'}).waitFor();
  assert.ok((await page.locator('#detail').innerText()).includes('Macro — sem contexto CPIS'));
  report.cases.push({of:'OF26499',plan:macro.plan,origin:macro.administrative_origin});
  const unknown=await search('CWA223E');
  const row=unknown.orders.find(r=>r.unidentified);assert.ok(row);assert.equal(row.of,null);
  const link=page.locator('#orders a').filter({hasText:'Ver CWA223E na RAW'});await link.waitFor();
  await link.click();await page.waitForFunction(()=>window.Raw?.state.data?.rows.some(r=>r.key==='macro:mtg_397c8ea5e42480c1:plan:51449'));
  report.cases.push({unidentified_key:row.raw_links[0].key,visible_in_raw:true});
  await page.screenshot({path:folder+'/c06-complete-orders-unidentified.png',fullPage:true});
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(error){report.result='failed';report.failure=error.stack;throw error;}
 finally{fs.writeFileSync(folder+'/c06-complete-orders-browser.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
