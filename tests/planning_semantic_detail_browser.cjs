const {chromium}=require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const base=process.env.PLANNING_CHECK_BASE,folder='docs/validacao-planeamento-integral/20260923-execucao';
const prefix=process.env.PLANNING_PROOF||'c04-semantic-detail-browser';
if(base!=='http://127.0.0.1:18113'||process.env.PLANNING_TEST_ISOLATED!=='1'||!/^c04-[a-z-]+$/.test(prefix))throw Error('Isolated planning proof required');
(async()=>{
 const browser=await chromium.launch({executablePath:'/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
 const report={at:new Date().toISOString(),base,script_sha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),cases:[],errors:[]};
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  for(const [area,q,key] of [['perfis','CI5421A3004','macro:mtg2_bf1cd6a25986791e:plan:5589'],['cantoneiras','C03-cantoneiras-2','5881f704-89c8-4e16-81e9-6d7797a0a436']]){
   await page.goto(base+'/planeamento/raw?area='+area+'&q='+encodeURIComponent(q));
   await page.waitForFunction(()=>Raw.state.data);
   await page.locator('#population').selectOption('all');await page.locator('#page-size').selectOption('500');
   await page.waitForFunction(key=>Raw.state.data?.population==='all'&&Raw.state.data.rows.some(r=>r.key===key)&&document.querySelector('#notice').textContent==='',key);
   const data=await page.evaluate(key=>({index:Raw.state.data.rows.findIndex(r=>r.key===key),ofColumn:Raw.state.columns.indexOf('of'),row:Raw.state.data.rows.find(r=>r.key===key),fields:Raw.state.fields,version:Raw.state.data.version}),key);
   assert.equal(data.row.calculation.contract,'planning-integral-20260923-v5');
   await page.locator('#sheet tbody tr').nth(data.index).locator('td').nth(data.ofColumn).dblclick();
   await page.locator('#drawer').getByRole('button',{name:'Cálculos',exact:true}).click();
   const details={};
   for(const field of ['description','deadline_status','overdue',...(area==='cantoneiras'?['material_description']:[])]){
    const label=data.fields.find(f=>f.id===field).label;
    const tr=page.locator('#drawer tbody tr').filter({has:page.getByRole('cell',{name:label,exact:true})});
    await tr.scrollIntoViewIfNeeded();const cells=await tr.locator('td').allTextContents();
    assert.ok(cells[3].length>1);assert.ok(!cells[3].includes('[object Object]'),'Nested inputs must be readable: '+cells[3]);
    assert.notEqual(cells[4],'—');details[field]={inputs:cells[3],source:cells[4],value:cells[1]};
   }
   if(area==='perfis'){
    assert.ok(details.overdue.inputs.includes('corte=0'));assert.ok(details.overdue.inputs.includes('abocardar=75'));
    assert.equal(data.fields.find(f=>f.id==='bars').unit,'un.');
   }
   assert.ok(details.overdue.inputs.includes('Data local='));
   assert.ok(details.overdue.inputs.includes('Origem da data='));
   report.cases.push({area,key,version:data.version,details});
   await page.screenshot({path:folder+'/'+prefix+'-'+area+'.png',fullPage:true});
  }
  assert.deepEqual(report.errors,[]);report.result='passed';
 }catch(e){report.result='failed';report.failure=e.stack;throw e;}
 finally{fs.writeFileSync(folder+'/'+prefix+'.json',JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
