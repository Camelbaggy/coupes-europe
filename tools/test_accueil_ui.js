// Essai Playwright (390 x 844, tactile) de l'accueil et des championnats.
// Usage : node tools/test_accueil_ui.js http://localhost:8767 /tmp/caps [dossier-donnees-relatif]
// Le serveur sert index.html + soirees/ + clubs/ + data.json, et un dossier de données de championnats (défaut « donnees/ »,
// passé à la page par ?donnees=). Contrôles : 0 erreur console, 0 débordement horizontal, accueil (derniers résultats,
// 8 tuiles), championnat (onglets, journée, classement, fiche de match : stats Opta, compos, momentum), retour à l'accueil,
// anciens liens des coupes (?c=ucl&tour=…, ?soiree=…).
const { chromium, devices } = require('playwright');

(async () => {
  const base = process.argv[2] || 'http://localhost:8767';
  const out = process.argv[3] || '/tmp/caps';
  const donnees = process.argv[4] || 'donnees/';
  require('fs').mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'], viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const erreurs = [];
  page.on('console', m => { if (m.type() === 'error') erreurs.push(m.text()); });
  page.on('pageerror', e => erreurs.push(String(e)));
  let echecs = 0;
  const ok = (cond, msg) => { console.log((cond ? '[OK] ' : '[ÉCHEC] ') + msg); if (!cond) echecs++; };
  const debord = async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  const q = `donnees=${encodeURIComponent(donnees)}`;

  // 1. Accueil
  await page.goto(`${base}/?${q}`);
  await page.waitForSelector('#accueil .acc-tuile', { timeout: 20000 });
  ok(await page.isVisible('#accueil') && !(await page.isVisible('#comp-view')), 'accueil affiché sans paramètre');
  ok((await page.$$('#accueil .acc-tuile')).length === 8, '8 tuiles (3 coupes + 5 championnats)');
  const blocs = await page.$$eval('#accueil .acc-bloc-h b', els => els.map(e => e.textContent));
  ok(blocs.length > 0, `derniers résultats : ${blocs.join(', ')}`);
  ok(await debord() <= 0, 'accueil : pas de débordement horizontal');
  await page.screenshot({ path: `${out}/01-accueil.png`, fullPage: true });

  // 2. Match ouvert depuis l'accueil
  await page.click('#accueil .acc-m');
  await page.waitForSelector('#match-modal.open', { timeout: 10000 });
  await page.screenshot({ path: `${out}/02-accueil-match.png` });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);

  // 3. Entrer dans un championnat par sa tuile
  const tuiles = await page.$$('#accueil .acc-tuile');
  await tuiles[3].click();   // Ligue 1
  await page.waitForSelector('#comp-view:not([hidden]) .match-tile', { timeout: 20000 });
  ok(new URL(page.url()).searchParams.get('c') === 'fl1', 'URL ?c=fl1 ; tour=' + new URL(page.url()).searchParams.get('tour'));
  ok((await page.$$('#tabs-bar .tab-btn')).length === 5, '5 onglets de championnat');
  ok(!(await page.isVisible('#focus-section')), 'pas de focus clubs français en championnat');
  ok(await page.textContent('#tour-btn .tour-t').then(t => /^Journée \d+$/.test(t)), 'menu des journées : ' + await page.textContent('#tour-btn .tour-t'));
  ok(await debord() <= 0, 'championnat : pas de débordement horizontal');
  await page.screenshot({ path: `${out}/03-ligue1.png`, fullPage: true });

  // 4. Fiche de match : Stats (momentum, xG), Compos
  await page.click('.match-tile');
  await page.waitForSelector('#match-modal.open', { timeout: 10000 });
  await page.click('[data-view="stats"]');
  await page.waitForTimeout(300);
  const statsTxt = await page.textContent('#modal-body-content');
  ok(/Buts attendus/.test(statsTxt) && /Momentum/.test(statsTxt), 'stats : momentum + xG');
  ok(!/Autres/.test(statsTxt), 'stats : aucune clé rangée dans « Autres »');
  await page.screenshot({ path: `${out}/04-stats.png`, fullPage: false });
  await page.click('[data-view="lineups"]');
  await page.waitForTimeout(500);
  ok((await page.$$('#modal-body-content .player-dot')).length >= 22, 'compos : 22 titulaires au moins');
  await page.screenshot({ path: `${out}/05-compos.png`, fullPage: false });
  const dot = await page.$('#modal-body-content .player-dot');
  if (dot) { await dot.click(); await page.waitForTimeout(400); await page.screenshot({ path: `${out}/06-joueur.png` }); await page.keyboard.press('Escape'); }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);

  // 5. Onglet suivant (Premier League), menu des journées
  await page.click('#tabs-bar .tab-btn[data-comp="pl"]');
  await page.waitForSelector('#comp-view .match-tile', { timeout: 20000 });
  await page.click('#tour-btn');
  await page.waitForSelector('#tour-modal.open');
  await page.screenshot({ path: `${out}/07-menu-journees.png` });
  await page.keyboard.press('Escape');

  // 6. Retour à l'accueil (bouton) puis retour arrière du navigateur
  await page.click('#home-btn');
  await page.waitForSelector('#accueil:not([hidden])', { timeout: 10000 });
  ok(!new URL(page.url()).searchParams.get('c'), 'retour à l\'accueil : URL sans ?c=');

  // 7. Anciens liens des coupes
  await page.goto(`${base}/?c=ucl&tour=j5&${q}`);
  await page.waitForSelector('#comp-view:not([hidden]) .match-tile', { timeout: 20000 });
  ok((await page.textContent('#tour-btn .tour-t')) === 'Journée 5' && (await page.$$('#tabs-bar .tab-btn')).length === 3, 'ancien lien ?c=ucl&tour=j5 : LDC J5');
  ok(await page.isVisible('#focus-section'), 'coupes : focus clubs français conservé');
  await page.screenshot({ path: `${out}/08-ldc-j5.png`, fullPage: true });
  await page.goto(`${base}/?soiree=2026-11-05&${q}`);
  await page.waitForSelector('#comp-view:not([hidden]) .match-tile', { timeout: 20000 });
  ok(new URL(page.url()).searchParams.get('c') !== null, 'ancien lien ?soiree= : coupe ouverte (' + new URL(page.url()).search + ')');

  ok(erreurs.length === 0, 'console : ' + (erreurs.length ? erreurs.slice(0, 5).join(' | ') : '0 erreur'));
  await browser.close();
  console.log(echecs ? `[BILAN] ${echecs} échec(s)` : '[BILAN] tout est bon');
  process.exit(echecs ? 1 : 0);
})();
