// Carga e Gantt simples enquanto o servidor refaz as caches (07/10/2026): a página volta a pedir de 8 em 8 s,
// mas só volta a desenhar quando chega a versão atual. O detalhe aberto da Carga e o dia aberto do Gantt ficam
// como estão durante os pedidos repetidos (antes refaziam-se com «A carregar…» a cada pedido).
// Respostas da API sintéticas (nada vai à base); os 8 s passam a 50 ms no browser.
// Uso: SETOR_BASE=http://127.0.0.1:<porta> node tests/setor_stale_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.SETOR_BASE || 'http://127.0.0.1:8113';

const TODAY = '2026-10-07';
const json = (route, body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});

function carga(stale, load) {
  const monday = (i) => new Date(Date.UTC(2026, 9, 5 + 7 * i)).toISOString().slice(0, 10);
  const weeks = Array.from({length: 13}, (_, i) => ({year: 2026, week: 41 + i, monday: monday(i)}));
  const days = (i) => Array.from({length: 5}, (_, d) => ({date: new Date(Date.UTC(2026, 9, 5 + 7 * i + d)).toISOString().slice(0, 10), shifts: 1}));
  return {sector: 'cantoneiras', today: TODAY, weeks, stale,
    machines: [{id: 'm1', name: 'Máquina 1', has_calendar: true, after: 0, default_shifts: 1,
      late_before: {hours: 0, operations: 0, unknown: 0}, no_date: {hours: 0, operations: 0, unknown: 0},
      weeks: weeks.map((w, i) => ({...w, load, capacity: 40, full_capacity: 40, status: 'folga', shifts: 1, manual: false,
        plan: load, due: 0, suggested: 0, late: 0, unknown: 0, operations: 1, advice: {}, days: days(i)}))}],
    elsewhere: {operations: 0, hours: 0, machines: []}, settings: {template: 'x', workdays: [1, 2, 3, 4, 5], holidays: []}, shift_hours: [8]};
}

function quadro(stale, imported) {
  return {sector: 'cantoneiras', sector_label: 'MTG3 Cantoneiras', today: TODAY, imported_at: imported, day_view: true, stale,
    source: {kind: 'automatica', placed: 1, operations: 1, missing: []}, unplanned: {orders: []}, not_in_plans: [],
    elsewhere: {operations: 0, machines: []},
    machines: [{id: 'm1', name: 'Máquina 1', days: {}, boxes: [{of: 'OF1', start: TODAY, end: '2026-10-08', pieces: 1, hours: 2, customer: 'Cliente'}]}]};
}

