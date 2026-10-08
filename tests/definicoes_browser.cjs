// Definições do setor: secção «Planeamento» (P9, 08/10/2026) e 2.ª operação fora da lista (P3-A).
// Nada é gravado: as gravações são intercetadas e respondidas com uma confirmação simulada; o teste confirma o que a
// página pediria ao servidor. O «medido» e a 2.ª operação são acrescentados à resposta quando a base ainda não os tem.
// Uso: DEFS_BASE=http://127.0.0.1:8194 [DEFS_SHOTS=/tmp/defs] node tests/definicoes_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.DEFS_BASE || 'http://127.0.0.1:8113';
const shots = process.env.DEFS_SHOTS;
const SECOND = ['Saca bocados', 'Plasma manual', 'Fresadora', 'Prensa'];

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [], writes = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  page.on('dialog', (d) => d.accept());
  await page.route('**/planeamento/api/**', async (route) => {
    const req = route.request();
    if (req.method() === 'GET') return route.fallback();
    writes.push({url: req.url(), body: req.postDataJSON()});
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({changed: 1, repeated: false})});
  });
  // Resposta das Definições: `mode` = 'novo' (acrescenta medido e 2.ª operação se faltarem) ou 'antigo' (sem os campos novos).
  let mode = 'novo', machines = null, thomasSimulated = false;
  await page.route(/\/planeamento\/api\/setor\/definicoes\?/, async (route) => {
    const setor = new URL(route.request().url()).searchParams.get('setor');
    let body;
    try { body = await (await route.fetch()).json(); } catch { return route.abort().catch(() => {}); }  // página fechada a meio
    if (mode === 'antigo') { delete body.planning; delete body.second_operation; body.speed_table.margin_editable = false; }
    else {
      assert.ok(Array.isArray(body.planning), 'API nova: campo planning');
      if (setor === 'cantoneiras' && !(body.second_operation || []).length) {
        // Sem o módulo da 2.ª operação (parte X) a lista ainda as traz: simula o que o servidor fará.
        body.second_operation = body.machines.filter((m) => SECOND.includes(m.name)).map((m) => ({id: m.id, name: m.name, process: m.process}));
        body.machines = body.machines.filter((m) => !SECOND.includes(m.name));
        body.weeks = body.weeks.filter((w) => body.machines.some((m) => m.id === w.machine));
      }
      const [a, b, c] = body.machines;
      if (a && !(a.measured || []).length) {
        a.excel_rate = a.excel_rate || {value: 120, unit: 'm/h', source: 'teste'};
        a.measured = [{operation: '112', value: 85.5, unit: a.excel_rate.unit, hours: 40, sheets: 12, enough: true, ratio_pct: Math.round(85.5 / a.excel_rate.value * 100), plausible: true}];
      }
      if (b && !(b.measured || []).length) b.measured = [{operation: '112', value: 60, unit: 'm/h', hours: 6, sheets: 2, enough: false, ratio_pct: 50, plausible: true}];
      // Como a Thomas (E2-11): sem % e com a nota do × 3; o ecrã diz «sem comparação» e põe a nota no título.
      if (c && !(c.measured || []).length) {
        thomasSimulated = true;
        c.excel_rate = c.excel_rate || {value: 50, unit: 'm/h', source: 'teste'};
        c.measured = [{operation: '112', value: 150, unit: 'm/h', hours: 30, sheets: 9, enough: true, ratio_pct: null, plausible: true,
                       note: 'O × 3 da Thomas (QTD > 50) já está nas horas: este medido não se compara com a taxa base nem deve ir para a eficiência.'}];
      }
    }
    machines = body.machines;
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });

  // MTG3: secção entre Máquinas e Velocidades, uma linha de eficiência por máquina, medido, política, sem margem.
  await page.goto(`${base}/planeamento/setor/definicoes?setor=cantoneiras`);
  await page.waitForSelector('#planning-rows tr', {timeout: 120000});
  const order = await page.locator('main > section h2').allInnerTexts();
  assert.deepEqual(order.slice(0, 3), ['Máquinas', 'Planeamento', 'Velocidades das máquinas']);
  assert.deepEqual(await page.locator('#planning-table thead th').allInnerTexts(), ['Parâmetro', 'Valor', 'Unidade', 'O que muda', 'Origem', 'Medido']);
  assert.equal(await page.locator('#planning-rows tr[data-param="efficiency"]').count(), machines.length, 'uma linha de eficiência por máquina');
  assert.equal(await page.locator('#machines tr').count(), machines.length);
  for (const name of SECOND) assert.ok(!(await page.locator('#machines').innerText()).includes(name), `${name} fora da lista`);
  assert.match(await page.locator('#second-op').innerText(), /^Fora do plano \(2\.ª operação\): .+/);
  for (const name of SECOND) assert.ok((await page.locator('#second-op').innerText()).includes(name), `${name} na linha da 2.ª operação`);
  const measured = await page.locator('#planning-rows tr[data-param="efficiency"] td.measured').allInnerTexts();
  assert.match(measured[0], /^\d+ % \([\d,]+ ÷ [\d,]+ m\/h do Excel, 12 folhas\)$/, `medido: ${measured[0]}`);
  assert.match(measured[1], /^amostra insuficiente \(2 folhas, 6 h\)$/, `medido: ${measured[1]}`);
  if (measured.length > 2 && thomasSimulated) {
    assert.match(measured[2], /^150 m\/h \(9 folhas\) · sem comparação com o Excel$/, `medido: ${measured[2]}`);
    assert.match(await page.locator('#planning-rows tr[data-param="efficiency"] td.measured').nth(2).getAttribute('title'), /× 3 da Thomas/);
  }
  assert.equal(await page.locator('#planning-rows tr[data-param="efficiency"] td.what').count(), 1, '«O que muda» uma vez para a eficiência');
  assert.equal(await page.locator('#planning-rows tr[data-param="efficiency"] td', {hasText: 'Pressuposto'}).count(), 1);
  assert.equal(await page.locator('#planning-rows tr[data-param="deadline_policy"] summary').innerText(), 'Data Corte');
  assert.equal(await page.locator('#planning-rows tr[data-param="posts"]').count(), 0, 'MTG3 sem postos compostos');
  assert.equal(await page.locator('#speed-margin').count(), 0, 'sem o campo Margem');
  assert.equal(await page.locator('#speed-timing-link a').getAttribute('href'), '#planeamento');
  assert.equal(await page.locator('#planning-save').isVisible(), false, 'sem alterações, sem botão');
  assert.equal(await page.locator('#planning-recalc').isVisible(), false);

  // Eficiência fora dos limites: recusada no ecrã, nada enviado.
  const first = page.locator('#planning-rows tr[data-param="efficiency"] input').first();
  const firstId = await first.getAttribute('data-machine');
  await first.fill('250');
  assert.equal(await page.locator('#planning-recalc').innerText(), 'Vai recalcular as horas (2–3 min).');
  let n = writes.length;
  await page.click('#planning-save');
  await page.waitForFunction(() => !document.getElementById('error').hidden);
  assert.match(await page.locator('#error').innerText(), /entre 10 e 200 %/);
  assert.equal(writes.length, n);
  // Eficiência 85,5 % e tempo fixo 0,5 min: uma só gravação «planeamento», com a revisão.
  await first.fill('85,5');
  await page.locator('#planning-rows tr[data-param="piece_minutes"] input').fill('0,5');
  await page.click('#planning-save');
  await page.waitForFunction(() => /Gravado: /.test(document.getElementById('notice').textContent));
  assert.equal(writes.length, n + 1);
  let sent = writes.at(-1).body;
  assert.match(writes.at(-1).url, /\/api\/setor\/definicoes$/);
  assert.equal(sent.tipo, 'planeamento');
  assert.equal(typeof sent.expected_revision, 'number');
  assert.deepEqual(sent.valores, {efficiency: {[firstId]: 85.5}, piece_minutes: 0.5});
  assert.match(await page.locator('#notice').innerText(), /^Gravado: Eficiência e Tempo fixo por peça\. Vai recalcular as horas \(2–3 min\)\.$/);

  // Política de prazo: ativar o Picking, subi-lo e gravar (rota da política).
  await page.waitForSelector('#planning-rows tr[data-param="deadline_policy"] summary');
  await page.locator('#planning-rows tr[data-param="deadline_policy"] summary').click();
  await page.locator('#policy li[data-field="picking"] input[type=checkbox]').check();
  await page.locator('#policy li[data-field="picking"] button[aria-label="Subir Picking"]').click();
  assert.equal(await page.locator('#planning-rows tr[data-param="deadline_policy"] summary').innerText(), 'Picking → Data Corte');
  assert.ok(await page.locator('#policy .policy-hint').isVisible(), 'aviso do recálculo dos prazos');
  n = writes.length;
  await page.click('#policy-save');
  await page.waitForFunction(() => /Prazo gravado/.test(document.getElementById('notice').textContent));
  assert.equal(writes.length, n + 1);
  sent = writes.at(-1).body;
  assert.match(writes.at(-1).url, /\/api\/setor\/prioridades\/politica$/);
  assert.deepEqual([sent.setor, sent.expected_revision, sent.definition.principal, sent.definition.following],
    ['cantoneiras', 0, ['picking', 'cut_date'], ['galvanizing']]);
  if (shots) await page.screenshot({path: `${shots}/definicoes-planeamento.png`, fullPage: true});

  // MTG2: postos (uma só capacidade) e a política por defeito.
  await page.goto(`${base}/planeamento/setor/definicoes?setor=perfis`);
  await page.waitForSelector('#planning-rows tr', {timeout: 120000});
  assert.equal(await page.locator('#planning-rows tr[data-param="deadline_policy"] summary').innerText(), 'Picking → Semana escolhida → Galvanização → Data Corte');
  const posts = await page.locator('#planning-rows tr[data-param="posts"] .post').allInnerTexts();
  assert.ok(posts.some((t) => /^Serrote Fita pav\.1 \(posto\) = Serrote Fita pav\.1 \+ .+: uma só capacidade$/.test(t)), `postos: ${posts}`);
  assert.equal(await page.locator('#second-op').isVisible(), false, 'MTG2 sem 2.ª operação');

  // 390 px: a página não desliza na horizontal; a tabela desliza dentro da caixa.
  await page.setViewportSize({width: 390, height: 900});
  for (const setor of ['cantoneiras', 'perfis']) {
    await page.goto(`${base}/planeamento/setor/definicoes?setor=${setor}`);
    await page.waitForSelector('#planning-rows tr', {timeout: 120000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `sem scroll horizontal a 390 px (${setor})`);
    assert.equal(await page.locator('#planning-table thead').evaluate((x) => getComputedStyle(x).display), 'table-header-group', 'cabeçalho visível a 390 px');
    if (shots) await page.screenshot({path: `${shots}/definicoes-planeamento-390-${setor}.png`, fullPage: true});
  }
  await page.setViewportSize({width: 1440, height: 1000});

  // Serviço ainda com o Python antigo: sem secção nova, o tempo fixo continua nas Velocidades (sem margem).
  mode = 'antigo';
  await page.goto(`${base}/planeamento/setor/definicoes?setor=cantoneiras`);
  await page.waitForSelector('#machines tr', {timeout: 120000});
  await page.waitForSelector('#speed-fixed', {timeout: 60000});
  assert.equal(await page.locator('#planeamento').isVisible(), false);
  assert.equal(await page.locator('#second-op').isVisible(), false);
  assert.equal(await page.locator('#speed-margin').count(), 0);
  n = writes.length;
  await page.fill('#speed-fixed', '1');
  await page.click('#speed-timing-save');
  await page.waitForFunction(() => /Tempo fixo 1 min/.test(document.getElementById('notice').textContent));
  sent = writes.at(-1).body;
  assert.deepEqual([sent.tipo, sent.piece_minutes, 'margin_pct' in sent], ['tempos', 1, false]);

  assert.deepEqual(errors.filter((e) => !/worked_hours/.test(e)), []);
  console.log(`definicoes_browser: OK · ${machines.length} máquinas · ${writes.length} gravações intercetadas`);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
