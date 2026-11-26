// Essai Playwright (390 x 844, tactile) du menu latéral des compétitions.
// Usage : node tools/test_menu_ui.js http://localhost:8768 /tmp/menu [dossier-donnees-relatif-ou-url-championnats]
// Le serveur sert index.html + soirees/ + clubs/ + data.json + donnees/ ; les championnats viennent de ?donnees= (Pages réelles par défaut).
// Contrôles : accueil sans tuiles (Derniers résultats puis Prochains matchs), bouton ☰, 4 sections (« Coupes de clubs » ouverte), dérouler,
// clic sur Ligue 1 -> ?c=fl1 + menu fermé, menu sur ?c=fl1 (section ouverte, ligne surlignée), Échap, fond, ✕, glissement vers la gauche,
// focus rendu, état mémorisé après rechargement, 0 débordement, 0 erreur console (hors 404).
const { chromium, devices } = require('playwright');

(async () => {
  const base = process.argv[2] || 'http://localhost:8768';
  const out = process.argv[3] || '/tmp/menu';
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
  const debord = () => page.evaluate(() => document.documentElement.scrollWidth - 390);
  const q = `donnees=${encodeURIComponent(donnees)}`;
  const aller = async (qs, sel) => { await page.goto(`${base}/?${qs}${qs ? '&' : ''}${q}`); await page.waitForSelector(sel, { timeout: 25000 }); await page.waitForTimeout(800); };
  const ouvert = () => page.evaluate(() => document.getElementById('menu-modal').classList.contains('open'));
  const ouvrir = async () => { await page.click('#menu-btn'); await page.waitForSelector('#menu-modal.open'); await page.waitForTimeout(350); };
  const etats = () => page.$$eval('#menu-corps .menu-sec-h', e => e.map(h => `${h.dataset.sec}:${h.getAttribute('aria-expanded')}`).join(' '));
  const swipe = (dx, dy) => page.evaluate(([dx, dy]) => {
    const el = document.getElementById('menu-panel'), r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const t = (px, py) => new Touch({ identifier: 1, target: el, clientX: px, clientY: py });
    el.dispatchEvent(new TouchEvent('touchstart', { touches: [t(x, y)], changedTouches: [t(x, y)], bubbles: true }));
    el.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [t(x + dx, y + dy)], bubbles: true }));
  }, [dx, dy]);

  // 1. Accueil sans tuiles
  await aller('', '#accueil .pm-liste');
  const titres = await page.$$eval('#accueil h2.acc-h', e => e.map(x => x.firstChild.textContent.trim()));
  ok(titres.join('|') === 'Derniers résultats|Prochains matchs', 'accueil : ' + titres.join(' | '));
  ok(!(await page.$('#accueil .acc-tuile, #accueil .acc-grille')), 'accueil : plus aucune tuile');
  ok(await debord() <= 0, 'accueil : pas de débordement horizontal');
  const btn = await page.$('#menu-btn');
  ok(await btn.getAttribute('aria-label') === 'Compétitions' && await btn.getAttribute('aria-expanded') === 'false' && await btn.getAttribute('aria-controls') === 'menu-modal', 'bouton ☰ : aria-label / aria-expanded / aria-controls');
  await page.screenshot({ path: `${out}/01-accueil.png`, fullPage: true });

  // 2. Menu sur l'accueil
  await ouvrir();
  ok(await btn.getAttribute('aria-expanded') === 'true', 'menu ouvert : aria-expanded = true');
  ok((await page.$$('#menu-corps .menu-sec-h')).length === 4, '4 sections : ' + await etats());
  ok(await etats() === 'coupes:true selections:false championnats:false autres:false', 'seule « Coupes de clubs » ouverte par défaut');
  ok((await page.$$('#menu-corps .menu-sec-c:not([hidden]) .menu-ligne')).length === 5, 'coupes : 5 lignes (ucl, uel, uecl, cdmc, ci)');
  const w = await page.$eval('#menu-panel', e => e.getBoundingClientRect().width);
  ok(Math.abs(w - Math.min(390 * 0.86, 340)) < 1.5, 'largeur du panneau = ' + w);
  ok(await page.evaluate(() => document.body.style.overflow === 'hidden'), 'défilement de la page verrouillé');
  const ligne = await page.$eval('#menu-corps .menu-ligne[data-k="ucl"]', e => e.textContent.replace(/\s+/g, ' ').trim());
  ok(/Ligue des Champions/.test(ligne) && /J|Journée|tour|Barrages|Phase/i.test(ligne), 'ligne LDC : ' + ligne);
  await page.screenshot({ path: `${out}/02-menu-accueil.png` });
  // Tab piégé
  for (let i = 0; i < 12; i++) await page.keyboard.press('Tab');
  ok(await page.evaluate(() => document.getElementById('menu-panel').contains(document.activeElement)), 'focus piégé dans le panneau après 12 Tab');
  // Dérouler « Championnats majeurs »
  await page.click('#menu-h-championnats');
  ok(await page.getAttribute('#menu-h-championnats', 'aria-expanded') === 'true' && await page.isVisible('#menu-corps .menu-ligne[data-k="fl1"]'), 'section « Championnats majeurs » déroulée');
  ok(await page.$$eval('#menu-c-championnats .menu-ligne[data-k="fl1"] img.flag', i => i.length) === 1, 'Ligue 1 : drapeau de ligue');
  ok(await debord() <= 0, 'menu ouvert : pas de débordement horizontal');
  // Échap
  await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  ok(!(await ouvert()), 'Échap ferme le menu');
  ok(await page.evaluate(() => document.activeElement.id === 'menu-btn'), 'focus rendu au bouton ☰');
  ok(await page.evaluate(() => document.body.style.overflow === ''), 'verrou de défilement levé');
  // Fond
  await ouvrir(); await page.mouse.click(380, 400); await page.waitForTimeout(200);
  ok(!(await ouvert()), 'clic sur le fond ferme le menu');
  // Glissement
  await ouvrir(); await swipe(-20, 0);
  ok(await ouvert(), 'glissement de 20 px : menu toujours ouvert');
  await swipe(-30, -90);
  ok(await ouvert(), 'glissement surtout vertical : menu toujours ouvert');
  await swipe(-100, 10); await page.waitForTimeout(200);
  ok(!(await ouvert()), 'glissement vers la gauche ferme le menu');
  // ✕
  await ouvrir(); await page.click('#menu-close'); await page.waitForTimeout(200);
  ok(!(await ouvert()), 'bouton ✕ ferme le menu');

  // 3. Clic sur Ligue 1
  await ouvrir();
  ok(await page.isVisible('#menu-corps .menu-ligne[data-k="fl1"]'), 'section championnats encore ouverte (état gardé)');
  await page.click('#menu-corps .menu-ligne[data-k="fl1"]');
  await page.waitForSelector('#comp-view:not([hidden]) .match-tile', { timeout: 25000 });
  ok(new URL(page.url()).searchParams.get('c') === 'fl1' && !(await ouvert()), 'clic Ligue 1 -> ?c=fl1, menu fermé');
  ok(await page.isVisible('#menu-btn'), 'bouton ☰ visible sur la page de compétition');
  await page.screenshot({ path: `${out}/03-fl1.png` });

  // 4. Menu sur ?c=fl1 ouvert directement
  await aller('c=fl1', '#comp-view:not([hidden]) .match-tile');
  await ouvrir();
  ok((await etats()).includes('championnats:true'), 'sur ?c=fl1 : section des championnats majeurs ouverte (' + await etats() + ')');
  ok(await page.getAttribute('#menu-corps .menu-ligne[data-k="fl1"]', 'aria-current') === 'true', 'Ligue 1 surlignée (aria-current)');
  await page.waitForTimeout(2500);
  const sous = await page.$$eval('#menu-corps .menu-ligne', e => e.filter(x => x.querySelector('.ms') && x.querySelector('.ms').textContent.trim() === '…').length);
  ok(sous === 0, 'sous-titres chargés (aucun « … » restant)');
  const fl1 = await page.$eval('#menu-corps .menu-ligne[data-k="fl1"]', e => e.textContent.replace(/\s+/g, ' ').trim());
  ok(/Journée \d+/.test(fl1), 'Ligue 1 : ' + fl1);
  await page.screenshot({ path: `${out}/04-menu-fl1.png` });
  // Changer de compétition depuis une page de compétition, puis retour accueil par le bouton maison
  await page.click('#menu-h-coupes'); await page.click('#menu-corps .menu-ligne[data-k="ucl"]');
  await page.waitForSelector('#comp-view:not([hidden]) .match-tile', { timeout: 25000 });
  ok(new URL(page.url()).searchParams.get('c') === 'ucl', 'depuis Ligue 1 -> LDC (?c=ucl)');
  ok(await page.$$eval('#tabs-bar .tab-btn.active', b => b.length === 1 && b[0].dataset.comp === 'ucl'), 'onglet LDC actif');
  // glissement entre onglets inchangé
  await page.click('#tabs-bar .tab-btn[data-comp="uel"]'); await page.waitForTimeout(600);
  ok(new URL(page.url()).searchParams.get('c') === 'uel', 'onglets de coupes toujours fonctionnels');

  // 5. Mémorisation après rechargement
  await aller('', '#accueil .pm-liste');
  await ouvrir();
  await page.click('#menu-h-autres'); await page.click('#menu-h-coupes');
  const avant = await etats();
  await page.reload(); await page.waitForSelector('#accueil .pm-liste', { timeout: 25000 }); await page.waitForTimeout(500);
  await ouvrir();
  ok(await etats() === avant, 'état des sections mémorisé après rechargement : ' + avant);
  // Stockage indisponible : la page marche
  await page.evaluate(() => localStorage.setItem('menu-sections-ouvertes', '{pas du json'));
  await page.reload(); await page.waitForSelector('#accueil .pm-liste', { timeout: 25000 }); await ouvrir();
  ok(await etats() === 'coupes:true selections:false championnats:false autres:false', 'stockage corrompu : valeurs par défaut');
  await page.evaluate(() => localStorage.removeItem('menu-sections-ouvertes'));

  ok(erreurs.length === 0, 'aucune erreur console' + (erreurs.length ? ' : ' + erreurs.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(echecs ? `${echecs} échec(s)` : 'Tout est vert');
  process.exit(echecs ? 1 : 0);
})();
