// KPIs da semana na Carteira (P4, 08/10/2026) e 2.ª operação fora das listas (P3-A). Nada é gravado: qualquer POST
// de gravação é intercetado e falha o teste.
// Compara, máquina a máquina, a Carga e turnos da semana atual (/api/setor/carga) com /api/carteira/kpis?semanas=<atual>
// e confirma o cabeçalho «MTG3 Cantoneiras · Semana N (dd/mm–dd/mm) · …»; sem Prazo não há linha de âmbito (P6).
// Uso: CARTEIRA_BASE=http://127.0.0.1:8191 [CARTEIRA_SHOT=/caminho.png] node tests/carteira_semana_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.CARTEIRA_BASE || 'http://127.0.0.1:8113';
const shot = process.env.CARTEIRA_SHOT;
const SECOND = ['Saca bocados', 'Plasma manual', 'Fresadora', 'Prensa'];
const h1 = new Intl.NumberFormat('pt-PT', {maximumFractionDigits: 1});

async function json(path) {
  const response = await fetch(`${base}${path}`, {headers: {Accept: 'application/json'}});
  const body = await response.json();
  assert.ok(response.ok, `${path}: ${response.status} ${body.error || ''}`);
  return body;
}

(async () => {
  // 1. API: a semana atual da Carga é a dos KPIs, máquina a máquina.
  const carga = await json('/planeamento/api/setor/carga?setor=cantoneiras');
  const week = carga.weeks[0];
  const code = `${week.year}-W${String(week.week).padStart(2, '0')}`;
  const kpis = await json(`/planeamento/api/carteira/kpis?setor=cantoneiras&semanas=${code}`);
  assert.ok(kpis.scope, 'a API dos KPIs não tem «scope»: falta a Python nova');
  assert.deepEqual(kpis.scope.weeks, [code]);
  assert.equal(kpis.scope.current, true);
  assert.equal(kpis.scope.sector_label, 'MTG3 Cantoneiras');
  assert.match(kpis.scope.label, new RegExp(`^Semana ${week.week} \\(\\d\\d/\\d\\d–\\d\\d/\\d\\d\\)$`));
  const rows = new Map(carga.machines.map((m) => [m.id, m]));
  const shown = kpis.panels.flatMap((p) => p.machines).filter((m) => m.week && rows.has(m.id));
  assert.ok(shown.length >= 4, 'poucas máquinas para comparar');
  for (const m of shown) {
    const row = rows.get(m.id), cell = row.weeks[0];
    assert.deepEqual([m.week.load, m.week.capacity, m.week.status], [cell.load, cell.full_capacity, cell.status], `${m.name}: KPI ≠ célula da Carga`);
    assert.deepEqual([m.week.plan, m.week.due, m.week.suggested, m.week.unknown], [cell.plan, cell.due, cell.suggested, cell.unknown], `${m.name}: tipos`);
    assert.equal(m.week.late_before, row.late_before.hours, `${m.name}: atrasado`);
  }
  // E2-03: todas as máquinas com célula na Carga entram (painéis ou outras): a soma bate com o total da semana.
  const everyWeek = [...kpis.panels.flatMap((p) => p.machines), ...(kpis.other_machines || [])].filter((m) => m.week);
  assert.equal(Math.round(everyWeek.reduce((a, m) => a + m.week.load, 0) * 10) / 10, kpis.week_totals.load, 'soma das máquinas ≠ total da semana');
  assert.ok((kpis.other_machines || []).every((m) => m.week), 'na semana, as outras máquinas levam os números da semana (E2-10)');
  console.log('Semana', code, '·', shown.map((m) => `${m.name} ${m.week.load}/${m.week.capacity} h (${m.week.status}) atrasado ${m.week.late_before}`).join(' · '));
  // 2.ª operação: fora das linhas da Carga e de «Atribuir máquina»/Conjuntos; só contada à parte.
  for (const name of SECOND) assert.ok(!carga.machines.some((m) => m.name === name), `${name} ainda é linha da Carga`);
  const sets = await json('/planeamento/api/carteira/conjuntos?setor=cantoneiras');
  for (const name of SECOND) assert.ok(!sets.machines.some((m) => m.name === name), `${name} ainda se pode atribuir`);
  console.log('2.ª operação:', carga.second_operation.text || '(nenhuma)');

  // 2. Ecrã: cabeçalho, números e cor das máquinas iguais à API; os acréscimos (+…) não aparecem na semana.
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [], writes = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  for (const path of ['selecao', 'maquina', 'conjuntos', 'conjuntos/arquivar']) {
    await page.route(`**/planeamento/api/carteira/${path}`, async (route) => {
      if (route.request().method() === 'POST') { writes.push(path); await route.abort(); } else await route.continue();
    });
  }
  try {
    await page.goto(`${base}/planeamento/carteira?setor=cantoneiras&semanas=${code}`);
    await page.waitForSelector('#kpis .kpis-scope', {timeout: 180000});
    await page.waitForFunction(() => /Semana \d+/.test(document.querySelector('#kpis .kpis-scope').textContent), null, {timeout: 180000});
    const scope = await page.textContent('#kpis .kpis-scope');
    assert.equal(scope, `MTG3 Cantoneiras · ${kpis.scope.label} · carga e capacidade como na Carga e turnos`);
    assert.equal(await page.textContent('#semanas-resumo'), (await page.locator(`#semanas-lista input[value="${code}"]`).getAttribute('data-label')));
    for (const m of shown) {
      const li = page.locator(`#kpis li[data-machine="${m.id}"]`);
      const text = (await li.locator('.m-hours').textContent()).trim();
      assert.equal(text, `${h1.format(m.week.load)} / ${h1.format(m.week.capacity)} h`, `${m.name} no ecrã`);
      assert.match(await li.locator('.m-hours').getAttribute('class'), new RegExp(`st-${m.week.status}`));
      assert.match(await li.locator('.m-hours').getAttribute('title'), /^no plano .* · a vencer .* · sugerida /);
      assert.equal(await li.locator('.m-late').count(), m.week.late_before > 0 ? 1 : 0);
    }
    assert.equal(await page.locator('#kpis .delta').count(), 0, 'na semana não há acréscimos (+…)');
    const resumo = await page.locator('#kpis .resumo tbody tr[data-state="sem_maquina"] td').nth(1).textContent();
    assert.match(resumo, /na sugerida/);
    if (shot) await page.screenshot({path: shot, fullPage: false});

    if ((kpis.other_machines || []).length) {
      assert.match(await page.textContent('#kpis .others'), / h( · |$)/, 'outras máquinas na semana em horas da semana');
    }
    // Limpar filtros: volta logo à carga do que está Planeado, com os acréscimos e sem linha de âmbito (P6).
    await page.click('#limpar-filtros');
    await page.waitForFunction(() => !document.querySelector('#kpis .kpis-scope') && document.querySelector('#kpis .delta'), null, {timeout: 60000});
    assert.ok(await page.locator('#kpis .delta').count() > 0);
    // Escolher a semana no Prazo recarrega os KPIs (sem recarregar a página).
    await page.click('#semanas summary');
    await page.locator(`#semanas-lista input[value="${code}"]`).check();
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => /Semana \d+/.test(document.querySelector('#kpis .kpis-scope')?.textContent || ''), null, {timeout: 120000});

    // Telemóvel: os painéis cabem em 390 px.
    await page.setViewportSize({width: 390, height: 900});
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => { const k = document.getElementById('kpis'); return k.scrollWidth - k.clientWidth; });
    assert.ok(overflow <= 1, `os KPIs passam a largura do telemóvel (${overflow} px)`);
    assert.deepEqual(writes, [], 'nada é gravado');
    assert.deepEqual(errors, []);
    console.log('OK · carteira_semana_browser');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
