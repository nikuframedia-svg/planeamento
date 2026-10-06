// Aceitação de Carga e turnos, Definições do setor e Gantt semanal (pedido do Luís, 06/10/2026).
// Nada é gravado: os pedidos de gravação são intercetados e respondidos com uma confirmação simulada;
// o teste confirma o que a página pediria ao servidor.
// Uso: SETOR_BASE=http://127.0.0.1:8113 SETOR_SHOTS=/tmp/setor node tests/setor_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.SETOR_BASE || 'http://127.0.0.1:8113';
const shots = process.env.SETOR_SHOTS;

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

  // Carga e turnos: grelha máquina × 13 semanas, detalhe por OF, − / + por semana e por dia, recomendação.
  await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras`);
  await page.waitForSelector('#body tr td.c', {timeout: 120000});
  const weeks = await page.locator('#head th').count();
  assert.equal(weeks, 14, 'Máquina + 13 semanas');
  const rows = await page.locator('#body tr').count();
  assert.ok(rows >= 3, `máquinas da MTG3 na grelha (${rows})`);
  const first = page.locator('#body tr').first().locator('td.c').first();
  assert.match(await first.locator('.cap').innerText(), /^\d t · [\d\s.]+ h/);
  await first.click();
  await page.waitForFunction(() => document.querySelector('#detail table.orders') || /0 OF/.test(document.getElementById('detail').innerText), null, {timeout: 120000});
  assert.equal(await page.locator('#detail .day').count(), 7, 'sete dias no detalhe');
  assert.match(await page.locator('#detail a[href*="/planeamento/gantt?setor=cantoneiras&semana="]').getAttribute('href'), /semana=\d{4}-W\d{2}$/);
  if (shots) await page.screenshot({path: `${shots}/carga.png`, fullPage: true});
  // + numa semana: pede turnos atuais + 1 para essa máquina e semana.
  const plus = page.locator('#body tr').first().locator('td.c').nth(1).locator('button.pm').nth(1);
  const before = Number((await page.locator('#body tr').first().locator('td.c').nth(1).locator('.cap').innerText()).split(' ')[0]);
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
    await dayPlus.click();
    await page.waitForFunction((n) => document.getElementById('notice').textContent && n, writes.length);
    const sent = writes.at(-1);
    assert.match(sent.body.mudancas[0].dia, /^\d{4}-\d{2}-\d{2}$/);
  }
  // Aplicar uma recomendação, se houver.
  const apply = page.locator('#body button.apply').first();
  if (await apply.count()) {
    const n = writes.length;
    await apply.click();
    await page.waitForFunction((k) => document.getElementById('notice').textContent.length > 0 && k, n);
    assert.equal(writes.length, n + 1, 'Aplicar envia um pedido');
  }

  // Definições do setor: máquinas, turnos, feriados, regras.
  await page.goto(`${base}/planeamento/setor/definicoes?setor=perfis`);
  await page.waitForSelector('#machines tr', {timeout: 60000});
  assert.ok(await page.locator('#machines tr').count() >= 2, 'máquinas da MTG2');
  assert.equal(await page.locator('#template input').count(), 6, 'três turnos × início/fim');
  assert.match(await page.locator('#holidays').inputValue(), /2026-12-25/);
  assert.ok((await page.locator('#rules').innerText()).length > 20, 'regras do setor visíveis');
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

  // Telemóvel: sem deslocamento horizontal da página.
  await page.setViewportSize({width: 390, height: 900});
  for (const url of ['/planeamento/setor/carga?setor=perfis', '/planeamento/setor/definicoes?setor=cantoneiras']) {
    await page.goto(base + url);
    await page.waitForTimeout(1500);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `sem scroll horizontal em ${url}`);
  }

  assert.deepEqual(errors, []);
  console.log(`setor_browser: OK · ${rows} máquinas MTG3 · ${rowsGantt} no Gantt · ${writes.length} gravações intercetadas · ${range}`);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
