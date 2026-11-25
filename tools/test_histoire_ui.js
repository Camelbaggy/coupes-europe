// Test Playwright 390 x 844 tactile de l'onglet « Histoire » de la fiche de club (clubs/historique/<id>.json).
// Usage : python -m http.server 8765 &, puis node tools/test_histoire_ui.js http://localhost:8765 <dossier de captures>
const { chromium } = require(process.env.PLAYWRIGHT_PATH || '/opt/node-tools/node_modules/playwright');
const OUT = process.argv[3] || '/tmp/histo';
const BASE = process.argv[2] || 'http://localhost:8765';
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
  await page.goto(BASE + '/index.html?c=ucl', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof openClub === 'function' && clubIndex && clubIndex.size > 0);

  // Débordement horizontal : page, feuille et tout élément du corps de la fiche
  const debord = () => page.evaluate(() => {
    const vw = document.documentElement.clientWidth, body = document.getElementById('club-body');
    const bad = [];
    body.querySelectorAll('*').forEach(el => { const r = el.getBoundingClientRect(); if (r.width && r.right > vw + 1 && !el.closest('summary')) bad.push(el.className + ' ' + Math.round(r.right)); });
    return { page: document.documentElement.scrollWidth - vw, corps: body.scrollWidth - body.clientWidth, bad: bad.slice(0, 5) };
  });

  const clubs = [['50051', 'real-madrid'], ['52277', 'lens'], ['52748', 'marseille'], ['88148', 'petit-club-egnatia'], ['7889', 'liverpool']];
  for (const [id, nom] of clubs) {
    await page.evaluate((i) => openClub(i, 'histoire'), id);
    await page.waitForSelector('#club-body .hi-sum', { timeout: 8000 });
    const d = await debord();
    ok(d.page <= 0 && d.corps <= 0 && d.bad.length === 0, `${nom} : aucun débordement horizontal ${JSON.stringify(d)}`);
    await page.screenshot({ path: `${OUT}/${nom}-1-haut.png` });
    // faire défiler jusqu'aux saisons, ouvrir la 1re édition de la décennie ouverte
    await page.evaluate(() => { const b = document.getElementById('club-body'); b.scrollTop = b.scrollHeight; });
    await sleep(200);
    const premiere = await page.$('details.hi-dec[open] details.hi-ed > summary');
    if (premiere) {
      await premiere.tap();
      await page.waitForSelector('details.hi-dec[open] details.hi-ed[open] .hi-m', { timeout: 4000 });
      const d2 = await debord();
      ok(d2.page <= 0 && d2.corps <= 0 && d2.bad.length === 0, `${nom} : édition ouverte sans débordement ${JSON.stringify(d2)}`);
    }
    await page.screenshot({ path: `${OUT}/${nom}-2-saisons.png` });
    await page.evaluate(() => closeClub());
    await sleep(150);
  }

  // Real Madrid : palmarès (15 titres en C1), toutes les finales, décennie plus ancienne, info-bulle
  await page.evaluate(() => openClub('50051', 'histoire'));
  await page.waitForSelector('#club-body .hi-pal');
  const pal = await page.evaluate(() => [...document.querySelectorAll('#club-body .hi-pal')].map(e => e.querySelector('.n').textContent + ' ' + e.querySelector('.t').textContent));
  ok(pal.some(t => t.startsWith('15 ')), 'Real Madrid : 15 titres de Ligue des champions (' + pal.join(' | ') + ')');
  await page.tap('details.hi-fins > summary');
  await sleep(150);
  const nbFin = await page.evaluate(() => document.querySelectorAll('.hi-fin').length);
  ok(nbFin === 18 + 2 + 2 + 9 + 5, 'Real Madrid : 36 finales listées (C1 18, C2 2, C3 2, SE 9, IC 5) : ' + nbFin);
  await page.evaluate(() => { document.querySelector('details.hi-fins').scrollIntoView(); });
  await sleep(150);
  await page.screenshot({ path: `${OUT}/real-madrid-3a-finales.png` });
  await page.evaluate(() => { document.getElementById('club-body').scrollTop = 0; });
  await page.tap('#club-body .hi-pal .t');   // toucher une ligne du palmarès ne plante pas
  await page.tap('#club-body h4 .info-btn');
  await sleep(150);
  ok(await page.evaluate(() => document.getElementById('info-pop').classList.contains('open')), 'info-bulle du palmarès ouverte');
  await page.screenshot({ path: `${OUT}/real-madrid-3-finales-info.png` });
  await page.tap('#club-body h4 .info-btn');
  // décennie ancienne : 1950-1959 (sous la première), puis une édition
  await page.evaluate(() => { const ds = [...document.querySelectorAll('details.hi-dec')]; ds[ds.length - 1].open = true; ds[ds.length - 1].scrollIntoView(); });
  await sleep(200);
  await page.tap('details.hi-dec:last-of-type > details.hi-ed > summary');
  await sleep(200);
  await page.screenshot({ path: `${OUT}/real-madrid-4-annees-1950.png` });

  // Glissement entre onglets : Effectif -> Histoire (vers la gauche) puis retour (vers la droite)
  await page.evaluate(() => openClub('7889', 'histoire'));
  await page.waitForSelector('#club-body .hi-pal');
  await page.tap('details.hi-fins > summary');
  const fl = await page.evaluate(() => [...document.querySelectorAll('.hi-fin')].map(e => e.innerText.replace(/\s+/g, ' ')));
  ok(fl.some(t => /1972-73/.test(t) && /cumul 3-2 \(3-0 puis 0-2\)/.test(t)), 'Liverpool : finale 1973 en deux manches, cumul 3-2');
  ok(fl.some(t => /2004-05/.test(t) && /3-3 a\.p\. \(tab 3-2\)/.test(t) || /2004-05/.test(t) && /tab/.test(t)), 'Liverpool : finale 2005 aux tirs au but');
  await page.evaluate(() => { document.querySelector('details.hi-fins').scrollIntoView(); });
  await sleep(150);
  await page.screenshot({ path: `${OUT}/liverpool-3-finales.png` });
  await page.evaluate(() => closeClub());
  // Glissements simulés par de vrais TouchEvent dans la page (un glissement CDP vers la droite déclencherait le retour arrière du navigateur
  // headless, indépendamment de la page : constaté aussi sur l'onglet Stats)
  async function glisser(x0, x1, y) {
    await page.evaluate(async ([x0, x1, y]) => {
      const el = document.elementFromPoint(x0, y) || document.getElementById('club-body');
      const t = (x, yy) => new Touch({ identifier: 1, target: el, clientX: x, clientY: yy, pageX: x, pageY: yy });
      const ev = (type, x, yy, fin) => el.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true, touches: fin ? [] : [t(x, yy)], changedTouches: [t(x, yy)], targetTouches: fin ? [] : [t(x, yy)] }));
      ev('touchstart', x0, y);
      for (let i = 1; i <= 6; i++) { ev('touchmove', x0 + (x1 - x0) * i / 6, y); await new Promise(r => setTimeout(r, 16)); }
      ev('touchend', x1, y, true);
    }, [x0, x1, y]);
    await sleep(350);
  }
  await page.evaluate(() => openClub('52748'));     // OM, Aperçu
  await page.waitForSelector('#club-body .cl-sec');
  await page.evaluate(() => switchClubView('effectif'));
  await sleep(200);
  await glisser(330, 90, 500);
  ok(await page.evaluate(() => currentClubView) === 'histoire', 'glissement vers la gauche depuis Effectif : onglet Histoire');
  await page.waitForSelector('#club-body .hi-sum');
  await glisser(330, 90, 500);
  ok(await page.evaluate(() => currentClubView) === 'histoire', 'pas de boucle à l\'extrémité droite (Histoire reste)');
  await glisser(90, 330, 500);
  ok(await page.evaluate(() => currentClubView) === 'effectif', 'glissement vers la droite : retour à Effectif');
  // glissement vertical : le défilement n'est pas gêné et ne change pas d'onglet
  await page.evaluate(() => switchClubView('histoire'));
  await page.waitForSelector('#club-body .hi-sum');
  await glisser(200, 215, 650);
  await glisser(200, 190, 300);
  ok(await page.evaluate(() => currentClubView) === 'histoire', 'petit geste quasi vertical : onglet inchangé');
  await page.screenshot({ path: `${OUT}/marseille-glissement.png` });
  // barre d'onglets à 5 entrées
  const tabs = await page.evaluate(() => [...document.querySelectorAll('#club-tabs .subtab-btn')].map(b => { const r = b.getBoundingClientRect(); return [b.textContent.trim(), Math.round(r.width), b.scrollWidth <= b.clientWidth]; }));
  ok(tabs.length === 5 && tabs.every(t => t[2]), 'cinq onglets lisibles sans coupure : ' + JSON.stringify(tabs));
  // club sans historique (fichier absent) : message, pas d'erreur
  await page.route('**/clubs/historique/52277.json*', r => r.fulfill({ status: 404, body: '' }));
  await page.evaluate(() => { histoCache.delete('52277'); openClub('52277', 'histoire'); });
  await page.waitForSelector('#club-body .empty-state');
  ok((await page.textContent('#club-body')).includes('pas encore disponible'), 'historique absent : message clair');
  await page.screenshot({ path: `${OUT}/lens-historique-absent.png` });

  ok(errs.length === 0, 'aucune erreur console : ' + JSON.stringify(errs));
  await browser.close();
  console.log(echecs ? `${echecs} ECHEC(S)` : 'TOUT EST OK');
  process.exit(echecs ? 1 : 0);
})();
