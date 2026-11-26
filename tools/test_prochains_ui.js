// Essai Playwright (390 x 844, tactile) de la section « Prochains matchs » (accueil et onglets de compétition).
// Usage : node tools/test_prochains_ui.js http://localhost:8791 /tmp/caps [dossier-donnees-relatif-ou-url-championnats]
// Le serveur sert index.html + soirees/ + clubs/ + data.json + donnees/ (internationales). Les championnats viennent de ?donnees= (Pages réelles par défaut).
// Contrôles : section sous « Derniers résultats » (accueil), France d'abord, 10 lignes au plus puis « Voir plus », clic, section sous le classement
// (?c=ucl, ?c=fl1, ?c=ci), absente sur un tour futur, 0 erreur console (hors 404), 0 débordement horizontal.
const { chromium, devices } = require('playwright');

(async () => {
  const base = process.argv[2] || 'http://localhost:8791';
  const out = process.argv[3] || '/tmp/caps';
  const donnees = process.argv[4] || 'https://camelbaggy.github.io/donnees-football/';
  require('fs').mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'], viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const erreurs = [];
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) erreurs.push(m.text()); });
  page.on('pageerror', e => erreurs.push(String(e)));
  let echecs = 0;
  const ok = (cond, msg) => { console.log((cond ? '[OK] ' : '[ÉCHEC] ') + msg); if (!cond) echecs++; };
  const debord = async () => page.evaluate(() => document.documentElement.scrollWidth - 390);
  const q = `donnees=${encodeURIComponent(donnees)}`;
  const aller = async (qs, sel) => { await page.goto(`${base}/?${qs}${qs ? '&' : ''}${q}`); await page.waitForSelector(sel, { timeout: 25000 }); await page.waitForTimeout(800); };
  const lignes = (sel) => page.$$eval(`${sel} .acc-m.pm`, e => e.map(x => ({ hidden: !x.offsetParent, t: x.textContent.replace(/\s+/g, ' ').trim(), fr: !!x.querySelector('.is-fr'), tour: x.dataset.tour, k: x.dataset.k })));

  // 1. Accueil : section sous « Derniers résultats », avant les tuiles
  await aller('', '#accueil .pm-liste');
  const titres = await page.$$eval('#accueil h2.acc-h', e => e.map(x => x.firstChild.textContent.trim()));
  const iR = titres.indexOf('Derniers résultats'), iP = titres.indexOf('Prochains matchs'), iC = titres.length;
  ok(iP >= 0 && (iR < 0 || iR < iP) && iP < iC, 'accueil : Prochains matchs après Derniers résultats et dernière section : ' + titres.join(' | '));
  const jour = await page.$eval('#accueil .pm-liste', e => e.previousElementSibling.textContent);
  ok(/^(Aujourd'hui, )?\p{L}+/u.test(jour) && !/\d{4}/.test(jour), 'accueil : jour en toutes lettres : ' + jour);
  const L = await lignes('#accueil');
  const visibles = L.filter(l => !l.hidden);
  ok(visibles.length > 0 && visibles.length <= 10, `accueil : ${visibles.length} ligne(s) visible(s) (10 max), ${L.length} au total`);
  const iNonFr = L.findIndex(l => !l.fr);
  ok(iNonFr < 0 || L.slice(iNonFr).every(l => !l.fr || /^(fl1|pl|liga|sa|bl|fl2)$/.test(l.k)), 'accueil : équipes françaises d\'abord (hors surlignage de championnat)');
  if (L.length > 10) {
    const btn = await page.$('#accueil .pm-plus');
    ok(btn && await btn.getAttribute('aria-expanded') === 'false' && /Voir plus \(\d+\)/.test(await btn.textContent()), 'accueil : bouton Voir plus (' + (btn && await btn.textContent()) + ')');
    await btn.scrollIntoViewIfNeeded(); await btn.click();
    ok(await btn.getAttribute('aria-expanded') === 'true' && (await lignes('#accueil')).every(l => !l.hidden) && /Voir moins/.test(await btn.textContent()), 'accueil : Voir plus déroule tout');
    await btn.click();
    ok((await lignes('#accueil')).filter(l => !l.hidden).length === 10, 'accueil : Voir moins replie à 10');
  } else ok(!(await page.$('#accueil .pm-plus')), 'accueil : pas de bouton sous 11 matchs');
  ok(await debord() <= 0, 'accueil : pas de débordement horizontal');
  await page.evaluate(() => document.querySelector('#accueil .pm-liste').scrollIntoView());
  await page.screenshot({ path: `${out}/p01-accueil.png` });
  // clic
  const l0 = visibles[0];
  await page.click('#accueil .acc-m.pm');
  await page.waitForSelector('#comp-view:not([hidden])', { timeout: 20000 });
  await page.waitForTimeout(800);
  ok(new URL(page.url()).searchParams.get('c') === l0.k, 'accueil : clic -> ?c=' + l0.k + ' tour=' + new URL(page.url()).searchParams.get('tour'));

  // 2. Onglet de coupe : sous le classement
  await aller('c=ucl', '#comp-view:not([hidden]) #standings-container table');
  const ordreDom = await page.evaluate(() => { const s = document.getElementById('standings-section'), n = document.getElementById('next-section'); return { hid: n.hidden, apres: !!(s.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING) }; });
  ok(!ordreDom.hid && ordreDom.apres, 'ucl : Prochains matchs sous le classement');
  const Lc = await lignes('#next-container');
  ok(Lc.length > 0 && Lc.filter(l => !l.hidden).length <= 10, `ucl : ${Lc.length} match(s), au plus 10 visibles`);
  ok(Lc.every(l => l.k === 'ucl'), 'ucl : uniquement la compétition');
  ok(await debord() <= 0, 'ucl : pas de débordement horizontal');
  await page.evaluate(() => document.getElementById('next-section').scrollIntoView());
  await page.screenshot({ path: `${out}/p02-coupe.png` });
  // absente sur un tour futur
  const futur = await page.evaluate(() => (toursByComp.ucl || []).find(t => t.futur));
  if (futur) {
    await aller('c=ucl&tour=' + futur.id, '#comp-view:not([hidden]) #prog-section:not([hidden])');
    ok(await page.$eval('#next-section', e => e.hidden), 'ucl : tour futur (' + futur.id + ') : pas de Prochains matchs (le Programme y est)');
  } else ok(false, 'ucl : aucun tour futur pour tester');

  // 3. Championnat (vraies données)
  await aller('c=fl1', '#comp-view:not([hidden]) #standings-container table');
  const sec = await page.$eval('#next-section', e => e.hidden);
  const Lf = await lignes('#next-container');
  ok(!sec && Lf.length > 0, 'fl1 : section présente (' + Lf.length + ' match(s))');
  ok(await page.$$eval('#next-container .is-fr', e => e.length) === 0, 'fl1 : pas de surlignage français en championnat');
  ok(await debord() <= 0, 'fl1 : pas de débordement horizontal');
  await page.evaluate(() => document.getElementById('next-section').scrollIntoView());
  await page.screenshot({ path: `${out}/p03-championnat.png` });
  if (Lf[0] && Lf[0].tour) {
    await page.click('#next-container .acc-m.pm');
    await page.waitForTimeout(1200);
    ok(new URL(page.url()).searchParams.get('tour') === Lf[0].tour, 'fl1 : clic -> tour ' + Lf[0].tour);
  }
  // vue Saisons passées : rien
  await aller('c=fl1&vue=histo', '#comp-view.histo');
  ok(!(await page.isVisible('#next-section')), 'fl1 : Saisons passées sans Prochains matchs');

  // 4. International : Coupe intercontinentale (finale PSG à venir)
  await aller('c=ci', '#comp-view:not([hidden])');
  const Li = await lignes('#next-container');
  ok(Li.length > 0, 'ci : ' + Li.length + ' match(s) à venir : ' + (Li[0] || {}).t);
  ok(await debord() <= 0, 'ci : pas de débordement horizontal');
  await page.evaluate(() => document.getElementById('next-section').scrollIntoView());
  await page.screenshot({ path: `${out}/p04-international.png` });

  ok(erreurs.length === 0, '0 erreur console ' + erreurs.join(' | '));
  await browser.close();
  console.log(echecs ? `${echecs} ÉCHEC(S)` : 'TOUT EST VERT');
  process.exit(echecs ? 1 : 0);
})();
