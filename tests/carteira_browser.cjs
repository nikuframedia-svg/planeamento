// Read-only acceptance of the Carteira page (plano de 28/09/2026). No production edits.
// Uso: CARTEIRA_BASE=http://127.0.0.1:8113 CARTEIRA_SHOT=/tmp/carteira.png node tests/carteira_browser.cjs
const {chromium} = require('/home/luis/.npm/_npx/fd3bca3c548369c0/node_modules/playwright-core');
const assert = require('node:assert/strict');
const base = process.env.CARTEIRA_BASE || 'http://127.0.0.1:8113';
const shot = process.env.CARTEIRA_SHOT;

(async () => {
  const browser = await chromium.launch({executablePath: '/home/luis/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome', headless: true, args: ['--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('requestfailed', (r) => errors.push(`${r.url()} ${r.failure()?.errorText}`));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  try {
    await page.goto(`${base}/planeamento/carteira`);
    await page.waitForSelector('#rows tr', {timeout: 60000});
    assert.equal(await page.textContent('#level-title'), 'Referência mestre');
    assert.ok((await page.locator('#totals .card').count()) >= 5, 'faltam os totais');
    const first = page.locator('#rows tr').first();
    await first.locator('.toggle').click();
    await page.waitForSelector('#rows tr.level-1', {timeout: 30000});
    assert.equal(await first.locator('.toggle').getAttribute('aria-expanded'), 'true');
    assert.ok(await first.locator('.act-plan').count() === 1, 'falta o botão Planear');
    assert.ok((await page.locator('#rows .state-proposta').count()) > 0, 'falta o estado Proposta');
    assert.ok((await page.locator('#totals .card').count()) >= 8, 'faltam os totais de decisão');
    if (shot) await page.screenshot({path: shot, fullPage: false});
    await page.selectOption('#vista', 'of');
    await page.waitForFunction(() => document.getElementById('level-title').textContent === 'Obra / OV', null, {timeout: 30000});
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/planeamento/api/carteira?') && r.url().includes('sinal=prioridade')),
      page.selectOption('#sinal', 'prioridade'),
    ]);
    await page.waitForFunction(() => {
      const rows = [...document.querySelectorAll('#rows tr')];
      return rows.length > 0 && rows.every((tr) => tr.querySelector('.badge-priority'));
    }, null, {timeout: 30000});
    assert.deepEqual(errors, []);
    console.log('Carteira OK:', await page.locator('#rows tr').count(), 'obras (OV) com prioridade escrita');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
