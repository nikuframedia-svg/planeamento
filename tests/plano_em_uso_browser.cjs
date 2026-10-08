// Gantt simples com o plano em uso (Etapa 3, 08/10/2026): a linha de origem, a caixa com a conclusão prevista, a
// margem e os avisos no diálogo, a 2.ª operação só contada e a resposta antiga (Python anterior) ainda desenhada.
// Respostas da API sintéticas (nada vai à base). Com PLANO_REAL=1 abre também a página com os dados do servidor
// (só leituras) e confirma que desenha sem erros.
// Uso: SETOR_BASE=http://127.0.0.1:<porta> [PLANO_REAL=1] node tests/plano_em_uso_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.SETOR_BASE || 'http://127.0.0.1:8113';

const TODAY = '2026-10-08';
const json = (route, body) => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

function quadro(source, box) {
  return {sector: 'cantoneiras', sector_label: 'MTG3 Cantoneiras', today: TODAY, imported_at: '2026-10-08T07:00:00+00:00', day_view: true,
    stale: false, source, unplanned: {orders: []}, not_in_plans: [], elsewhere: {operations: 0, machines: []},
    machines: [{id: 'm1', name: 'Ficep XP T4', days: {[TODAY]: 15}, boxes: [box]}]};
}

const box = {of: 'OF264095', start: TODAY, end: '2026-10-10', pieces: 1200, pieces_unknown: 0, lines: 125, hours: 18.75, hours_unknown: 0,
  hours_estimated: 125, customer: 'PAINHAS, SA', designation: 'Postes', due: '2026-07-28', late: true, approximate: false,
  days: [{date: TODAY, hours: 15}, {date: '2026-10-09', hours: 3.75}], shifts: [{date: TODAY, shift: 1, hours: 7.5}],
  keys: ['v2:a', 'v2:b'], start_at: '2026-10-08T05:00:00+00:00', end_at: '2026-10-09T08:45:00+00:00',
  conclusion: '2026-10-13T05:33:09+00:00', margin_days: -4, risk: 'atrasa', already_late: true, conflicts: ['Iniciada na Peddi 8']};

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const errors = [];
  const newPage = async (width = 1440) => {
    const page = await browser.newPage({viewport: {width, height: 1000}});
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
    return page;
  };
  const mock = async (page, body) => {
    await page.route('**/planeamento/api/setor/quadro?*', (route) => json(route, body));
    await page.route('**/planeamento/api/setor/quadro/dia?*', (route) => json(route, {sector: 'cantoneiras', day: TODAY, start: `${TODAY}T00:00:00+01:00`,
      end: '2026-10-09T00:00:00+01:00', bands: [], ticks: [], machines: [], elsewhere: {operations: 0}, today: TODAY, stale: false}));
    await page.route('**/planeamento/api/carteira/selecao', (route) => route.abort());  // nada se grava
  };

  // --- Plano em uso: origem, caixa e diálogo
  {
    const page = await newPage();
    await mock(page, quadro({kind: 'plano_em_uso', origin: '2026-10-08T05:00:00+00:00', placed: 141, operations: 141, missing: [
      {of: 'OF1', reference: 'R1', operation: 'Corte', reasons: ['Sem horas']}], second_operation: 3}, box));
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras`);
    await page.waitForFunction(() => document.querySelector('#source')?.textContent.includes('Plano em uso'));
    const source = await page.textContent('#source');
    assert.match(source, /MTG3 Cantoneiras · Plano em uso \(previsão com capacidade finita\) · 141 operações Planeadas/);
    assert.match(await page.textContent('#second-operation'), /3 operações de 2.ª operação fora do plano/);
    const missing = await page.textContent('#missing summary');
    assert.match(missing, /1 operação planeada não aparece no quadro$/);
    await page.click('.pq-box');
    const dialog = await page.textContent('#dialog-body');
    assert.match(dialog, /Nesta máquina08\/10, 06:00 a 09\/10, 09:45/);
    assert.match(dialog, /Conclusão prevista13\/10, 06:33/);
    assert.match(dialog, /Margem4 dias úteis depois do prazo/);
    assert.match(dialog, /AvisosIniciada na Peddi 8/);
    assert.equal(await page.getAttribute('#dialog-body dd:nth-of-type(8)', 'class'), 'late');  // linha «Prazo»
    await page.close();
  }

  // --- Resposta antiga (Python anterior, proposta automática): continua a desenhar, sem as linhas novas
  {
    const page = await newPage(390);
    const old = {...box}; for (const k of ['keys', 'start_at', 'end_at', 'conclusion', 'margin_days', 'risk', 'already_late', 'conflicts']) delete old[k];
    await mock(page, quadro({kind: 'automatica', placed: 1, operations: 2, missing: []}, old));
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras`);
    await page.waitForFunction(() => document.querySelector('#source')?.textContent.includes('proposta automática'));
    await page.click('.pq-box');
    const dialog = await page.textContent('#dialog-body');
    assert.ok(!/Conclusão prevista|Margem|Nesta máquina|Avisos/.test(dialog));
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 390 + 1, `sem deslocamento horizontal a 390 px (${width})`);
    await page.close();
  }

  // --- Dados reais (opcional, só leituras): a página desenha com o plano em uso do servidor
  if (process.env.PLANO_REAL === '1') {
    const page = await newPage();
    await page.route('**/planeamento/api/carteira/selecao', (route) => route.abort());
    await page.goto(`${base}/planeamento/gantt?setor=cantoneiras`);
    await page.waitForFunction(() => /Plano em uso/.test(document.querySelector('#source')?.textContent || ''), null, {timeout: 600000});
    const boxes = await page.$$eval('.pq-box', (n) => n.length);
    const source = await page.textContent('#source');
    console.log(`real: ${source} · ${boxes} caixas nesta semana`);
    if (boxes) {
      await page.click('.pq-box');
      const dialog = await page.textContent('#dialog-body');
      assert.match(dialog, /Nesta máquina/);
      console.log('real: diálogo ·', dialog.replace(/\s+/g, ' ').slice(0, 400));
    }
    await page.close();
  }

  await browser.close();
  assert.deepEqual(errors, []);
  console.log('plano_em_uso_browser: OK');
})().catch((e) => { console.error(e); process.exit(1); });