async function waitFor(condition, timeout = 5000) {
  const end = Date.now() + timeout;
  while (!condition()) {
    if (Date.now() > end) throw new Error('condição não cumprida a tempo');
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

const dia = (stale) => ({sector: 'cantoneiras', day: TODAY, start: `${TODAY}T00:00:00+01:00`, end: '2026-10-08T00:00:00+01:00',
  bands: [], ticks: [], machines: [], elsewhere: {operations: 0}, today: TODAY, stale});

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const errors = [];
  const newPage = async () => {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
    await page.addInitScript(() => {  // os pedidos repetidos de 8 em 8 s passam a 50 ms
      const later = window.setTimeout;
      window.setTimeout = (fn, ms, ...rest) => later(fn, ms === 8000 ? 50 : ms, ...rest);
    });
    return page;
  };

  // --- Carga com o detalhe de uma semana aberto: respostas antigas até o ensaio mudar `fresh`
  {
    const page = await newPage();
    const seen = {carga: 0, celula: 0};
    let fresh = false;
    await page.route(/\/planeamento\/api\/setor\/carga\?/, (route) => { seen.carga += 1; return json(route, carga(!fresh, fresh ? 20 : 10)); });
    await page.route(/\/planeamento\/api\/setor\/carga\/celula\?/, (route) => { seen.celula += 1; return json(route, {orders: [], hours: 0, unknown: 0, excel_hours: 0}); });
    await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras`);
    await page.waitForSelector('#body td.c');
    await page.locator('#body td.c').first().click();
    await page.waitForFunction(() => document.querySelector('#detail-orders p')?.textContent.includes('0 OF'));
    await page.evaluate(() => { document.getElementById('detail-orders').dataset.marca = 'aberto'; });
    const before = {...seen};
    await waitFor(() => seen.carga >= before.carga + 3);
    assert.equal(seen.celula, before.celula, 'o detalhe aberto não volta a pedir a célula enquanto a resposta é a anterior');
    assert.equal(await page.locator('#detail-orders').getAttribute('data-marca'), 'aberto', 'o detalhe não foi refeito');
    assert.equal(await page.locator('#body td.c .load-cap').first().innerText(), '10 / 40 h');
    // Chega a versão atual: desenha uma vez, refaz o detalhe uma vez e deixa de pedir.
    fresh = true;
    await page.waitForFunction(() => document.querySelector('#body td.c .load-cap')?.textContent === '20 / 40 h');
    const done = seen.carga;
    await page.waitForTimeout(400);
    assert.equal(seen.carga, done, 'deixa de pedir quando a resposta é a atual');
    assert.equal(seen.celula, before.celula + 1, 'o detalhe aberto atualiza uma vez com a versão atual');
    assert.equal(await page.locator('#detail').isHidden(), false, 'o detalhe continua aberto');
    await page.close();
  }

  // --- Carga: um pedido repetido que falha mostra o erro (o recálculo de fundo falhou no servidor)
  {
    const page = await newPage();
    let calls = 0;
    await page.route(/\/planeamento\/api\/setor\/carga\?/, (route) => {
      calls += 1;
      return calls === 1 ? json(route, carga(true, 10)) : json(route, {error: 'Falhou o cálculo da carga.'}, 500);
    });
    await page.goto(`${base}/planeamento/setor/carga?setor=cantoneiras`);
    await page.waitForSelector('#body td.c');
    await page.waitForFunction(() => !document.getElementById('error').hidden);
    assert.equal(await page.locator('#error').innerText(), 'Falhou o cálculo da carga.');
    assert.equal(await page.locator('#body td.c .load-cap').first().innerText(), '10 / 40 h', 'a grelha anterior fica à vista');
    await page.waitForTimeout(300);
    assert.equal(calls, 2, 'depois do erro deixa de pedir');
    await page.close();
  }

  // --- Gantt simples com um dia aberto: respostas antigas até o ensaio mudar `fresh`
  {
    const page = await newPage();
    const seen = {quadro: 0, dia: 0};
    let fresh = false;
    await page.route(/\/planeamento\/api\/setor\/quadro\?/, (route) => {
      seen.quadro += 1;
      return json(route, quadro(!fresh, fresh ? '2026-10-07T10:00:00+00:00' : '2026-10-07T09:00:00+00:00'));
    });
    await page.route(/\/planeamento\/api\/setor\/quadro\/dia\?/, (route) => { seen.dia += 1; return json(route, dia(false)); });
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras&dia=${TODAY}`);
    await page.waitForFunction(() => document.querySelector('#day-content p')?.textContent.includes('não tem máquinas'));
    await page.evaluate(() => { document.querySelector('#day-content p').dataset.marca = 'aberto'; });
    const before = {...seen};
    await waitFor(() => seen.quadro >= before.quadro + 3);
    assert.equal(seen.dia, before.dia, 'o dia aberto não volta a carregar enquanto o quadro é o anterior');
    assert.equal(await page.locator('#day-content p').getAttribute('data-marca'), 'aberto', 'o dia não foi trocado por «A carregar o dia…»');
    fresh = true;
    await page.waitForFunction(() => /11:00/.test(document.getElementById('source').textContent));
    const done = seen.quadro;
    await page.waitForTimeout(400);
    assert.equal(seen.quadro, done, 'deixa de pedir quando o quadro é o atual');
    assert.equal(seen.dia, before.dia + 1, 'com o quadro atual, o dia aberto atualiza uma vez');
    await page.close();
  }

  // --- Gantt simples: um pedido repetido que falha mostra o erro e mantém o quadro anterior
  {
    const page = await newPage();
    let calls = 0;
    await page.route(/\/planeamento\/api\/setor\/quadro\?/, (route) => {
      calls += 1;
      return calls === 1 ? json(route, quadro(true, '2026-10-07T09:00:00+00:00')) : json(route, {error: 'Falhou o cálculo do plano.'}, 500);
    });
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras`);
    await page.waitForFunction(() => !document.getElementById('notice').hidden);
    assert.equal(await page.locator('#notice').innerText(), 'Falhou o cálculo do plano.');
    assert.match(await page.locator('#source').innerText(), /dados de 07\/10, 10:00/, 'o quadro anterior fica à vista');
    await page.waitForTimeout(300);
    assert.equal(calls, 2, 'depois do erro deixa de pedir');
    await page.close();
  }

  await browser.close();
  assert.deepEqual(errors, [], `erros na página: ${errors.join(' | ')}`);
  console.log('ok: Carga e Gantt simples não se redesenham enquanto a resposta é a anterior');
})().catch((e) => { console.error(e); process.exit(1); });
