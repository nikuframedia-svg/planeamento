// Cenários (Etapa 5, 08/10/2026): a vista «Cenários» da Carga desenhada por window.cenariosView (cenarios.js).
// Criar, acrescentar alterações, comparar (primeiro «a calcular», depois o resultado), Aplicar com a confirmação
// das mudanças reais (POST intercetado: nada vai à base), Desfazer, 390 px sem deslizar a página e a resposta da
// Python antiga (404 → «precisa que o serviço seja reiniciado»). Todas as respostas da API são sintéticas.
// Uso: SETOR_BASE=http://127.0.0.1:<porta> node tests/cenarios_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.SETOR_BASE || 'http://127.0.0.1:8113';

const json = (route, body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
const SID = '11111111-2222-4333-8444-555555555555';
const M = [{id: 'm1', name: 'Peddi 8', default_shifts: 1}, {id: 'm2', name: 'Ficep XP T4', default_shifts: 2}];
const KINDS = {cancelar: 'Cancelar', maquina_parada: 'Máquina parada', turnos: 'Turnos', pessoas_em_falta: 'Pessoas em falta', urgente: 'Urgente', prazo: 'Prazo'};

function world() {
  const s = {scenarios: [], posts: [], compareCalls: 0};
  s.list = () => ({sector: 'cantoneiras', installed: true, machines: M, shifts: 3, people_defined: false, kinds: KINDS,
    suggested_text: 'As máquinas sugeridas ficam as de agora; a atribuição das causas segue a ordem das alterações.', scenarios: s.scenarios});
  return s;
}

const DIFF = {pending: false, revision: 3, counters: {late_new: 2, late_gone: 1, over_capacity_before: 7, over_capacity_after: 7,
  people_short_before: null, people_short_after: null, cancelled: 0},
  suggested_text: 'As máquinas sugeridas ficam as de agora; a atribuição das causas segue a ordem das alterações.',
  orders: [{of: 'OF264095', customer: 'PAINHAS, SA', due_day: '2026-10-13', before: '2026-10-13T05:33:00+00:00', after: '2026-10-15T09:10:00+00:00',
    state_before: 'em_risco', state_after: 'atrasa', delta_days: 2, cancelled: false, why: 'Peddi 8 parada de 12/10 06:00 a 14/10 06:00 (alteração 1)'}],
  orders_total: 1, machines: [{id: 'm1', name: 'Peddi 8', queue_end_before: '2027-03-01T10:00:00+00:00', queue_end_after: '2027-03-03T10:00:00+00:00',
    recovery_before: null, recovery_after: null, recovers_before: false, recovers_after: false, overloaded_before: true, overloaded_after: true,
    late_hours_before: 400, late_hours_after: 415}],
  weeks: [{id: 'm1', name: 'Peddi 8', year: 2026, week: 42, load_before: 37.5, load_after: 22.5, capacity_before: 37.5, capacity_after: 22.5}],
  people: [], people_defined: false, stops: [], late_new: ['OF264095', 'OF2'], late_gone: ['OF3']};

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const errors = [];
  async function open(s, width = 1280, {old = false} = {}) {
    const page = await browser.newPage({viewport: {width, height: 900}});
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
    await page.route('**/planeamento/api/**', (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/planeamento/api/setor/cenarios')) return route.abort();  // o resto da Carga não interessa aqui
      if (old) return json(route, {detail: 'Not Found'}, 404);
      if (route.request().method() === 'POST') {
        const p = JSON.parse(route.request().postData());
        s.posts.push(p);
        assert.match(p.request_id, /^[0-9a-f-]{36}$/);
        return json(route, s.onPost(p));
      }
      if (url.pathname.endsWith('/comparacao')) {
        s.compareCalls += 1;
        return json(route, s.compare());
      }
      return json(route, s.list());
    });
    await page.goto(`${base}/planeamento/setor/carga`);
    await page.waitForFunction(() => typeof window.cenariosView === 'function');
    await page.evaluate(() => {
      const box = document.createElement('div');
      box.id = 'cen-test';
      document.querySelector('main').replaceChildren(box);
      window.cenariosView(box, {setor: 'cantoneiras'});
    });
    return page;
  }

  // --- criar, alterar, comparar, aplicar, desfazer
  {
    const s = world();
    let revision = 1;
    const scenario = () => s.scenarios[0];
    s.compare = () => (s.compareCalls === 1 ? {pending: true, revision, previous: null} : {...DIFF, revision});
    s.onPost = (p) => {
      if (p.acao === 'criar') {
        assert.equal(p.nome, 'Avaria da Peddi');
        s.scenarios = [{id: SID, name: p.nome, status: 'aberto', revision: 1, created_by: 'luis', created_at: '2026-10-08T10:00:00+00:00', changes: [], applied: []}];
        return {id: SID, revision: 1, repeated: false};
      }
      if (p.acao === 'alterar') {
        assert.equal(p.expected_revision, revision);
        revision += 1;
        const label = p.tipo === 'maquina_parada' ? 'Peddi 8 parada de 12/10 06:00 a 14/10 06:00' : 'Faltam 2 pessoas no 1.º turno de 12/10';
        const apply = p.tipo === 'maquina_parada' ? `Calendário: reserva horária — ${label}` : `Não se grava (só simulação): ${label}`;
        scenario().changes.push({id: `c${revision}`, kind: p.tipo, target: p.alvo, params: p.parametros, label, kind_text: KINDS[p.tipo], apply_text: apply, position: revision - 1});
        scenario().revision = revision;
        return {id: SID, revision, change: {id: `c${revision}`, label}};
      }
      if (p.acao === 'aplicar') {
        assert.equal(p.expected_revision, revision);
        revision += 1;
        Object.assign(scenario(), {status: 'aplicado', revision, applied_by: 'luis', applied_at: '2026-10-08T11:00:00+00:00'});
        s.compare = () => ({pending: false, applied: true, revision, simulated: true, stale: false, differences_total: 0, differences: [],
          items: [{change_id: 'c2', kind: 'maquina_parada', label: 'Peddi 8 parada de 12/10 06:00 a 14/10 06:00', written: '1 semana(s) do calendário', undone_at: null},
            {change_id: 'c3', kind: 'pessoas_em_falta', label: 'Faltam 2 pessoas no 1.º turno de 12/10', written: 'Não se grava (só simulação)', simulation_only: true}]});
        return {id: SID, revision, status: 'aplicado', applied: [{change_id: 'c2', label: 'Peddi 8 parada de 12/10 06:00 a 14/10 06:00', written: '1 semana(s) do calendário'}]};
      }
      if (p.acao === 'desfazer_aplicada') {
        assert.equal(p.alteracao, 'c2');
        revision += 1;
        scenario().revision = revision;
        const old = s.compare;
        s.compare = () => { const c = old(); c.items[0] = {...c.items[0], undone_at: '2026-10-08T12:00:00+00:00', undone_by: 'luis', undo_note: '1 semana(s) repostas'}; return c; };
        return {id: SID, revision, undone: 'c2', note: '1 semana(s) repostas'};
      }
      throw new Error(`ação inesperada ${p.acao}`);
    };
    const page = await open(s);
    await page.waitForSelector('.cen-banner');
    assert.equal((await page.textContent('.cen-banner')).trim(), 'Simulação: nada muda no plano em uso até Aplicar.');
    assert.match(await page.textContent('.cen-list'), /Ainda não há cenários/);
    await page.click('.cen-add-btn');
    await page.fill('.cen-new input', 'Avaria da Peddi');
    await page.click('.cen-new button[type=submit]');
    await page.waitForFunction(() => document.querySelector('.cen-body h2')?.textContent.includes('Avaria da Peddi'));
    assert.match(await page.textContent('.cen-body'), /Sem alterações: o cenário é igual ao plano em uso/);

    // Máquina parada (formulário mínimo do tipo)
    await page.selectOption('.cen-add select[name=tipo]', 'maquina_parada');
    await page.selectOption('.cen-add select[name=maquina]', 'm1');
    await page.fill('.cen-add input[name=de]', '2026-10-12T06:00');
    await page.fill('.cen-add input[name=ate]', '2026-10-14T06:00');
    await page.click('.cen-add button[type=submit]');
    await page.waitForFunction(() => document.querySelectorAll('.cen-changes li').length === 1);
    const stop = s.posts.find((p) => p.acao === 'alterar');
    assert.deepEqual([stop.tipo, stop.alvo, stop.parametros], ['maquina_parada', {maquina: 'm1'}, {de: '2026-10-12T06:00', ate: '2026-10-14T06:00'}]);
    // Pessoas em falta
    await page.selectOption('.cen-add select[name=tipo]', 'pessoas_em_falta');
    await page.fill('.cen-add input[name=dia]', '2026-10-12');
    await page.fill('.cen-add input[name=n]', '2');
    await page.click('.cen-add button[type=submit]');
    await page.waitForFunction(() => document.querySelectorAll('.cen-changes li').length === 2);
    assert.deepEqual(s.posts.at(-1).parametros, {dia: '2026-10-12', turno: 1, n: 2});
    assert.equal(await page.getAttribute('.cen-changes li:first-child .cen-x', 'aria-label'), 'Retirar: Peddi 8 parada de 12/10 06:00 a 14/10 06:00');

    // Comparação: «a calcular» e depois o resultado (o ecrã volta a pedir sozinho)
    await page.waitForFunction(() => document.querySelector('.cen-counters'), null, {timeout: 15000});
    const counters = await page.$$eval('.cen-count', (xs) => xs.map((x) => x.textContent));
    assert.deepEqual(counters, ['Passam a atrasar2', 'Deixam de atrasar1', 'Máquinas acima da capacidade7', 'Turnos com falta de pessoas—']);
    const row = await page.$$eval('.cen-table tbody tr:first-child td', (tds) => tds.map((t) => t.textContent));
    assert.equal(row[0], 'OF264095');
    assert.match(row[3], /^13\/10 06:33 → 15\/10 10:10atrasa$/);
    assert.equal(row[4], '+2');
    assert.equal(row[5], 'Peddi 8 parada de 12/10 06:00 a 14/10 06:00 (alteração 1)');
    assert.match(await page.textContent('.cen-compare'), /2026-S42.*37,5 → 22,5/s);
    assert.match(await page.textContent('.cen-compare'), /As máquinas sugeridas ficam as de agora/);
    assert.equal(await page.getAttribute('.cen-actions a', 'href'), `/planeamento/setor/carga?setor=cantoneiras&vista=calendario&cenario=${SID}`);

    // Aplicar: primeiro a confirmação com as mudanças reais; só depois o POST
    const before = s.posts.length;
    await page.click('.cen-actions button.primary');
    const confirm = await page.textContent('.cen-confirm');
    assert.match(confirm, /Calendário: reserva horária — Peddi 8 parada/);
    assert.match(confirm, /Não se grava \(só simulação\): Faltam 2 pessoas/);
    assert.equal(s.posts.length, before);
    await page.click('.cen-confirm button.primary');
    await page.waitForFunction(() => document.querySelector('.cen-applied'));
    assert.equal(s.posts.at(-1).acao, 'aplicar');
    assert.match(await page.textContent('.cen-msg'), /Aplicado: Peddi 8 parada .* — 1 semana\(s\) do calendário/);
    assert.match(await page.textContent('.cen-body'), /A previsão nova é igual à simulada/);
    const applied = await page.$$eval('.cen-applied li', (xs) => xs.map((x) => x.textContent));
    assert.match(applied[1], /Não se grava \(só simulação\)$/);       // sem Desfazer nas pessoas em falta
    await page.click('.cen-applied li:first-child button');
    await page.waitForFunction(() => document.querySelector('.cen-applied li')?.textContent.includes('desfeita por luis'));
    await page.screenshot({path: '/tmp/claude-1000/cenarios-1280.png', fullPage: true});
    await page.close();
  }

  // --- 390 px: nada desliza para o lado na página; as tabelas deslizam dentro da sua caixa
  {
    const s = world();
    s.scenarios = [{id: SID, name: 'Semana com avaria', status: 'aberto', revision: 3, created_by: 'luis', created_at: '2026-10-08T10:00:00+00:00', applied: [],
      changes: [{id: 'c1', kind: 'maquina_parada', label: 'Peddi 8 parada de 12/10 06:00 a 14/10 06:00', apply_text: 'Calendário: reserva', position: 1}]}];
    s.compare = () => DIFF;
    s.onPost = () => ({});
    const page = await open(s, 390);
    await page.waitForSelector('.cen-counters');
    const over = await page.evaluate(() => {
      const box = document.getElementById('cen-test');
      return {page: document.scrollingElement.scrollWidth - window.innerWidth, right: Math.max(...[...box.querySelectorAll('*')]
        .filter((x) => !x.closest('.cen-wrap')).map((x) => x.getBoundingClientRect().right)) - window.innerWidth};
    });
    assert.ok(over.page <= 1, `a página desliza ${over.page} px a 390 px`);
    assert.ok(over.right <= 1, `um elemento passa ${over.right} px da margem a 390 px`);
    await page.screenshot({path: '/tmp/claude-1000/cenarios-390.png', fullPage: true});
    await page.close();
  }

  // --- Python antiga: 404 sem erro → falta reiniciar
  {
    const s = world();
    const page = await open(s, 1280, {old: true});
    await page.waitForFunction(() => !document.querySelector('.cen-error')?.hidden);
    assert.equal(await page.textContent('.cen-error'), 'Os cenários precisam que o serviço do planeamento seja reiniciado.');
    await page.close();
  }

  await browser.close();
  assert.deepEqual(errors, []);
  console.log('cenarios_browser: ok');
})().catch((e) => { console.error(e); process.exit(1); });
