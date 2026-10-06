// Página Máquinas de ponta a ponta contra um servidor com dados (PLANNING_CHECK_BASE).
// Leituras reais; toda a gravação (aplicar/desfazer) é intercetada no browser e nunca chega ao servidor:
// o teste verifica o pedido que seria enviado. Qualquer outro POST é bloqueado e faz o teste falhar.
const {chromium}=require('./playwright_core.cjs');
const assert=require('node:assert/strict');
const root=process.env.PLANNING_CHECK_BASE;
if(!root)throw Error('PLANNING_CHECK_BASE em falta');
const READ_ONLY_POST=['/planeamento/api/setor/maquinas/previsao'];

(async()=>{
  const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1366,height:900}}),errors=[],writes=[],blocked=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/planeamento/api/**',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(req.method()==='GET'||READ_ONLY_POST.includes(url.pathname))return route.continue();
    const body=req.postDataJSON();
    if(url.pathname.endsWith('/maquinas/aplicar')){writes.push({path:'aplicar',body});
      return route.fulfill({json:{changed:0,kept:{iniciada:1},action_id:'acao-de-ensaio',repeated:false}})}
    if(url.pathname.endsWith('/maquinas/desfazer')){writes.push({path:'desfazer',body});
      return route.fulfill({json:{restored:0,skipped_changed_later:0}})}
    blocked.push(req.method()+' '+url.pathname);return route.fulfill({status:599,json:{error:'bloqueado no ensaio'}});
  });
  const panel=page.waitForResponse(r=>r.url().includes('/maquinas/painel'),{timeout:300000});
  await page.goto(root+'/planeamento/maquinas');
  const data=await (await panel).json();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Atualizado'),null,{timeout:300000});

  // Menu comum: a página atual marcada, uma só barra de navegação.
  assert.equal(await page.locator('header').count(),1);
  assert.equal(await page.locator('.pl-nav [aria-current=page]').innerText(),'Máquinas');

  // Carga: uma linha por máquina do painel, com as semanas que o servidor calculou.
  assert.equal(await page.locator('#machines .machine').count(),data.machines.length);
  const first=data.machines[0];
  assert.match(await page.locator('#machines .machine').first().innerText(),new RegExp(first.name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
  await page.locator('#machines .machine').first().click();
  await page.waitForSelector('#machines .machine .detail:not([hidden])');

  // Sugestões: contagem no separador = lotes do painel; aceitar 2 lotes envia exatamente as chaves deles.
  await page.locator('#tab-suggest').click();
  assert.equal((await page.locator('#count-suggest').innerText()).replace(/\D/g,''),String(data.suggestions.length));
  const cards=page.locator('#suggestions .card');
  assert.ok(await cards.count()>=2,'precisa de pelo menos 2 sugestões');
  const shown=data.suggestions.slice(0,2);
  await cards.nth(0).locator('input[type=checkbox]').check();await cards.nth(1).locator('input[type=checkbox]').check();
  assert.equal(await page.locator('#suggest-accept-selected').innerText(),'Aceitar 2 selecionadas');
  await page.locator('#suggest-accept-selected').click();
  await page.waitForFunction(()=>!document.querySelector('#toast').hidden);
  const accepted=writes.filter(w=>w.path==='aplicar');
  const byArea=a=>shown.filter(g=>g.area===a).flatMap(g=>g.keys).sort();
  for(const w of accepted){
    assert.equal(w.body.mode,'accept_suggestions');
    assert.equal(w.body.stamp,data.stamps[w.body.setor],'carimbo da versão vista');
    assert.deepEqual([...w.body.scope.keys].sort(),byArea(w.body.setor));
    assert.ok(w.body.request_id);
  }
  assert.equal(accepted.length,new Set(shown.map(g=>g.area)).size);
  assert.match(await page.locator('#toast').innerText(),/0 operações gravadas \(1 mantidas/);
  // Desfazer a partir do aviso usa a ação devolvida.
  await page.locator('#toast button',{hasText:'Desfazer'}).click();
  await page.waitForFunction(()=>document.querySelector('#toast').innerText.includes('Desfeito'));
  assert.deepEqual(writes.at(-1),{path:'desfazer',body:{setor:accepted.at(-1).body.setor,request_id:writes.at(-1).body.request_id,action_id:'acao-de-ensaio'}});

  // Outra máquina: o diálogo só lista alternativas técnicas (pré-visualização real, sem gravar).
  const g=data.suggestions[0];
  await page.locator('#suggestions .card').first().getByRole('button',{name:'Outra máquina…'}).click();
  await page.waitForSelector('#choose[open]',{timeout:120000});
  const options=await page.locator('#choose-options input[type=radio]').count();
  assert.ok(options>=1,'pelo menos uma máquina possível');
  await page.locator('#choose-options input[type=radio]').last().check();
  const picked=await page.locator('#choose-options input:checked').getAttribute('value');
  await page.locator('#choose-reason').fill('Ensaio automático');
  await page.locator('#choose-ok').click();
  await page.waitForFunction(n=>document.querySelector('#toast').innerText.includes('Gravado para'),null);
  const assign=writes.at(-1).body;
  assert.equal(assign.mode,'assign');assert.equal(assign.resource_id,picked);assert.equal(assign.include,'eligible');
  assert.deepEqual(assign.scope.keys,g.keys);assert.equal(assign.reason,'Ensaio automático');

  // Equilibrar: cada chave vai para a máquina de destino da proposta.
  await page.locator('#tab-balance').click();
  if(data.rebalance.length){
    const p=data.rebalance[0];
    await page.locator('#balance .card').first().getByRole('button',{name:`Mudar para ${p.to}`}).click();
    await page.waitForFunction(()=>document.querySelector('#toast').innerText.includes('mudado para'));
    const move=writes.at(-1).body;
    assert.equal(move.mode,'assign_each');
    assert.deepEqual(move.targets,Object.fromEntries(p.keys.map(k=>[k,p.to_id])));
    for(const q of data.rebalance)assert.notEqual(q.from_id,q.to_id);
  }

  // Histórico: leitura real.
  await page.locator('#tab-history').click();
  await page.waitForFunction(()=>document.querySelector('#history').children.length>0);

  // Filtro de setor recarrega só esse setor.
  const mtg2=page.waitForResponse(r=>r.url().includes('/maquinas/painel')&&r.url().includes('areas=perfis')&&!r.url().includes('areas=cantoneiras'),{timeout:300000});
  await page.locator('.seg button[data-area=perfis]').click();
  const perfis=await (await mtg2).json();
  assert.ok(perfis.machines.every(m=>m.area==='perfis'));

  // Telemóvel: nada sai da largura do ecrã.
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'sem deslocamento horizontal');

  assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);
  await browser.close();
  console.log(`Máquinas: ${data.machines.length} máquinas, ${data.suggestions.length} lotes sugeridos, ${data.rebalance.length} propostas; aceitar/escolher/equilibrar/desfazer enviam o pedido certo: OK`);
})().catch(error=>{console.error(error);process.exit(1)});
