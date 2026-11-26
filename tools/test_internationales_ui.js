// Essai Playwright (390 x 844, tactile) des compétitions internationales (sélections et compétitions mondiales de clubs).
// Usage : node tools/test_internationales_ui.js http://localhost:8790 /tmp/caps [dossier-donnees-relatif]
// Le serveur sert index.html + soirees/ + clubs/ + data.json et un dossier « donnees/ » contenant internationales/ (passé par ?donnees=).
// Contrôles : 0 erreur console (hors 404 attendus : championnats absents, fichiers optionnels d'une édition), 0 débordement horizontal,
// accueil (sections, tuiles), CdM (menu des tours par édition, groupes, tableau final, fiche de match), Euro, Ligue des nations (tour à
// venir), Coupe intercontinentale, Coupe du monde des clubs (flux réduit), non-régression ?c=ucl / ?c=fl1.
const { chromium, devices } = require('playwright');

(async () => {
  const base = process.argv[2] || 'http://localhost:8790';
  const out = process.argv[3] || '/tmp/caps';
  const donnees = process.argv[4] || 'donnees/';
  require('fs').mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'], viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const erreurs = [], manquants = [];
  const attendu = (u) => /\/championnats\//.test(u) || /internationales\/[a-z]+\/\d+\/(classements|programme)\.json/.test(u);
  page.on('response', r => { if (r.status() === 404) manquants.push(r.url()); });
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) erreurs.push(m.text()); });
  page.on('pageerror', e => erreurs.push(String(e)));
  let echecs = 0;
  const ok = (cond, msg) => { console.log((cond ? '[OK] ' : '[ÉCHEC] ') + msg); if (!cond) echecs++; };
  const debord = async () => page.evaluate(() => document.documentElement.scrollWidth - 390);
  const q = `donnees=${encodeURIComponent(donnees)}`;
  const images = async () => { try { await page.waitForFunction(() => [...document.images].every(i => i.complete), null, { timeout: 8000 }); } catch (e) { /* capture quand même */ } };
  const aller = async (qs, sel) => { await page.goto(`${base}/?${qs}&${q}`); await page.waitForSelector(sel, { timeout: 20000 }); await page.waitForTimeout(500); };
  const tours = () => page.textContent('#tour-btn .tour-t');

  // 1. Accueil
  await aller('', '#accueil .acc-tuile');
  const titres = await page.$$eval('#accueil h2.acc-h', e => e.map(x => x.textContent));
  ok(['Coupes de clubs', 'Sélections nationales', 'Championnats majeurs'].every((t, i) => titres.includes(t) && titres.indexOf(t) === titres.findIndex(x => x === t)) &&
     titres.indexOf('Sélections nationales') < titres.indexOf('Championnats majeurs') && titres.indexOf('Coupes de clubs') < titres.indexOf('Sélections nationales'), 'accueil : sections ' + titres.join(' | '));
  const tu = await page.$$eval('#accueil .acc-tuile', e => e.map(x => x.dataset.k));
  ok(tu.length === 21 && ['cdmc', 'ci', 'cdm', 'euro', 'ldn'].every(k => tu.includes(k)), `accueil : ${tu.length} tuiles dont CdM clubs, Intercontinentale, CdM, Euro, Ligue des nations`);
  ok(await debord() <= 0, 'accueil : pas de débordement horizontal');
  await images();
  await page.screenshot({ path: `${out}/i01-accueil.png`, fullPage: true });

  // 2. Coupe du monde : défaut, menu des tours par édition
  await page.click('#accueil .acc-tuile[data-k="cdm"]');
  await page.waitForSelector('#comp-view:not([hidden]) .match-tile', { timeout: 20000 });
  ok(new URL(page.url()).searchParams.get('c') === 'cdm', 'tuile CdM -> ?c=cdm&tour=' + new URL(page.url()).searchParams.get('tour'));
  ok(await page.$$eval('#tabs-bar .tab-btn', b => b.length) === 3, '3 onglets de sélections');
  ok(/^2026-/.test(new URL(page.url()).searchParams.get('tour') || ''), 'id de tour avec édition');
  ok(await tours() === 'Finale', 'défaut : tour le plus récent joué = ' + await tours());
  ok(!(await page.isVisible('#focus-section')), 'pas de cartes de clubs français');
  ok(await page.isVisible('#bracket-section') && (await page.$$('#bracket-container .br-col')).length >= 2, 'tableau final : ' + (await page.$$('#bracket-container .br-col')).length + ' colonnes');
  ok(await page.$eval('#bracket-container .bracket', e => e.hasAttribute('data-noswipe') && e.scrollWidth >= e.clientWidth), 'tableau final : bloc data-noswipe');
  ok(await debord() <= 0, 'CdM finale : pas de débordement horizontal');
  await images();
  await page.screenshot({ path: `${out}/i02-cdm-finale.png`, fullPage: true });
  await page.click('#tour-btn');
  await page.waitForSelector('#tour-modal.open');
  const grp = await page.$$eval('#tour-list .tour-grp', e => e.map(x => x.textContent));
  ok(grp.some(g => /Coupe du monde 2026/.test(g)), 'menu des tours groupé par édition : ' + grp.join(' | '));
  const opts = await page.$$eval('#tour-list .tour-opt .tour-t', e => e.map(x => x.textContent));
  ok(opts[0] === 'Finale' && opts.includes('Phase de groupes · J1'), 'menu : ordre chronologique inverse (' + opts.slice(0, 6).join(' / ') + ')');
  await page.screenshot({ path: `${out}/i03-cdm-menu.png` });
  await page.click('#tour-list .tour-opt:has-text("Phase de groupes · J1")');
  await page.waitForSelector('#comp-view .match-tile');
  await page.waitForTimeout(400);
  ok(/groupes-j1/.test(new URL(page.url()).searchParams.get('tour')), 'tour J1 choisi : ' + new URL(page.url()).searchParams.get('tour'));
  const details = await page.$$eval('#standings-container details.grp', d => d.map(x => x.open));
  ok(details.length >= 1 && details[0] === true, `tableaux de groupe : ${details.length} groupe(s), le premier ouvert`);
  ok(await page.$eval('#standings-container details.grp', d => /FRA/.test(d.textContent)), 'groupe de la France en premier');
  ok(await page.$$eval('#standings-container tr.is-fr-row', r => r.length) >= 1 && await page.$$eval('.tile-team-name.is-fr', r => r.length) >= 1, 'France surlignée (lignes et matchs)');
  ok(!(await page.isVisible('#bracket-section')), 'pas de tableau final pour un tour de groupes');
  await page.click('#standings-title .info-btn');
  ok(/officiel actuel/.test(await page.textContent('#info-pop')) && /Qualifié/.test(await page.textContent('#info-pop')), 'info-bulle des classements : source + légende des zones');
  await page.keyboard.press('Escape');
  await images();
  await page.screenshot({ path: `${out}/i04-cdm-groupes.png`, fullPage: true });

  // 3. Fiche de match France - Sénégal
  const tuile = page.locator('.match-tile', { hasText: 'Sénégal' }).first();
  await tuile.click();
  await page.waitForSelector('#match-modal.open');
  ok(/Phase de groupes/.test(await page.textContent('#modal-round')) && /Groupe I/.test(await page.textContent('#modal-round')), 'en-tête de fiche : ' + await page.textContent('#modal-round'));
  ok(!(await page.$('#match-modal .club-link')), 'aucun lien de club pour une sélection');
  ok(((await page.textContent('#modal-body-content')).match(/'/g) || []).length > 3, 'déroulé affiché');
  await page.click('[data-view="stats"]'); await page.waitForTimeout(300);
  const st = await page.textContent('#modal-body-content');
  ok(/Momentum/.test(st) && /Buts attendus/.test(st), 'stats : momentum + xG');
  ok(await page.$$eval('#modal-body-content svg', s => s.length) >= 1, 'momentum : graphique présent');
  await page.screenshot({ path: `${out}/i05-cdm-fiche-stats.png` });
  await page.click('[data-view="lineups"]'); await page.waitForTimeout(500);
  ok((await page.$$('#modal-body-content .player-dot')).length >= 22, 'compos : 22 titulaires au moins');
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);

  // 4. Tableau final : fiche depuis le tableau
  await aller('c=cdm', '.match-tile');
  await page.click('#bracket-container .br-m >> nth=0');
  await page.waitForSelector('#match-modal.open');
  ok(/Demi-finale/.test(await page.textContent('#modal-round')), 'fiche ouverte depuis le tableau final : ' + await page.textContent('#modal-round'));
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);

  // 5. Euro, éliminatoires de la Coupe du monde
  await aller('c=euro', '.match-tile');
  ok(await tours() === 'Finale' && await page.isVisible('#bracket-section'), 'Euro : finale + tableau final');
  await page.screenshot({ path: `${out}/i06-euro.png`, fullPage: true });
  await aller('c=cdm&tour=2026-eliminatoires-j9', '.match-tile');
  const grQ = await page.$$eval('#standings-container details.grp', d => d.length);
  ok(grQ >= 1 && /Éliminatoires/.test(await tours()), `CdM éliminatoires : ${grQ} groupes de qualification`);
  ok(await debord() <= 0, 'CdM éliminatoires : pas de débordement horizontal');
  await page.screenshot({ path: `${out}/i07-cdm-elim.png`, fullPage: true });

  // 6. Ligue des nations : tour à venir (programme)
  await aller('c=ldn', '.match-tile');
  ok(/Phase de ligue/.test(await tours()), 'LdN : défaut ' + await tours());
  await page.click('#tour-btn'); await page.waitForSelector('#tour-modal.open');
  const gl = await page.$$eval('#tour-list .tour-grp', e => e.map(x => x.textContent));
  ok(gl[0] === 'À venir' && gl.some(g => /Ligue des nations 2026-27/.test(g)), 'menu LdN : ' + gl.join(' | '));
  await page.click('#tour-list .tour-opt:has-text("Quarts de finale")');
  await page.waitForSelector('#prog-section:not([hidden]) .match-tile.prog', { timeout: 10000 });
  ok(!(await page.isVisible('#results-section')) && (await page.$$('#prog-container .match-tile.prog')).length >= 2, 'tour à venir : Programme seul (' + (await page.$$('#prog-container .match-tile.prog')).length + ' matchs)');
  ok(/\d{2}:\d{2}/.test(await page.textContent('#prog-container')), 'programme : heure de Paris');
  ok(await page.isVisible('#bracket-section'), 'tableau final du tour à venir');
  await page.screenshot({ path: `${out}/i08-ldn-quarts.png`, fullPage: true });
  ok(await debord() <= 0, 'LdN à venir : pas de débordement horizontal');

  // 7. Coupe intercontinentale : programme de décembre, « À déterminer »
  await aller('c=ci', '.match-tile');
  ok(await page.$$eval('#tabs-bar .tab-btn', b => b.length) === 5, 'CI : 5 onglets de coupes de clubs');
  await page.click('#tour-btn'); await page.waitForSelector('#tour-modal.open');
  const fut = await page.$$eval('#tour-list .tour-opt', e => e.filter(x => /à venir/.test(x.textContent)).map(x => x.querySelector('.tour-t').textContent.replace('à venir', '')));
  ok(fut.length >= 2, 'CI : tours à venir ' + fut.join(' / '));
  await page.click('#tour-list .tour-opt:has-text("Finale")');
  await page.waitForSelector('#prog-section:not([hidden])');
  const pt = await page.textContent('#prog-container');
  ok(/Paris/.test(pt) && /À déterminer/.test(pt), 'CI finale : PSG + « À déterminer » (' + pt.replace(/\s+/g, ' ').slice(0, 120) + ')');
  ok(await page.isVisible('#bracket-section') && /À déterminer/.test(await page.textContent('#bracket-container')), 'CI : tableau final avec places à déterminer');
  await page.screenshot({ path: `${out}/i09-ci-finale.png`, fullPage: true });
  ok(await debord() <= 0, 'CI : pas de débordement horizontal');

  // 8. Coupe du monde des clubs : finale Chelsea - PSG, flux réduit
  await aller('c=cdmc', '.match-tile');
  ok(await page.$$eval('.tile-team-name.is-fr', r => r.length) >= 1, 'CdM clubs : PSG surligné');
  await page.click('.match-tile'); await page.waitForSelector('#match-modal.open');
  await page.click('[data-view="stats"]'); await page.waitForTimeout(300);
  ok(/pas de graphique de pression/.test(await page.textContent('#modal-body-content')), 'flux réduit : message à la place du momentum');
  await page.screenshot({ path: `${out}/i10-cdmc-fiche.png` });
  await page.keyboard.press('Escape'); await page.waitForTimeout(300);
  ok(await debord() <= 0, 'CdM clubs : pas de débordement horizontal');
  await page.screenshot({ path: `${out}/i11-cdmc.png`, fullPage: true });

  // 9. Non-régression : coupes d'Europe et championnats
  await aller('c=ucl&tour=j5', '.match-tile');
  ok(await tours() === 'Journée 5' && await page.$$eval('#tabs-bar .tab-btn', b => b.length) === 5 && await page.isVisible('#focus-section') && !(await page.isVisible('#bracket-section')), 'LDC J5 : 5 onglets, focus français, pas de tableau final');
  ok(await debord() <= 0, 'LDC : pas de débordement horizontal');
  await page.screenshot({ path: `${out}/i12-ldc.png` });
  await page.goto(`${base}/?c=fl1&${q}`); await page.waitForTimeout(2500);
  ok(await page.isVisible('#comp-view'), 'Ligue 1 : page ouverte sans erreur (données locales éventuellement absentes)');
  ok(await debord() <= 0, 'Ligue 1 : pas de débordement horizontal');

  const inattendus = manquants.filter(u => !attendu(u));
  ok(inattendus.length === 0, '404 inattendus : ' + (inattendus.length ? inattendus.slice(0, 4).join(' | ') : 'aucun'));
  ok(erreurs.length === 0, 'console : ' + (erreurs.length ? erreurs.slice(0, 5).join(' | ') : '0 erreur'));
  await browser.close();
  console.log(echecs ? `[BILAN] ${echecs} échec(s)` : '[BILAN] tout est bon');
  process.exit(echecs ? 1 : 0);
})();
