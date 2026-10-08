// Edição manual do Gantt (Etapa 4, 08/10/2026): arrastar uma caixa na vista Semana (encaixe ao dia e à linha de outra
// máquina candidata), o diálogo «Mudar dia/máquina» (também por teclado), a faixa «Edição manual ativa», o Desfazer,
// a lista com «Retirar», a etiqueta «Fixada», a resposta antiga (Python anterior = só leitura) e 390 px.
// Respostas da API sintéticas e POST intercetado: nada vai à base. Com PLANO_REAL=1 abre também a página com os dados
// do servidor (só leituras, gravações abortadas) e confirma que desenha sem erros.
// Uso: SETOR_BASE=http://127.0.0.1:<porta> [PLANO_REAL=1] node tests/plano_ajustes_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.SETOR_BASE || 'http://127.0.0.1:8113';

const json = (route, body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
const RULE = 'Uma alteração feita no Gantt fica até a retirares ou até a OF deixar de ter trabalho planeado nessa máquina; o cálculo automático nunca a apaga.';
const iso = (d) => d.toISOString().slice(0, 10);
const monday = (() => {const d = new Date(); d.setUTCHours(12, 0, 0, 0); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d})();
const dayN = (n) => {const d = new Date(monday); d.setUTCDate(d.getUTCDate() + n); return iso(d)};
const TODAY = dayN(0);  // segunda desta semana: todos os dias da semana são «hoje ou depois»

function box(of, start, end, extra = {}) {
  return {of, start, end, pieces: 10, pieces_unknown: 0, lines: 1, hours: 6, hours_unknown: 0, hours_estimated: 0, customer: 'PAINHAS, SA',
    designation: 'Postes', due: dayN(20), late: false, approximate: false, days: [{date: start, hours: 6}], shifts: [],
    keys: [`${of}:k`], start_at: `${start}T05:00:00+00:00`, end_at: `${start}T11:00:00+00:00`, conclusion: `${start}T11:00:00+00:00`,
    margin_days: 5, risk: 'ok', already_late: false, conflicts: [], candidates: [{id: 'm2', name: 'Peddi 8', in_spec: true}],
    anchor: null, ...extra};
}

function quadro({anchored = false, capabilities = true} = {}) {
  const fixed = anchored ? {id: 'aj-1', dia: dayN(2), hora: null, estado: 'ativa', autor: 'luis', ja_passou: false} : null;
  const items = anchored ? [{id: 'aj-1', of: 'OF264095', resource_id: 'm1', machine: 'Ficep XP T4', day: dayN(2), hour: null, author: 'luis',
    created_at: `${TODAY}T09:00:00+00:00`, avisos: []}] : [];
  const body = {sector: 'cantoneiras', sector_label: 'MTG3 Cantoneiras', today: TODAY, imported_at: `${TODAY}T07:00:00+00:00`, day_view: true,
    stale: false, template: [['06:00', '14:00'], ['14:00', '22:00'], ['22:00', '06:00']],
    source: {kind: 'plano_em_uso', origin: `${TODAY}T05:00:00+00:00`, placed: 2, operations: 2, missing: [], second_operation: 0},
    unplanned: {orders: []}, not_in_plans: [], elsewhere: {operations: 0, machines: []},
    manual: {count: items.length, last: items[0] || null, items},
    machines: [
      {id: 'm1', name: 'Ficep XP T4', days: {}, boxes: [box('OF264095', anchored ? dayN(2) : dayN(0), anchored ? dayN(3) : dayN(1), {anchor: fixed})]},
      {id: 'm2', name: 'Peddi 8', days: {}, boxes: [box('OF1', dayN(1), dayN(2), {candidates: []})]},
      {id: 'm3', name: 'Thomas', days: {}, boxes: [box('OF2', dayN(0), dayN(1), {candidates: []})]}]};
  if (capabilities) body.capabilities = {ajustes: true, ajustes_motivo: null, regra_ajustes: RULE};
  return body;
}

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const errors = [];
  const newPage = async (width = 1440) => {
    const page = await browser.newPage({viewport: {width, height: 1000}});
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
    return page;
  };
  const posts = [];
  const mock = async (page, body, reply) => {
    await page.route('**/planeamento/api/setor/quadro?*', (route) => json(route, body));
    await page.route('**/planeamento/api/setor/quadro/ajustes', (route) => {
      const sent = JSON.parse(route.request().postData());
      posts.push(sent);
      return reply ? reply(route, sent) : json(route, {acao: sent.acao, ajuste: {id: 'aj-1'}, avisos: ['Máquina fora da ficha técnica'],
        impacto: {later: [{of: 'OF1', days: 2}], later_count: 1, new_late: [], new_late_count: 0, complete: [{machine: 'Peddi 8', date: dayN(2), shift: 1}], complete_count: 1},
        quadro: quadro({anchored: sent.acao === 'mover'})});
    });
    await page.route('**/planeamento/api/carteira/selecao', (route) => route.abort());
  };
  const open = async (page) => {
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras`);
    await page.waitForFunction(() => document.querySelector('#source')?.textContent.includes('Plano em uso'));
  };

  // --- Arrastar: encaixe ao dia e à linha de outra máquina candidata; as outras esbatidas; grava logo
  {
    const page = await newPage();
    await mock(page, quadro());
    await open(page);
    assert.equal(await page.isVisible('#manual'), false, 'sem alterações: sem faixa');
    assert.match(await page.textContent('#edit-rule'), /o cálculo automático nunca a apaga/);
    const source = await page.locator('.pq-row[data-id="m1"] .pq-box').boundingBox();
    const cells = await page.locator('.pq-row[data-id="m2"] .pq-cell').all();
    const target = await cells[2].boundingBox();                          // 3.º dia da semana, linha da Peddi 8
    await page.mouse.move(source.x + 20, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(source.x + 40, source.y + 30, {steps: 3});
    await page.mouse.move(target.x + 20, target.y + target.height / 2, {steps: 8});
    assert.equal(await page.locator('#gantt.pq-dragging').count(), 1);
    assert.equal(await page.locator('.pq-row[data-id="m3"].drop-no').count(), 1, 'máquina não candidata esbatida');
    assert.equal(await page.locator('.pq-row[data-id="m2"].drop-ok .pq-cell.drop-target').count(), 1);
    await page.mouse.up();
    await page.waitForFunction(() => /fixada/.test(document.querySelector('#notice')?.textContent || ''));
    assert.deepEqual({...posts.at(-1), request_id: undefined},
      {setor: 'cantoneiras', acao: 'mover', of: 'OF264095', de: 'm1', maquina: 'm2', dia: dayN(2), request_id: undefined});
    assert.match(posts.at(-1).request_id, /^[0-9a-f-]{36}$/);
    const note = await page.textContent('#notice');
    assert.equal(note, `OF264095 → ${dayN(2).slice(8, 10)}/${dayN(2).slice(5, 7)} (Peddi 8) fixada. Máquina fora da ficha técnica. 1 OF acaba mais tarde: OF1 +2 dias úteis. 1 turno fica completo: Peddi 8 ${dayN(2).slice(8, 10)}/${dayN(2).slice(5, 7)} 1.º.`);
    assert.equal(await page.locator('#dialog[open]').count(), 0, 'largar não abre o diálogo');
    // A resposta traz o quadro novo: faixa, etiqueta «Fixada» e lista com «Retirar».
    assert.match(await page.textContent('#manual-text'), /^Edição manual ativa · OF264095 → \d\d\/\d\d \(Ficep XP T4\)$/);
    assert.equal(await page.textContent('#manual-toggle'), '1 alteração ▸');
    assert.match(await page.textContent('.pq-box.fixed'), /Fixada \d\d\/\d\d/);
    await page.click('#manual-toggle');
    assert.match(await page.textContent('#manual-list'), /OF264095 → \d\d\/\d\d \(Ficep XP T4\) · luis/);
    await page.click('#manual-list button:text("Retirar")');
    await page.waitForFunction(() => /Retirada/.test(document.querySelector('#notice')?.textContent || ''));
    assert.deepEqual([posts.at(-1).acao, posts.at(-1).ajuste_id], ['retirar', 'aj-1']);
    await page.close();
  }

  // --- Diálogo «Mudar dia/máquina» só com o teclado; Desfazer da faixa
  {
    const page = await newPage();
    await mock(page, quadro({anchored: true}));
    await open(page);
    await page.focus('.pq-row[data-id="m1"] .pq-box');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#dialog[open] .pq-move');
    assert.match(await page.textContent('#dialog-body'), /AlteraçãoFixada \d\d\/\d\d · luis/);
    await page.fill('#move-day', dayN(4));
    await page.focus('#move-shift');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.focus('#move-machine');
    await page.keyboard.press('ArrowDown');
    await page.focus('#dialog-actions button:text("Fixar aqui")');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => /fixada/.test(document.querySelector('#notice')?.textContent || ''));
    assert.deepEqual({...posts.at(-1), request_id: undefined},
      {setor: 'cantoneiras', acao: 'mover', of: 'OF264095', de: 'm1', maquina: 'm2', dia: dayN(4), turno: 2, request_id: undefined});
    await page.click('#manual-undo');
    await page.waitForFunction(() => /Desfeita/.test(document.querySelector('#notice')?.textContent || ''));
    assert.deepEqual([posts.at(-1).acao, posts.at(-1).ajuste_id], ['desfazer', 'aj-1']);
    await page.close();
  }

  // --- Erro do servidor (ex.: sem horas nessa máquina) e Python antigo no POST (404): mensagens claras, nada muda
  {
    const page = await newPage();
    let status = 409;
    await mock(page, quadro({anchored: true}), (route) => status === 404 ? route.fulfill({status: 404, body: ''})
      : json(route, {error: 'A Peddi 8 não tem horas para esta operação: escolhe outra máquina.'}, 409));
    await open(page);
    await page.click('#manual-undo');
    await page.waitForFunction(() => document.querySelector('#notice')?.classList.contains('error'));
    assert.match(await page.textContent('#notice'), /Não foi possível gravar: A Peddi 8 não tem horas/);
    status = 404;
    await page.click('#manual-undo');
    await page.waitForFunction(() => /reiniciado/.test(document.querySelector('#notice')?.textContent || ''));
    await page.close();
  }

  // --- Python antigo (sem capabilities): só leitura — sem arrastar, sem secção no diálogo, sem faixa
  {
    const page = await newPage();
    await mock(page, quadro({capabilities: false}));
    await open(page);
    assert.equal(await page.locator('.pq-box.draggable').count(), 0);
    assert.equal(await page.isVisible('#edit-rule'), false);
    await page.click('.pq-row[data-id="m1"] .pq-box');
    assert.equal(await page.locator('#dialog .pq-move').count(), 0);
    await page.close();
  }

  // --- 390 px: faixa e diálogo sem deslocamento horizontal da página
  {
    const page = await newPage(390);
    await mock(page, quadro({anchored: true}));
    await open(page);
    await page.click('#manual-toggle');
    let width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 391, `faixa a 390 px sem deslocamento horizontal (${width})`);
    await page.click('.pq-row[data-id="m1"] .pq-box');
    await page.waitForSelector('#dialog[open] .pq-move');
    const dialog = await page.locator('#dialog').boundingBox();
    assert.ok(dialog.x >= 0 && dialog.x + dialog.width <= 390, 'diálogo dentro do ecrã');
    width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 391, `diálogo a 390 px sem deslocamento horizontal (${width})`);
    await page.close();
  }

  // --- Dados reais (opcional, só leituras; gravações abortadas)
  if (process.env.PLANO_REAL === '1') {
    const page = await newPage();
    await page.route('**/planeamento/api/setor/quadro/ajustes', (route) => route.abort());
    await page.route('**/planeamento/api/carteira/selecao', (route) => route.abort());
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras`);
    await page.waitForFunction(() => /Plano em uso/.test(document.querySelector('#source')?.textContent || ''), null, {timeout: 600000});
    const info = await page.evaluate(async () => {
      const r = await fetch('/planeamento/api/setor/quadro?setor=cantoneiras').then((x) => x.json());
      const boxes = r.machines.flatMap((m) => m.boxes);
      return {capabilities: r.capabilities, manual: r.manual, boxes: boxes.length,
              withCandidates: boxes.filter((b) => b.candidates?.length).length, anchors: boxes.filter((b) => b.anchor).length};
    });
    console.log('real:', JSON.stringify(info));
    assert.equal(info.capabilities?.ajustes, false, 'sem a 053 na base: só leitura');
    assert.match(info.capabilities?.ajustes_motivo || '', /migração 053/);
    assert.equal(await page.locator('.pq-box.draggable').count(), 0);
    await page.close();
  }

  await browser.close();
  assert.deepEqual(errors, []);
  console.log('plano_ajustes_browser: OK');
})().catch((e) => { console.error(e); process.exit(1); });
