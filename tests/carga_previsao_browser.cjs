// Vistas da previsão na Carga e turnos (Etapa 3, pontos 11 e 12, 08/10/2026): «Calendário» e «Capacidade e prazos».
// Nada é gravado: qualquer pedido que não seja GET falha o teste.
// Uso: CARGA_BASE=http://127.0.0.1:8181 [CARGA_SHOTS=/tmp/carga] node tests/carga_previsao_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.CARGA_BASE || 'http://127.0.0.1:8113';
const shots = process.env.CARGA_SHOTS;

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [], writes = [];
  page.on('console', (m) => { if (m.type() === 'error' && !/fingido/.test((m.location() || {}).url || '')) errors.push(m.text()); });  // o 404 do cenário inventado é esperado
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('response', (r) => { if (r.status() >= 400 && !/fingido/.test(r.url())) errors.push(`${r.status()} ${r.url()}`); });
  await page.route('**/planeamento/api/**', (route) => {
    if (route.request().method() === 'GET') return route.continue();
    writes.push(route.request().url());
    return route.abort();
  });

  // --- Calendário: 6 semanas × 7 dias, sem texto de explicação (revisão 08/10), a semana passada só com realizado.
  await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras&vista=calendario`);
  await page.waitForSelector('#fc-cal-body td.fc-day', {timeout: 240000});
  assert.equal(await page.locator('#views button[aria-pressed="true"]').innerText(), 'Calendário');
  assert.ok(await page.locator('#fc-text').isHidden(), 'sem a frase de explicação');
  assert.ok(await page.locator('#weeks-view').isHidden() && await page.locator('#group-view').isHidden(), 'só o calendário');
  assert.equal(await page.locator('#fc-cal-body tr').count(), 6, '6 semanas');
  assert.equal(await page.locator('#fc-cal-body td').count(), 42, '7 dias por semana');
  assert.equal(await page.locator('#fc-cal-body tr').first().locator('td.past').count(), 7, 'semana passada: só o realizado');
  for (const t of await page.locator('#fc-cal-body td.past').allInnerTexts()) assert.ok(!/ h · /.test(t), `dia passado sem previsão: ${t}`);
  const today = page.locator('#fc-cal-body td.today');
  assert.equal(await today.count(), 1, 'hoje marcado');
  const todayText = await today.innerText();
  assert.match(todayText, /(\d[\d\s,.]* \/ [\d\s,.]+ h\s+(\d+ %|100 % · completa))|Fechado|Sem carga/, `hoje com a previsão: ${todayText}`);
  // Estados: 100 % é «completa» (laranja claro), nunca erro.
  for (const cls of await page.locator('#fc-cal-body td').evaluateAll((tds) => tds.map((td) => td.className))) {
    assert.ok(!/error|falta/.test(cls), `sem estado de erro: ${cls}`);
  }

  // Clicar no dia (hoje): Previsão e «Realizado neste dia» em secções separadas.
  await today.click();
  await page.waitForSelector('#fc-day .fc-forecast h3', {timeout: 60000});
  assert.equal(await page.locator('#fc-day .fc-forecast h3').first().innerText(), 'Previsão');
  assert.equal(await page.locator('#fc-day .fc-realized h3').innerText(), 'Realizado neste dia');
  assert.equal(await page.locator('#fc-day .fc-forecast .fc-realized, #fc-day .fc-realized .fc-forecast').count(), 0, 'nunca uma dentro da outra');
  assert.match(await page.locator('#fc-day .fc-realized h3').getAttribute('title'), /MES/);
  const gantt = await page.locator('#fc-day a', {hasText: 'Ver no Gantt (dia)'}).getAttribute('href');
  assert.match(gantt, /^\/planeamento\/gantt\?setor=cantoneiras&dia=\d{4}-\d{2}-\d{2}/);
  assert.equal(await page.locator('#fc-day a', {hasText: 'Ver na Carga'}).count(), 1);  // o link não leva a semana
  if (await page.locator('#fc-day details.fc-machine').count()) {
    await page.locator('#fc-day details.fc-machine summary').first().click();
    const head = await page.locator('#fc-day details.fc-machine').first().locator('thead th').allInnerTexts();
    assert.deepEqual(head, ['OF', 'Cliente', 'Horas neste dia', 'Peças', 'Metros', 'Planeado / resto', 'Prazo', 'Acaba']);
  }
  if (shots) await page.screenshot({path: `${shots}/calendario.png`, fullPage: true});
  // Um dia passado: «Dia passado: sem previsão.» e o realizado à parte.
  await page.locator('#fc-cal-body td.past').nth(2).click();
  await page.waitForFunction(() => /Dia passado/.test(document.querySelector('#fc-day .fc-forecast')?.innerText || ''), null, {timeout: 60000});
  assert.equal(await page.locator('#fc-day .fc-realized h3').innerText(), 'Realizado neste dia');
  // ◀ ▶
  const range = await page.locator('#fc-range').innerText();
  await page.click('#fc-next');
  await page.waitForFunction((r) => { const t = document.querySelector('#fc-range').textContent; return t !== r && !/A carregar/.test(t); }, range, {timeout: 60000});
  assert.equal(await page.locator('#fc-cal-body td.past').count(), 0, 'semanas seguintes: só previsão');
  await page.click('#fc-prev');
  await page.waitForFunction((r) => document.querySelector('#fc-range').textContent === r, range, {timeout: 60000});

  // --- Capacidade e prazos: 3 contadores, mapa 15 dias úteis | 13 semanas, riscos e dados em falta.
  await page.locator('#views button', {hasText: /^Capacidade e prazos$/}).click();
  assert.match(page.url(), /vista=capacidade/);
  await page.waitForSelector('#fc-map-body tr', {timeout: 120000});
  assert.ok(await page.locator('#fc-cal').isHidden(), 'calendário escondido');
  assert.equal(await page.locator('#fc-counters .counter').count(), 3, '3 contadores (sem «saúde»)');
  const counters = await page.locator('#fc-counters').innerText();
  assert.match(counters, /OF que atrasam/); assert.match(counters, /OF em risco/); assert.match(counters, /Máquinas que limitam/);
  assert.ok(!/saúde/i.test(counters));
  const api = await page.evaluate(async () => (await fetch('/planeamento/api/setor/capacidade-prazos?setor=cantoneiras')).json());
  assert.match(counters, new RegExp(`^${api.counters.atrasam}\\s`), 'contador = previsão');
  assert.equal(await page.locator('#fc-map-head th').count(), 16, 'Máquina + 15 dias úteis');
  for (const t of await page.locator('#fc-map-body td.m').allInnerTexts()) {
    assert.match(t, /^(\d+ %|100 % · completa|Fechado|Sem carga|Sem calendário)( ●\d*)*$/, `célula: ${t}`);
  }
  assert.match(await page.locator('#fc-risks-title').innerText(), /^Riscos principais \(\d+\)$/);
  if (api.risks.length) {
    assert.deepEqual(await page.locator('#fc-risks-table thead th').allInnerTexts(),
      ['OF', 'Cliente', 'Máquina', 'Prazo', 'Conclusão prevista', 'Margem (dias úteis)', 'Motivo', 'Estado']);
    for (const s of await page.locator('#fc-risks-table tbody td:last-child').allInnerTexts()) assert.ok(['atrasa', 'em risco'].includes(s), `só atrasa/em risco: ${s}`);
  }
  assert.ok((await page.locator('#fc-missing').innerText()).length > 5, 'previsão com dados em falta');
  if (shots) await page.screenshot({path: `${shots}/capacidade-dia.png`, fullPage: true});
  await page.click('#fc-semana');
  await page.waitForFunction(() => document.querySelectorAll('#fc-map-head th').length === 14, null, {timeout: 120000});
  assert.match(await page.locator('#fc-map-head th').nth(1).innerText(), /^S\d+/);

  // --- Cenários: sem cenarios.js, a frase combinada; com ?cenario, a faixa da simulação.
  await page.locator('#views button', {hasText: /^Cenários$/}).click();
  assert.match(page.url(), /vista=cenarios/);
  const hasScenarios = await page.evaluate(() => typeof window.cenariosView === 'function');
  if (!hasScenarios) assert.equal(await page.locator('#fc-cen').innerText(), 'Cenários ainda não disponíveis.');
  await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras&vista=calendario&cenario=fingido`);
  await page.waitForFunction(() => !document.querySelector('#fc-banner').hidden || !document.querySelector('#fc-error').hidden, null, {timeout: 120000});
  if (!(await page.locator('#fc-banner').isHidden())) {
    assert.match(await page.locator('#fc-banner').innerText(), /^(Simulação «.+»: nada mudou no plano em uso|Cenários ainda não disponíveis: mostra o plano em uso) · Ver plano em uso$/);
    assert.ok(!/cenario=/.test(await page.locator('#fc-banner a').getAttribute('href')), '«Ver plano em uso» sem o cenário');
  }

  // --- Python antigo (404 sem erro): a nota pede o reinício, nada parte.
  const old = await browser.newPage({viewport: {width: 1440, height: 1000}});
  await old.route(/\/planeamento\/api\/setor\/(calendario|capacidade-prazos)/, (r) => r.fulfill({status: 404, contentType: 'application/json', body: '{"detail":"Not Found"}'}));
  await old.goto(`${base}/planeamento/setor/carga?setor=cantoneiras&vista=calendario`);
  await old.waitForSelector('#fc-error:not([hidden])', {timeout: 60000});
  assert.match(await old.locator('#fc-error').innerText(), /precisa que o serviço do planeamento seja reiniciado/);
  await old.close();

  // --- 390 px: as 7 colunas deslizam dentro da grelha; a página não ganha scroll horizontal.
  await page.setViewportSize({width: 390, height: 900});
  for (const vista of ['calendario', 'capacidade']) {
    await page.goto(`${base}/planeamento/setor/carga?setor=perfis&vista=${vista}`);
    await page.waitForSelector(vista === 'calendario' ? '#fc-cal-body td.fc-day' : '#fc-map-body tr', {timeout: 240000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${vista} sem scroll horizontal a 390 px`);
    const box = vista === 'calendario' ? '#fc-cal-wrap' : '#fc-map-wrap';
    assert.ok(await page.evaluate((s) => { const b = document.querySelector(s); return b.scrollWidth > b.clientWidth; }, box), `${vista}: a grelha desliza`);
    if (shots) await page.screenshot({path: `${shots}/${vista}-390.png`, fullPage: true});
  }
  await page.locator('#fc-map-body').waitFor();
  await page.goto(`${base}/planeamento/setor/carga?setor=perfis&vista=calendario`);
  await page.waitForSelector('#fc-cal-body td.today', {timeout: 240000});
  await page.locator('#fc-cal-body td.today').click();
  await page.waitForSelector('#fc-day .fc-realized h3', {timeout: 60000});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'detalhe do dia sem scroll horizontal a 390 px');

  assert.deepEqual(writes, [], 'nada gravado');
  assert.deepEqual(errors, [], `erros no browser:\n${errors.join('\n')}`);
  await browser.close();
  console.log('Vistas da previsão na Carga: OK');
})().catch((e) => { console.error(e); process.exit(1); });
