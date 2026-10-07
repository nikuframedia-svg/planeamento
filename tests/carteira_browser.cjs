// Aceitação da Carteira simples (esboço do Luís, 02/10/2026). Nada é gravado:
// o pedido de gravação (/selecao) é intercetado no browser e respondido com uma confirmação simulada.
// Uso: CARTEIRA_BASE=http://127.0.0.1:8113 CARTEIRA_SHOT=/tmp/carteira.png node tests/carteira_browser.cjs
// 08/10: cabeçalho fixo (P2) e ordem por data (P6), também com a Python antiga simulada (sem «order»).
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.CARTEIRA_BASE || 'http://127.0.0.1:8113';
const shot = process.env.CARTEIRA_SHOT;

// Carga base dos painéis (sem o acréscimo entre parênteses nem a coluna Marcados).
const baseLoad = () => [
  ...[...document.querySelectorAll('#kpis li')].map((li) => [li.querySelector('.m-name'), li.querySelector('.m-metres').firstChild,
    li.querySelector('.m-hours').firstChild].map((n) => n.textContent).join('|')),
  ...[...document.querySelectorAll('#kpis .resumo tbody tr')].map((tr) => [...tr.children].map((n) => n.textContent).join('|')),
];

// Cabeçalho fixo: cópia por baixo do menu, colunas do original, Subtotal, aria-hidden e inert.
const stickyState = () => {
  const menu = document.querySelector('.pl-header').getBoundingClientRect();
  const wrap = document.querySelector('.sticky-head');
  const inner = wrap.querySelector('.sticky-head-in');
  const real = [...document.querySelectorAll('#tree > thead th')].map((th) => th.getBoundingClientRect());
  const copy = [...wrap.querySelectorAll('table.sticky-copy > thead th')].map((th) => th.getBoundingClientRect());
  return {on: wrap.classList.contains('on'), visible: getComputedStyle(inner).visibility === 'visible',
          gap: inner.getBoundingClientRect().top - menu.bottom, bottom: inner.getBoundingClientRect().bottom,
          columns: [real.length, copy.length], subtotal: wrap.querySelectorAll('tr.subtotal').length,
          left: Math.max(...real.map((r, i) => Math.abs(r.left - copy[i].left))),
          right: Math.max(...real.map((r, i) => Math.abs(r.right - copy[i].right))),
          inert: wrap.hasAttribute('inert'), hidden: wrap.getAttribute('aria-hidden')};
};
const checkSticky = (s, where) => {
  assert.ok(s.on && s.visible, `${where}: a cópia do cabeçalho não aparece`);
  assert.ok(Math.abs(s.gap) <= 1, `${where}: a cópia está a ${s.gap}px do menu`);
  assert.equal(s.columns[0], s.columns[1]);
  assert.ok(s.left <= 1 && s.right <= 1, `${where}: colunas desalinhadas (${s.left}/${s.right}px)`);
  assert.equal(s.subtotal, 1, `${where}: falta o Subtotal na cópia`);
  assert.ok(s.inert && s.hidden === 'true');
};
const scrollPastHead = () => {
  const t = document.getElementById('tree').getBoundingClientRect();
  window.scrollTo(0, window.scrollY + t.top + 400);
};
const frames = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
const DUE = /^(\d\d\/\d\d|S\d\d\??|sem data|estacionada)$/;

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  const writes = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('requestfailed', (r) => { if (r.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`${r.url()} ${r.failure()?.errorText}`); });  // mudar de página cancela pedidos
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  await page.route('**/planeamento/api/carteira/selecao', async (route) => {
    const body = JSON.parse(route.request().postData());
    writes.push(body);
    const n = body.membros ? body.membros.length : 1;
    await route.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify({changed: n, members: n, skipped_no_machine: 0, action: 'selected', metres: 0, repeated: false, keys: []})});
  });
  const machineWrites = [];
  await page.route('**/planeamento/api/carteira/maquina', async (route) => {
    const body = JSON.parse(route.request().postData());
    machineWrites.push(body);
    await route.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify({changed: body.membros.length, members: body.membros.length, machine: 'Máquina de ensaio', repeated: false, keys: []})});
  });
  await page.route('**/planeamento/api/carteira/conjuntos', async (route) => {
    if (route.request().method() === 'POST') { writes.push('conjunto'); await route.fulfill({status: 500, body: '{}'}); }
    else await route.continue();
  });
  try {
    await page.goto(`${base}/planeamento/carteira?setor=cantoneiras`);
    await page.waitForSelector('#rows tr.group', {timeout: 90000});
    assert.equal(await page.inputValue('#vista'), 'perfil', 'Perfil é a vista por defeito');
    assert.equal(await page.textContent('#level-title'), 'Perfil');
    const rows = await page.locator('.cart-row').allTextContents();
    assert.equal(rows.length, 2, 'filtros em duas linhas');
    for (const label of ['Setor', 'Família de Produto', 'Família SKU', 'Ver por']) assert.ok(rows[0].includes(label), `falta ${label}`);
    for (const label of ['Pesquisar', 'Máquina', 'Prazo', 'Ordem', 'Estado', 'Limpar filtros']) assert.ok(rows[1].includes(label), `falta ${label}`);
    assert.deepEqual(await page.locator('#estado option').allTextContents(), ['Todos', 'Planeado', 'Planeado para nesting', 'Sem máquina atribuída']);
    await page.waitForSelector('#kpis .panel h2', {timeout: 120000});
    const text = await page.textContent('main');
    for (const gone of ['Planear para', 'Como ler', 'Excluir', 'Data Corte', 'por planear:']) assert.ok(!text.includes(gone), `ainda aparece «${gone}»`);
    assert.deepEqual(await page.locator('#kpis .panel h2').allTextContents(), ['Punção', 'Broca', 'Resumo']);
    assert.deepEqual(await page.locator('#kpis .resumo tbody th').allTextContents(), ['Planeado', 'Planeado para nesting', 'Sem máquina atribuída']);
    assert.deepEqual(await page.locator('#kpis .resumo thead th').allTextContents(), ['', 'Metros', 'Horas', 'Toneladas']);
    assert.equal(await page.locator('#subtotal tr.subtotal th').textContent(), 'Subtotal');
    // 08/10: avisos numa só linha discreta, só quando há casos (repetidas, produção acima da QTD); Excel por importar.
    const note = page.locator('#subtotal tr.subtotal-note');
    if (await note.count()) {
      const said = await note.textContent();
      assert.match(said, /^(\d[\d\s\u00a0\u202f.]* linhas? (possivelmente repetidas? \(\+[\d\s\u00a0\u202f.,]+ m\)|com produção acima da QTD \(\+[\d\s\u00a0\u202f.]+ peças\))( · )?)+$/);
      console.log('Avisos da lista:', said);
    }
    const sourceNotice = page.locator('#source-notice');
    if (await sourceNotice.isVisible()) assert.match(await sourceNotice.textContent(), /^O Excel de MTG[23] \S+ no Drive é mais recente/);
    assert.deepEqual(await page.locator('#tree > thead th').allTextContents(), ['Perfil', 'Planear', 'Metros', 'Peças', 'OF', 'Sem máquina', 'Em nesting']);
    // Ordem (P6): na MTG3 por defeito pela data de corte; etiqueta curta no nome de cada grupo.
    assert.equal(await page.inputValue('#ordem'), 'corte');
    assert.deepEqual(await page.locator('#ordem option').allTextContents(), ['Data de corte mais próxima', 'Mais urgente primeiro', 'Mais metros primeiro']);
    const dues = await page.locator('#rows tr.group.level-0 .due').allTextContents();
    assert.equal(dues.length, await page.locator('#rows tr.group.level-0').count(), 'cada grupo tem a sua data');
    assert.ok(dues.every((d) => DUE.test(d)), `etiquetas: ${dues.slice(0, 5)}`);
    const firstUndated = dues.findIndex((d) => !/\d/.test(d));
    assert.ok(firstUndated === -1 || dues.slice(firstUndated).every((d) => !/\d/.test(d)), 'as sem data e estacionadas vêm no fim');
    const late = page.locator('#rows tr.group.level-0 .due.late').first();
    if (await late.count()) assert.match(await late.getAttribute('title'), /^Data de corte mais antiga com saldo · \d+ dias? de atraso$/);
    console.log('Ordem por data de corte:', dues.slice(0, 4).join(' '), '…', dues.slice(-2).join(' '));
    const loadBefore = await page.evaluate(baseLoad);

    // Uma linha com trabalho em nesting e mais de um membro: marcar todos menos um na lupa.
    const groups = page.locator('#rows tr.group');
    let index = 0;
    for (; index < await groups.count(); index += 1) {
      const g = groups.nth(index);
      if (Number(await g.getAttribute('data-total')) > 1 && (await g.locator('td').nth(5).textContent()) !== '—') break;
    }
    const first = groups.nth(index);
    const total = Number(await first.getAttribute('data-total'));
    const name = await first.getAttribute('data-name');
    const byName = () => page.locator(`#rows tr.group[data-name="${name}"]`);
    await first.locator('.lupa').click();
    await page.waitForSelector('tr.detail-row tr.member', {timeout: 60000});
    await page.locator('tr.detail-row').getByRole('button', {name: 'Marcar todos', exact: true}).click();
    await page.locator('tr.detail-row input.member-pick').first().uncheck();
    const counter = (n) => document.querySelector(`#rows tr.group[data-name="${n[1]}"] .pick-count`).textContent === `${n[0] - 1}/${n[0]}`;
    await page.waitForFunction(counter, [total, name], {timeout: 30000});
    assert.equal(await byName().locator('.group-pick').evaluate((b) => b.indeterminate), true);
    await page.waitForFunction(() => document.getElementById('marked-text').textContent.includes('acrescenta'), null, {timeout: 60000});
    console.log(`${name}:`, await page.textContent('#marked-text'),
                '| máquinas →', (await page.locator('#kpis .delta').allTextContents()).filter(Boolean).join(' '));
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('tr.detail-row').count(), 0);
    assert.equal(await page.evaluate(() => document.activeElement.className), 'lupa', 'o foco volta à lupa');
    if (shot) await page.screenshot({path: shot, fullPage: false});

    // Cabeçalho fixo (P2): depois de descer, a cópia fica colada ao menu e alinhada; a lupa focada não fica tapada.
    await page.evaluate(scrollPastHead);
    await page.evaluate(frames);
    checkSticky(await page.evaluate(stickyState), '1440 px');
    const under = await page.evaluate((bottom) => [...document.querySelectorAll('#rows tr.group')].findIndex((tr) => tr.getBoundingClientRect().top > bottom + 4),
                                      (await page.evaluate(stickyState)).bottom);
    const lupaRow = page.locator('#rows tr.group').nth(under);
    await lupaRow.locator('.lupa').click();
    await page.waitForSelector('tr.detail-row input[type=search]', {timeout: 60000});
    await page.waitForFunction(() => document.activeElement && document.activeElement.type === 'search', null, {timeout: 60000});
    const focusTop = await page.evaluate(() => document.activeElement.getBoundingClientRect().top);
    assert.ok(focusTop >= (await page.evaluate(stickyState)).bottom - 1, 'a pesquisa da lupa fica por baixo da cópia do cabeçalho');
    await page.keyboard.press('Escape');
    const lupaTop = await page.evaluate(() => document.activeElement.getBoundingClientRect().top);
    assert.ok(lupaTop >= (await page.evaluate(stickyState)).bottom - 1, 'a lupa focada fica por baixo da cópia do cabeçalho');
    if (shot) await page.screenshot({path: shot.replace(/\.png$/, '-fixo.png'), fullPage: false});
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(frames);
    assert.equal(await page.evaluate(() => document.querySelector('.sticky-head').classList.contains('on')), false, 'no topo a cópia não aparece');

    // Filtrar, pesquisar sem resultados, Prazo e Limpar filtros não mexem na marcação nem na carga.
    await page.fill('#q', 'NAO-EXISTE-NADA-ASSIM');
    await page.waitForSelector('#empty:not([hidden])', {timeout: 30000});
    await page.selectOption('#estado', 'nesting');
    await page.click('#semanas summary');
    const weeks = page.locator('#semanas-lista input');
    assert.ok(await weeks.count() > 1, 'faltam semanas no Prazo');
    await weeks.nth(0).check();
    await page.keyboard.press('Escape');
    await page.click('#limpar-filtros');
    await page.waitForSelector('#rows tr.group', {timeout: 30000});
    assert.equal(await page.inputValue('#q'), '');
    assert.equal(await page.inputValue('#estado'), '');
    assert.equal(await page.textContent('#semanas-resumo'), 'Todas');
    await page.waitForFunction(counter, [total, name], {timeout: 30000});
    assert.equal(writes.length, 0, 'filtros não gravam nada');
    assert.deepEqual(await page.evaluate(baseLoad), loadBefore, 'a carga base não muda com os filtros');

    // Atribuir máquina às linhas marcadas: uma lista com a sugestão aprendida já escolhida.
    await page.waitForFunction(() => document.querySelectorAll('#assign-machine option').length > 2, null, {timeout: 60000});
    const options = await page.locator('#assign-machine option').allTextContents();
    console.log('Máquinas para atribuir:', options.length - 2, '| sugerida:', options.find((o) => o.includes('sugerida')) || '(sem sugestão)');
    if (!(await page.inputValue('#assign-machine'))) await page.selectOption('#assign-machine', {index: 1});
    await page.click('#assign');
    await page.waitForFunction(() => /passam para/.test(document.getElementById('notice').textContent), null, {timeout: 30000});
    assert.equal(machineWrites.length, 1);
    assert.equal(machineWrites[0].membros.length, total - 1);
    assert.ok(machineWrites[0].maquina && machineWrites[0].request_id);
    assert.match(await page.textContent('#marked-text'), new RegExp(`^${total - 1} marcada`), 'as linhas continuam marcadas para Planear');

    // Planear envia só os membros marcados dessa linha, sem filtros nem fase.
    await byName().locator('.act-plan').click();
    await page.waitForFunction(() => /planeada/.test(document.getElementById('notice').textContent), null, {timeout: 30000});
    assert.equal(writes.length, 1);
    assert.equal(writes[0].membros.length, total - 1);
    assert.ok(writes[0].membros.every((m) => m.chave && m.token));
    assert.ok(!('filtros' in writes[0]) && !('fase' in writes[0]));

    // Conjuntos de famílias: a página abre, lista famílias e máquinas; nada é gravado.
    await page.click('a.sets-link');
    await page.waitForSelector('#novo:not([disabled])', {timeout: 60000});
    await page.click('#novo');
    await page.waitForSelector('#familias .family', {timeout: 30000});
    assert.ok(await page.locator('#familias .family').count() > 10, 'faltam famílias');
    assert.ok(await page.locator('#maquina option').count() > 3, 'faltam máquinas');
    if (shot) await page.screenshot({path: shot.replace(/\.png$/, '-conjuntos.png'), fullPage: false});
    await page.click('#cancelar');
    await page.goto(`${base}/planeamento/carteira?setor=cantoneiras`);
    await page.waitForSelector('#rows tr.group', {timeout: 90000});

    await page.setViewportSize({width: 390, height: 844});
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `a página tem ${overflow}px de scroll horizontal a 390 px`);
    if (shot) await page.screenshot({path: shot.replace(/\.png$/, '-390.png'), fullPage: false});
    // 390 px: a cópia acompanha o scroll horizontal da caixa e não cria scroll na página.
    await page.evaluate(scrollPastHead);
    await page.evaluate(() => { document.getElementById('cart-table').scrollLeft = 180; });
    await page.evaluate(frames);
    checkSticky(await page.evaluate(stickyState), '390 px com scroll horizontal');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth) <= 1);
    if (shot) await page.screenshot({path: shot.replace(/\.png$/, '-390-fixo.png'), fullPage: false});

    // MTG2: por defeito pelo Picking, com «S42» / «S42?».
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(`${base}/planeamento/carteira?setor=perfis`);
    await page.waitForSelector('#rows tr.group', {timeout: 120000});
    assert.equal(await page.inputValue('#ordem'), 'picking');
    assert.deepEqual(await page.locator('#ordem option').allTextContents(),
      ['Data de picking mais próxima', 'Data de corte mais próxima', 'Mais urgente primeiro', 'Mais metros primeiro']);
    const picks = await page.locator('#rows tr.group.level-0 .due').allTextContents();
    assert.ok(picks.length && picks.every((d) => DUE.test(d)) && /^S\d\d/.test(picks[0]), `etiquetas MTG2: ${picks.slice(0, 5)}`);
    console.log('Ordem por Picking (MTG2):', picks.slice(0, 4).join(' '), '…', picks.slice(-2).join(' '));
    // Mudar de setor volta à ordem por data do outro setor.
    await page.selectOption('#setor', 'cantoneiras');
    await page.waitForFunction(() => document.getElementById('ordem').value === 'corte', null, {timeout: 30000});
    await page.waitForSelector('#rows tr.group .due', {timeout: 120000});

    // Python antiga (resposta sem «order»): fica a ordem de hoje e a nota, sem etiquetas.
    const old = await browser.newPage({viewport: {width: 1440, height: 900}});
    await old.route((url) => url.pathname === '/planeamento/api/carteira', async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      delete body.order; delete body.capabilities;
      for (const g of body.groups || []) delete g.due_tag;
      await route.fulfill({response, json: body});
    });
    await old.goto(`${base}/planeamento/carteira?setor=cantoneiras`);
    await old.waitForSelector('#order-note:not([hidden])', {timeout: 120000});
    await old.waitForSelector('#rows tr.group', {timeout: 120000});
    assert.equal(await old.inputValue('#ordem'), 'urgencia');
    assert.equal(await old.evaluate(() => document.querySelector('#ordem option[value=corte]').disabled), true, 'a ordem por data fica desligada');
    assert.equal(await old.locator('#rows .due').count(), 0);
    assert.equal(await old.textContent('#order-note'), 'A ordem por data precisa que o serviço do planeamento seja reiniciado.');
    await old.close();
    assert.deepEqual(errors, []);
    assert.ok(!writes.includes('conjunto'));
    console.log(`Carteira OK: ${name} ${total - 1}/${total}, Atribuir máquina e Planear exatos (intercetados), Conjuntos, filtros sem efeito na carga, 390 px sem scroll, cabeçalho fixo, ordem por data`);
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
