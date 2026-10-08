// Gantt técnico: as 4 máquinas da 2.ª operação das cantoneiras (fora do plano) não aparecem no filtro de máquinas,
// nem com uma área nem com «ambas» (E2-01, 08/10/2026). Corre com a Python nova (a lista vem em `second_operation`)
// e com a antiga simulada (as 4 ainda em `machines`, reconhecidas pelo processo). Nada é gravado.
// Uso: GANTT_BASE=http://127.0.0.1:8113 node tests/gantt_areas_browser.cjs
const {chromium} = require('./playwright_core.cjs');
const assert = require('node:assert/strict');
const base = process.env.GANTT_BASE || 'http://127.0.0.1:8113';
const SECOND = ['Saca bocados', 'Plasma manual', 'Fresadora', 'Prensa'];
const READY = '#operations .operation-row, #operations details, #operations .operations-empty';

(async () => {
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  try {
    for (const mode of ['novo', 'antigo']) {
      const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
      const errors = [], writes = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.route('**/planeamento/api/**', async (route) => {
        if (route.request().method() !== 'GET') { writes.push(route.request().url()); return route.abort(); }
        return route.fallback();
      });
      let fromNew = 0;
      await page.route(/\/planeamento\/api\/setor\/definicoes\?/, async (route) => {
        const body = await (await route.fetch()).json();
        fromNew += (body.second_operation || []).length;
        if (mode === 'antigo' && Array.isArray(body.second_operation)) {
          body.machines = [...(body.machines || []), ...body.second_operation];
          delete body.second_operation;
        }
        return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      });
      await page.goto(`${base}/planeamento/gantt/detalhe`);
      await page.waitForSelector(READY, {timeout: 400000});
      const counts = {};
      for (const areas of ['both', 'cantoneiras', 'both']) {
        if (await page.inputValue('#areas') !== areas) {
          // A lista de máquinas refaz-se quando chega a resposta das operações da área escolhida.
          const loaded = page.waitForResponse((r) => /\/api\/raw\/gantt\/operations\?/.test(r.url())
            && (areas === 'both' ? !/[?&]area=/.test(r.url()) : r.url().includes(`area=${areas}`)), {timeout: 400000});
          await page.selectOption('#areas', areas);
          await loaded;
          await page.waitForTimeout(1500);
        }
        await page.waitForFunction(() => document.querySelectorAll('#source-machine-filter option').length > 1, null, {timeout: 400000});
        const options = await page.locator('#source-machine-filter option').allTextContents();
        for (const name of SECOND) assert.ok(!options.includes(name), `${mode}/${areas}: ${name} no filtro de máquinas`);
        counts[areas] = options.length - 1;
        console.log(`${mode} · ${areas}: ${options.length - 1} máquinas, sem as 4 da 2.ª operação`);
      }
      assert.ok(counts.cantoneiras < counts.both, `${mode}: só cantoneiras devia ter menos máquinas do que ambas`);
      if (mode === 'novo') assert.ok(fromNew > 0, 'a API das Definições não trouxe second_operation (Python antiga?)');
      assert.deepEqual(writes, [], 'nada é gravado');
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('OK · gantt_areas_browser');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
