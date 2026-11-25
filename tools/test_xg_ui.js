// Test Playwright 390 x 844 tactile de l'onglet Stats avec et sans xG (buts attendus, ESPN / Opta).
// Usage : servir un dossier contenant index.html + data.json (soirée AVEC xG), puis
//   node tools/test_xg_ui.js http://localhost:8766 <dossier de captures>
const { chromium } = require(process.env.PLAYWRIGHT_PATH || '/opt/node-tools/node_modules/playwright');
const OUT = process.argv[3] || '/tmp/xg';
const BASE = process.argv[2] || 'http://localhost:8766';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let echecs = 0;
const ok = (c, msg) => { if (!c) { echecs++; console.log('ECHEC : ' + msg); } else console.log('ok : ' + msg); };
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error' && !/flagcdn|img\.uefa|ERR_|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await page.goto(BASE + '/index.html', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof openMatchModal === 'function' && appData && appData.competitions);
  const debord = () => page.evaluate(() => {
    const vw = document.documentElement.clientWidth, body = document.getElementById('modal-body-content');
    const bad = [];
    body.querySelectorAll('*').forEach(el => { const r = el.getBoundingClientRect(); if (r.width && r.right > vw + 1) bad.push(el.className + ' ' + Math.round(r.right)); });
    return { page: document.documentElement.scrollWidth - vw, corps: body.scrollWidth - body.clientWidth, bad: bad.slice(0, 5) };
  });
  const cible = await page.evaluate(() => {
    for (const [k, c] of Object.entries(appData.competitions)) for (const m of c.matches || [])
      if ((m.stats.all || []).some(s => s.key === 'xg')) return { k, id: m.match_id };
    return null;
  });
  ok(!!cible, 'la soirée servie contient un match avec xG');
  // 1) avec xG
  await page.evaluate(({ k, id }) => { openMatchModal(id, appData, k); switchModalView('stats'); }, cible);
  await sleep(300);
  const t = await page.evaluate(() => {
    const b = document.querySelector('.poss.xg');
    return b ? { txt: b.innerText, vals: [...b.querySelectorAll('.poss-v')].map(e => e.textContent), info: !!b.querySelector('[aria-haspopup]') } : null;
  });
  ok(t && t.vals.length === 2 && t.vals.every(v => /^\d+,\d{2}$/.test(v)), 'xG en grand, 2 décimales, virgule française : ' + JSON.stringify(t && t.vals));
  ok(t && t.info, 'infoBtn de définition / source présent dans le bloc xG');
  const ordre = await page.evaluate(() => [...document.querySelectorAll('#modal-body-content .poss-lbl, #modal-body-content .st-sec')].map(e => e.textContent.trim().slice(0, 22)));
  const ix = ordre.findIndex(s => /Buts attendus/.test(s));
  ok(ix >= 0 && (ix === 0 || /Possession/.test(ordre[ix - 1])), 'xG en tête des stats (sous la possession si elle existe) : ' + ordre.slice(0, 4).join(' | '));
  const lignes = await page.evaluate(() => [...document.querySelectorAll('#modal-body-content .st-row')].filter(r => /xG|Passes décisives attendues/.test(r.textContent)).map(r => r.innerText.replace(/\n/g, ' ')));
  ok(lignes.length >= 1 && lignes.every(l => /\d,\d{2}/.test(l)), 'lignes xGOT / xA en 2 décimales : ' + JSON.stringify(lignes));
  let d = await debord();
  ok(d.page <= 0 && d.corps <= 0 && d.bad.length === 0, 'avec xG : aucun débordement horizontal ' + JSON.stringify(d));
  await page.screenshot({ path: `${OUT}/stats-avec-xg.png` });
  await page.evaluate(() => document.querySelector('.poss.xg [aria-haspopup]').click());
  await sleep(200);
  await page.screenshot({ path: `${OUT}/stats-avec-xg-info.png` });
  await page.keyboard.press('Escape');
  // mi-temps : xG masqués
  await page.evaluate(() => switchStatsPeriod('1st'));
  await sleep(200);
  const mt = await page.evaluate(() => ({ xg: !!document.querySelector('.poss.xg'), lignes: [...document.querySelectorAll('.st-row')].filter(r => /xG|attendues/.test(r.textContent)).length }));
  ok(!mt.xg && mt.lignes === 0, 'xG absents sur la 1re mi-temps');
  await page.screenshot({ path: `${OUT}/stats-mi-temps.png` });
  await page.evaluate(() => switchStatsPeriod('all'));
  // 2) sans xG
  await page.evaluate(({ k, id }) => {
    const m = appData.competitions[k].matches.find(x => x.match_id === id);
    m.stats.all = m.stats.all.filter(s => !['xg', 'xgot', 'xg_sans_penalty', 'xa'].includes(s.key));
    delete m.xg_source; delete m.xg_espn_id;
    closeMatchModal(); openMatchModal(id, appData, k); switchModalView('stats');
  }, cible);
  await sleep(300);
  const sans = await page.evaluate(() => ({ bloc: !!document.querySelector('.poss.xg'), poss: !!document.querySelector('.poss'), rows: document.querySelectorAll('.st-row').length }));
  ok(!sans.bloc && sans.poss && sans.rows > 3, 'sans xG : pas de bloc xG, reste de la page intact ' + JSON.stringify(sans));
  d = await debord();
  ok(d.page <= 0 && d.corps <= 0 && d.bad.length === 0, 'sans xG : aucun débordement horizontal ' + JSON.stringify(d));
  await page.screenshot({ path: `${OUT}/stats-sans-xg.png` });
  ok(errs.length === 0, '0 erreur console ' + JSON.stringify(errs));
  await browser.close();
  console.log(echecs ? `${echecs} ECHEC(S)` : 'TOUT OK');
  process.exit(echecs ? 1 : 0);
})();
