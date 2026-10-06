// Aceitação de Carga e turnos, Definições do setor e Gantt semanal (pedido do Luís, 06/10/2026).
// Nada é gravado: os pedidos de gravação são intercetados e respondidos com uma confirmação simulada;
// o teste confirma o que a página pediria ao servidor.
// Uso: SETOR_BASE=http://127.0.0.1:8113 SETOR_SHOTS=/tmp/setor [SETOR_CARGA_DIR=<pasta>] node tests/setor_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.SETOR_BASE || 'http://127.0.0.1:8113';
const shots = process.env.SETOR_SHOTS;
const cargaDir = process.env.SETOR_CARGA_DIR;
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [], writes = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('requestfailed', (r) => { if (r.failure()?.errorText !== 'net::ERR_ABORTED') errors.push(`${r.url()} ${r.failure()?.errorText}`); });
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  page.on('dialog', (d) => d.accept());
  await page.route('**/planeamento/api/**', async (route) => {
    const req = route.request();
    if (req.method() === 'GET') return route.continue();
    writes.push({url: req.url(), body: req.postDataJSON()});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({changed: 1, weeks: 1, revision: 1})});
  });

  // Carga e turnos (tabela simples, 07/10/2026): uma linha por máquina com calendário, «carga / capacidade h»,
  // Atrasado à parte, postos sem calendário numa lista fechada, − / + só no detalhe.
  // SETOR_CARGA_DIR=<pasta com carga-<setor>.json> serve a resposta nova da API (gerada só de leitura) enquanto o
  // serviço não é reiniciado; sem ela, usa a API ao vivo (antiga ou nova).
  if (cargaDir) {
    await page.route(/\/planeamento\/api\/setor\/carga\?/, (route) => {
      const setor = new URL(route.request().url()).searchParams.get('setor');
      return route.fulfill({status: 200, contentType: 'application/json', body: fs.readFileSync(`${cargaDir}/carga-${setor}.json`, 'utf8')});
    });
  }
  const NUM = '[\\d\\s\\u00a0\\u202f.]+';
  await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras`);
  await page.waitForSelector('#body tr td.c', {timeout: 120000});
  const headers = await page.locator('#head th').allInnerTexts();
  const modern = headers.includes('Atrasado (h)');
  assert.equal(headers[0], 'Máquina');
  assert.deepEqual(headers.slice(-2), ['Sem prazo (h)', 'Mais tarde (h)']);
  assert.equal(headers.length, modern ? 17 : 16, 'Máquina + Atrasado + 13 semanas + Sem prazo + Mais tarde');
  if (cargaDir) assert.ok(modern, 'resposta nova: coluna Atrasado');
  const rows = await page.locator('#body tr').count();
  assert.ok(rows >= 3, `máquinas da MTG3 na grelha (${rows})`);
  assert.equal(await page.locator('#body td.c').count(), rows * 13, '13 semanas por máquina');
  for (const t of await page.locator('#body td.c .load-cap').allInnerTexts()) assert.match(t, new RegExp(`^${NUM} / ${NUM} h$`), `célula «carga / capacidade h»: ${t}`);
  assert.equal(await page.locator('#body td.c button.pm').count(), 0, '− / + saíram das células');
  if (modern) {
    // A cor bate com os números escritos: carga / capacidade da semana (o atrasado tem a sua coluna).
    const cells = await page.locator('#body td.c').evaluateAll((tds) => tds.map((td) => ({text: td.querySelector('.load-cap').textContent, cls: td.className})));
    for (const {text, cls} of cells) {
      const [load, cap] = text.replace(' h', '').split(' / ').map((x) => Number(x.replace(/[\s\u00a0\u202f.]/g, '')));
      const want = load - cap > 0.5 ? 'falta' : cap - load >= 0.15 * cap + 0.5 ? 'folga' : null;  // perto dos limites, os arredondamentos decidem
      if (want) assert.ok(cls.split(' ').includes(want), `«${text}» devia ser ${want} (${cls})`);
    }
    // Atrasado a 0: sem aspeto de clique e sem abrir o detalhe.
    const zero = page.locator('#body tr > th + td.num:not(.clickable)').first();
    if (await zero.count()) {
      assert.equal(await zero.innerText(), '0');
      await zero.click();
      await page.waitForTimeout(200);
      assert.equal(await page.locator('#detail').isVisible(), false, 'Atrasado 0 não abre o detalhe');
    }
  }
  assert.equal(await page.locator('#body td.c.sem_calendario').count(), 0, 'sem células cinzentas');
  for (const t of await page.locator('#body td.c button.apply').allInnerTexts()) assert.match(t, /^[+−]\d turnos?$/);
  // Postos sem calendário: lista fechada, sem botões.
  const nocal = page.locator('#no-calendar details');
  if (await nocal.count()) {
    assert.equal(await nocal.getAttribute('open'), null, 'lista fechada');
    assert.match(await nocal.locator('summary').innerText(), /^Postos sem calendário: /);
    assert.equal(await page.locator('#no-calendar button').count(), 0, 'sem botões');
    const names = await page.locator('#body tr th').allInnerTexts();
    for (const li of await nocal.locator('li').allTextContents()) assert.ok(!names.includes(li.split(' · ')[0]), `${li} fora da tabela`);
  }
  // «Aplicar todas» só junta recomendações do mesmo sentido e diz quantas.
  const plusAdvice = (await page.locator('#body td.c button.apply').allInnerTexts()).filter((t) => t.startsWith('+')).length;
  if (plusAdvice) assert.equal(await page.locator('#apply-all').innerText(), `Aplicar todas: mais turnos (${plusAdvice})`);
  // Detalhe da semana atual: resumo curto, turnos da semana (− / +) e por dia, OF.
  const first = page.locator('#body tr').first().locator('td.c .load-cap').first();
  await first.click();
  await page.waitForFunction(() => document.querySelector('#detail table.orders') || /0 OF/.test(document.getElementById('detail').innerText), null, {timeout: 120000});
  await page.waitForFunction(() => !/…/.test(document.getElementById('detail-summary')?.innerText || '…'), null, {timeout: 120000});
  const summary = await page.locator('#detail-summary').innerText();
  for (const label of ['Capacidade', 'Carga', 'Horas segundo o Excel']) assert.ok(summary.includes(label), `resumo com ${label}`);
  if (modern) {
    assert.match(summary, /Atrasado/);
    assert.match(summary, /faltam [\d\s  .,]+ h desta semana/);
  }
  assert.equal(await page.locator('#detail .day').count(), 7, 'sete dias no detalhe');
  assert.equal(await page.locator('#week-shifts button.pm').count(), 2, '− / + da semana no detalhe');
  assert.match(await page.locator('#detail a[href*="/planeamento/gantt?setor=cantoneiras&semana="]').getAttribute('href'), /semana=\d{4}-W\d{2}$/);
  if (shots) await page.screenshot({path: `${shots}/carga.png`, fullPage: true});
  // + da semana (no detalhe): pede turnos atuais + 1 para essa máquina e semana.
  const plus = page.locator('#week-shifts button.pm').nth(1);
  const before = Number((await page.locator('#week-shifts').innerText()).match(/(\d) turno/)[1]);
  if (await plus.isEnabled()) {
    await plus.click();
    await page.waitForFunction(() => /semana\(s\) atualizadas/.test(document.getElementById('notice').textContent));
    const sent = writes.at(-1);
    assert.match(sent.url, /\/planeamento\/api\/setor\/turnos$/);
    assert.equal(sent.body.setor, 'cantoneiras');
    assert.equal(sent.body.mudancas.length, 1);
    assert.equal(sent.body.mudancas[0].turnos, before + 1);
    assert.ok(sent.body.mudancas[0].semana && sent.body.mudancas[0].ano && sent.body.request_id);
  }
  // − / + num dia do detalhe: pede o dia (AAAA-MM-DD), não a semana.
  const dayPlus = page.locator('#detail .day button.pm:not([disabled])').first();
  if (await dayPlus.count()) {
    const n = writes.length;
    await dayPlus.click();
    await page.waitForFunction(() => document.getElementById('notice').textContent.length > 0);
    await page.waitForTimeout(300);
    assert.equal(writes.length, n + 1);
    assert.match(writes.at(-1).body.mudancas[0].dia, /^\d{4}-\d{2}-\d{2}$/);
  }
  // Aplicar uma recomendação, se houver: turnos da semana + delta.
  const apply = page.locator('#body td.c button.apply').first();
  if (await apply.count()) {
    const n = writes.length;
    await apply.click();
    await page.waitForFunction((k) => document.getElementById('notice').textContent.length > 0 && k, n);
    await page.waitForTimeout(300);
    assert.equal(writes.length, n + 1, 'Aplicar envia um pedido');
  }
  if (plusAdvice) {
    const n = writes.length;
    await page.click('#apply-all');
    await page.waitForFunction((k) => document.getElementById('notice').textContent.startsWith('Aplicar todas') && k, n);
    assert.equal(writes.at(-1).body.mudancas.length, plusAdvice, 'Aplicar todas envia só as do mesmo sentido');
  }

  // Cálculo de uma operação e produção registada (continuam dentro do detalhe).
  await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras`);
  await page.waitForSelector('#body tr td.c', {timeout: 120000});
  await page.locator('#body tr').first().locator('td.c .load-cap').first().click();
  await page.waitForFunction(() => /Horas segundo o Excel/.test(document.getElementById('detail-summary')?.innerText || '') && !/…/.test(document.getElementById('detail-summary').innerText), null, {timeout: 120000});
  const firstOrder = page.locator('#detail-orders tr.clickable').first();
  if (await firstOrder.count()) {
    await firstOrder.click();
    await page.waitForSelector('#detail-operations table', {timeout: 120000});
    await page.locator('#detail-operations details summary').first().click();
    assert.match(await page.locator('#detail-operations dl.proof').first().innerText(), /Fórmula/);
  }
  await page.click('#production-open');
  await page.waitForFunction(() => /registos validados|Sem produção/.test(document.getElementById('detail-production').innerText), null, {timeout: 60000});
  if (shots) await page.screenshot({path: `${shots}/carga-detalhe.png`, fullPage: true});
  // Separador Máquinas: 6 colunas; a antiga «Capacidades das máquinas» abre aqui.
  await page.goto(`${base}/planeamento/capacidades?area=perfis`);
  assert.match(page.url(), /\/planeamento\/setor\/carga\?setor=perfis&vista=maquinas/);
  await page.waitForSelector('#machines-table tbody tr', {timeout: 120000});
  assert.ok(!(await page.locator('#machines-view').isHidden()), 'vista Máquinas aberta');
  assert.deepEqual(await page.locator('#machines-table thead th').allInnerTexts(),
    ['Máquina', 'Por fazer (mm²)', 'Horas previstas', 'Atrasado (h)', 'Sem prazo (h)', 'Semanas de trabalho']);
  assert.match(await page.locator('#machines-table tbody tr').first().getAttribute('title'), /Horas segundo o Excel/);
  if (shots) await page.screenshot({path: `${shots}/carga-maquinas.png`, fullPage: true});
  await page.goto(`${base}/planeamento/disponibilidade?area=cantoneiras`);
  assert.match(page.url(), /\/planeamento\/setor\/carga\?setor=cantoneiras$/);
  // Telemóvel (390 px): a tabela desliza dentro da caixa, a página não.
  await page.setViewportSize({width: 390, height: 900});
  for (const setor of ['cantoneiras', 'perfis']) {
    await page.goto(`${base}/planeamento/setor/carga?setor=${setor}`);
    await page.waitForSelector('#body tr td.c', {timeout: 120000});
    await page.locator('#body tr').first().locator('td.c .load-cap').first().click();
    await page.waitForSelector('#week-shifts');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Carga ${setor} sem scroll horizontal a 390 px`);
    if (shots) await page.screenshot({path: `${shots}/carga-390-${setor}.png`, fullPage: true});
  }
  await page.setViewportSize({width: 1440, height: 1000});

  // Definições do setor: máquinas, turnos, feriados, regras.
  await page.goto(`${base}/planeamento/setor/definicoes?setor=perfis`);
  await page.waitForSelector('#machines tr', {timeout: 60000});
  assert.ok(await page.locator('#machines tr').count() >= 2, 'máquinas da MTG2');
  assert.equal(await page.locator('#template input').count(), 6, 'três turnos × início/fim');
  assert.match(await page.locator('#holidays').inputValue(), /2026-12-25/);
  assert.ok((await page.locator('#rules').innerText()).length > 20, 'regras do setor visíveis');
  assert.ok(await page.locator('#machines details.names').count() >= 1, 'nomes e operações das máquinas');
  await page.waitForSelector('#worked .worked-form', {timeout: 60000});
  if (shots) await page.screenshot({path: `${shots}/definicoes.png`, fullPage: true});

  // Gantt semanal: sete colunas (seg a dom), «planeado / capacidade h» por dia, ◀ ▶ mudam de semana.
  await page.goto(`${base}/planeamento/gantt`);
  await page.waitForFunction(() => /^Semana \d+ · /.test(document.getElementById('range').textContent), null, {timeout: 120000});
  const range = await page.locator('#range').innerText();
  const rowsGantt = await page.locator('#gantt .pq-row').count();
  assert.ok(rowsGantt >= 1, 'máquinas no Gantt');
  const cells = await page.locator('#gantt .pq-row').first().locator('.pq-cell').count();
  assert.equal(cells, 7, 'sete dias por máquina');
  assert.ok(await page.locator('#gantt .pq-load').count() > 0, 'horas planeadas / capacidade por dia');
  assert.match(await page.locator('#gantt .pq-load').first().innerText(), /^[\d,]+ \/ [\d,]+ h$/);
  if (shots) await page.screenshot({path: `${shots}/gantt-semana.png`, fullPage: true});
  await page.click('#next');
  await page.waitForFunction((r) => document.getElementById('range').textContent !== r, range);
  await page.click('#today');
  await page.waitForFunction((r) => document.getElementById('range').textContent === r, range);

  // Só as máquinas do setor (Definições = mesma regra) no Gantt da semana e do dia.
  const own = (await (await page.request.get(`${base}/planeamento/api/setor/definicoes?setor=cantoneiras`)).json()).machines.map((m) => m.id);
  for (const id of await page.locator('#gantt .pq-row').evaluateAll((rows) => rows.map((r) => r.dataset.id))) assert.ok(own.includes(id), `máquina ${id} é do setor`);

  // Dia hora a hora: 7 dias clicáveis; eixo com 23–25 horas; faixas e totais por turno; voltar à semana.
  assert.equal(await page.locator('#gantt .pq-day-link').count(), 7, 'sete dias clicáveis');
  await page.locator('#gantt .pq-day-link.today, #gantt .pq-day-link').first().click();
  await page.waitForSelector('#day-content .pq-day-row', {timeout: 120000});
  assert.match(page.url(), /[?&]dia=\d{4}-\d{2}-\d{2}/);
  const ticks = await page.locator('#day-content .pq-tick').count();
  assert.ok(ticks >= 23 && ticks <= 25, `horas do dia (${ticks})`);
  assert.ok(await page.locator('#day-content .pq-band', {hasText: '1.º turno'}).count() >= 1, 'faixa do 1.º turno');
  for (const t of await page.locator('#day-content .pq-shift-total').allInnerTexts()) assert.match(t, /^\d\.º turno( de \S+ \d\d\/\d\d)?: [\d,]+ \/ [\d,]+ h$/);
  for (const id of await page.locator('#day-content .pq-day-row[data-id]').evaluateAll((rows) => rows.map((r) => r.dataset.id))) assert.ok(own.includes(id), `máquina ${id} do dia é do setor`);
  if (shots) await page.screenshot({path: `${shots}/gantt-dia.png`, fullPage: true});
  await page.click('#day-back');
  await page.waitForFunction(() => !document.getElementById('week-board').hidden && !/dia=/.test(location.search));
  // Uma máquina num dia, a partir da célula da semana.
  await page.locator('#gantt .pq-row .pq-cell.clickable').first().click({position: {x: 5, y: 5}});
  await page.waitForSelector('#day-content .pq-day-row', {timeout: 120000});
  assert.equal(await page.locator('#day-content .pq-day-row[data-id]').count(), 1, 'só essa máquina');
  assert.match(page.url(), /maquina=/);
  await page.goBack();
  await page.waitForFunction(() => !document.getElementById('week-board').hidden);

  // Telemóvel: sem deslocamento horizontal da página.
  await page.setViewportSize({width: 390, height: 900});
  const todayIso = new Date().toISOString().slice(0, 10);
  for (const url of ['/planeamento/setor/carga?setor=perfis', '/planeamento/setor/definicoes?setor=cantoneiras', `/planeamento/gantt?setor=cantoneiras&dia=${todayIso}`]) {
    await page.goto(base + url);
    await page.waitForTimeout(1500);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `sem scroll horizontal em ${url}`);
  }

  assert.deepEqual(errors, []);
  console.log(`setor_browser: OK · ${rows} máquinas MTG3 · ${rowsGantt} no Gantt · ${writes.length} gravações intercetadas · ${range}`);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
