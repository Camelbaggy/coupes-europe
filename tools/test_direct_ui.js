// Essai Playwright (390 x 844, tactile) du suivi en direct (drapeaux internationaux, équipes françaises en haut, tour du jour par défaut).
// Usage : node tools/test_direct_ui.js http://localhost:8767 /tmp/caps_direct [dossier-donnees-relatif]
// Le serveur sert index.html + soirees/ + clubs/ + data.json + donnees/. Les appels vers site.web.api.espn.com sont interceptés (routes Playwright).
// Contrôles : 0 erreur console (hors 404 attendus éventuels), 0 débordement horizontal sur 390 x 844 :
// 1. Direct international (ucl, uel, uecl, cdm, cdmc) : drapeaux flagcdn.com/w40/..., JAMAIS de logo club ESPN ; championnats (fl1, pl) : logos conservés.
// 2. Matchs internationaux français (PSG en LDC, Lyon en LE, Strasbourg en LC, France en CdM) en haut de #direct-accueil (avant tout match non-FR)
//    et en haut de #direct-section, avec la classe .is-fr.
// 3. Ouverture par défaut de la journée / phase du jour quand il y a des matchs aujourd'hui (y compris un tour futur > 150 min) ; repli sur la dernière jouée sinon.
const { chromium, devices } = require(process.env.PLAYWRIGHT_PATH || 'playwright');

(async () => {
  const base = process.argv[2] || 'http://localhost:8767';
  const out = process.argv[3] || '/tmp/caps_direct';
  const donnees = process.argv[4] || 'donnees/';
  require('fs').mkdirSync(out, { recursive: true });
  const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH, args: ['--no-sandbox'] } : {});
  const ctx = await browser.newContext({ ...devices['iPhone 13'], viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const erreurs = [];
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|ERR_/.test(m.text())) erreurs.push(m.text()); });
  page.on('pageerror', e => erreurs.push(String(e)));

  let echecs = 0;
  const ok = (cond, msg) => { console.log((cond ? '[OK] ' : '[ÉCHEC] ') + msg); if (!cond) echecs++; };
  const debord = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  const q = `donnees=${encodeURIComponent(donnees)}`;

  const nowIso = new Date(Date.now() - 35 * 60000).toISOString();
  const team = (id, name, abbr, logo) => ({
    homeAway: '',
    score: '1',
    team: { id: String(id), displayName: name, shortDisplayName: name, name, abbreviation: abbr, logo },
  });
  const mkEvent = (id, home, away, minute = "42'") => ({
    id: String(id),
    date: nowIso,
    status: { displayClock: minute, type: { state: 'in', name: 'STATUS_FIRST_HALF', completed: false } },
    competitions: [{
      competitors: [
        { ...home, homeAway: 'home', score: '2' },
        { ...away, homeAway: 'away', score: '1' },
      ],
    }],
  });

  // Mock ESPN scoreboard responses
  const espnBySlug = {
    'uefa.champions': [
      mkEvent('9001', team('86', 'Real Madrid', 'RMA', 'https://a.espncdn.com/i/teamlogos/soccer/500/86.png'), team('132', 'Bayern Munich', 'BAY', 'https://a.espncdn.com/i/teamlogos/soccer/500/132.png')),
      mkEvent('9002', team('160', 'Paris Saint-Germain', 'PSG', 'https://a.espncdn.com/i/teamlogos/soccer/500/160.png'), team('364', 'Liverpool', 'LIV', 'https://a.espncdn.com/i/teamlogos/soccer/500/364.png')),
    ],
    'uefa.europa': [
      mkEvent('9003', team('104', 'AS Roma', 'ROM', 'https://a.espncdn.com/i/teamlogos/soccer/500/104.png'), team('167', 'Olympique Lyonnais', 'LYO', 'https://a.espncdn.com/i/teamlogos/soccer/500/167.png')),
    ],
    'uefa.europa.conf': [
      mkEvent('9004', team('180', 'RC Strasbourg', 'STR', 'https://a.espncdn.com/i/teamlogos/soccer/500/180.png'), team('9991', 'Fiorentina', 'FIO', 'https://a.espncdn.com/i/teamlogos/soccer/500/109.png')),
    ],
    'fifa.world': [
      mkEvent('9005', team('478', 'France', 'FRA', 'https://a.espncdn.com/i/teamlogos/countries/500/fra.png'), team('203', 'Spain', 'ESP', 'https://a.espncdn.com/i/teamlogos/countries/500/esp.png')),
    ],
    'fifa.cwc': [
      mkEvent('9006', team('10207', 'Al Ahly FC', 'AHL', 'https://a.espncdn.com/i/teamlogos/soccer/500/10207.png'), team('16', 'CA River Plate', 'RIV', 'https://a.espncdn.com/i/teamlogos/soccer/500/16.png')),
    ],
    'fra.1': [
      mkEvent('9007', team('176', 'Marseille', 'OLM', 'https://a.espncdn.com/i/teamlogos/soccer/500/176.png'), team('174', 'Monaco', 'MON', 'https://a.espncdn.com/i/teamlogos/soccer/500/174.png')),
    ],
    'eng.1': [
      mkEvent('9008', team('359', 'Arsenal', 'ARS', 'https://a.espncdn.com/i/teamlogos/soccer/500/359.png'), team('363', 'Chelsea', 'CHE', 'https://a.espncdn.com/i/teamlogos/soccer/500/363.png')),
    ],
  };

  await page.route('https://site.web.api.espn.com/**', async route => {
    const url = route.request().url();
    const m = /\/soccer\/([^/]+)\/scoreboard/.exec(url);
    const slug = m && m[1];
    const events = espnBySlug[slug] || [];
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events }) });
  });

  // 1. Accueil : drapeaux internationaux vs logos domestiques + matchs français en haut
  await page.goto(`${base}/?${q}`);
  await page.waitForSelector('#direct-accueil .direct-bloc', { timeout: 20000 });
  await page.waitForTimeout(300);

  const accInfo = await page.evaluate(() => {
    const bloc = document.querySelector('#direct-accueil .direct-bloc');
    const items = [];
    let section = '';
    for (const el of bloc.children) {
      if (el.classList.contains('direct-comp')) {
        section = el.textContent.replace(/\s+/g, ' ').trim();
      } else if (el.classList.contains('acc-m')) {
        const imgs = [...el.querySelectorAll('img.flag')].map(i => ({
          src: i.getAttribute('src') || '',
          isClubLogo: i.classList.contains('logo-club'),
        }));
        items.push({
          section,
          text: el.textContent.replace(/\s+/g, ' ').trim(),
          frCount: el.querySelectorAll('.is-fr').length,
          hasTag: !!el.querySelector('.direct-tag'),
          tagText: (el.querySelector('.direct-tag') || {}).textContent || '',
          imgs,
        });
      }
    }
    return { sections: [...bloc.querySelectorAll('.direct-comp')].map(s => s.textContent.replace(/\s+/g, ' ').trim()), items };
  });

  ok(accInfo.sections[0].includes('Équipes françaises'), 'accueil direct : section "Équipes françaises" en premier (' + accInfo.sections[0] + ')');
  const frItems = accInfo.items.filter(i => i.section.includes('Équipes françaises'));
  ok(frItems.length === 4, 'accueil direct : 4 matchs internationaux français remontés en haut (PSG, Lyon, Strasbourg, France), trouvé ' + frItems.length);
  ok(frItems.every(i => i.frCount >= 1 && i.hasTag), 'accueil direct : matchs français marqués .is-fr avec étiquette de compétition');
  const otherItems = accInfo.items.filter(i => !i.section.includes('Équipes françaises'));
  ok(otherItems.some(i => i.section.includes('Ligue des Champions')) && otherItems.some(i => i.section.includes('Ligue 1')),
    'accueil direct : autres matchs conservés sous leurs compétitions');
  ok(!otherItems.some(i => /Paris Saint-Germain|Olympique Lyonnais|RC Strasbourg|France/.test(i.text)),
    'accueil direct : matchs internationaux français retirés de leurs blocs d\'origine');

  const intlImgs = accInfo.items
    .filter(i => !/Ligue 1|Premier League/.test(i.section))
    .flatMap(i => i.imgs);
  const domImgs = accInfo.items
    .filter(i => /Ligue 1|Premier League/.test(i.section))
    .flatMap(i => i.imgs);

  ok(intlImgs.length >= 10 && intlImgs.every(i => !/teamlogos(%2F|\/)soccer/i.test(i.src)),
    'accueil direct : aucun logo de club ESPN dans les compétitions internationales/européennes');
  ok(intlImgs.filter(i => /flagcdn\.com\/w40\//.test(i.src)).length >= 8,
    'accueil direct : drapeaux flagcdn affichés pour les équipes internationales/européennes (' + intlImgs.filter(i => /flagcdn\.com\/w40\//.test(i.src)).length + ')');
  ok(domImgs.length === 4 && domImgs.every(i => i.isClubLogo && /espncdn\.com\/combiner/.test(i.src)),
    'accueil direct : logos des clubs conservés pour fl1 / pl');
  ok(await debord() <= 0, 'accueil direct : 0 débordement horizontal sur 390x844');
  await page.screenshot({ path: `${out}/d01-accueil-direct.png`, fullPage: true });

  // 2. Page compétition (LDC) : match français en premier dans #direct-section + drapeaux
  await page.goto(`${base}/?c=ucl&${q}`);
  await page.waitForSelector('#direct-section:not([hidden]) .direct-bloc', { timeout: 20000 });
  const uclDirect = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('#direct-section .acc-m')];
    return rows.map(r => ({
      text: r.textContent.replace(/\s+/g, ' ').trim(),
      fr: r.querySelectorAll('.is-fr').length,
      imgs: [...r.querySelectorAll('img.flag')].map(i => ({ src: i.getAttribute('src') || '', club: i.classList.contains('logo-club') })),
    }));
  });
  ok(uclDirect.length === 2, 'ucl direct : 2 matchs affichés');
  ok(uclDirect[0].fr === 1 && /Paris/.test(uclDirect[0].text), 'ucl direct : PSG en premier dans #direct-section (' + uclDirect[0].text + ')');
  ok(uclDirect.flatMap(r => r.imgs).every(i => !i.club && /flagcdn\.com\/w40\//.test(i.src)), 'ucl direct : drapeaux uniquement');
  ok(await debord() <= 0, 'ucl direct : 0 débordement horizontal sur 390x844');
  await page.screenshot({ path: `${out}/d02-ucl-direct.png` });

  // 3. Page compétition sans match du jour : comportement par défaut conservé (LDC -> J5)
  const uclDefTour = await page.textContent('#tour-btn .tour-t');
  ok(uclDefTour === 'Journée 5', 'ucl sans match aujourd\'hui : ouvre la dernière journée jouée (' + uclDefTour + ')');

  // 4. Tour du jour par défaut (coupes, championnats, internationales) avec un match programmé aujourd'hui (> 150 min après coup d'envoi)
  const todayParis = await page.evaluate(() => new Date().toLocaleDateString('en-CA', { timeZone: 'Europe/Paris' }));
  const fourHoursAgo = new Date(Date.now() - 240 * 60000).toISOString();

  // Mock programme.json pour ucl (J7 aujourd'hui, commencée il y a 4h -> cachée par progVisibles mais doit rester sélectionnée par défaut)
  await page.route('**/clubs/programme.json*', async route => {
    const resp = await route.fetch();
    const json = await resp.json();
    json.competitions.ucl.push({
      id: '2049999',
      debut: fourHoursAgo,
      date: todayParis,
      stage: 'league',
      tour: 'J7',
      home_team: { flag: 'fr', country_name: 'France', id: '52747', name: 'Paris', short: 'PSG', country: 'FRA', is_french: true },
      away_team: { flag: 'es', country_name: 'Espagne', id: '50080', name: 'Barcelona', short: 'BAR', country: 'ESP', is_french: false },
      statut: 'À venir',
      stade: 'Parc des Princes',
      ville: 'Paris',
    });
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(json) });
  });

  // Mock programme.json pour cdm 2026 (phase Quarts de finale aujourd'hui)
  await page.route('**/internationales/cdm/2026/programme.json*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source: 'FIFA',
        maj: nowIso,
        matchs: [{
          id: 'fifa-99901',
          debut: fourHoursAgo,
          date: todayParis,
          phase: 'finale',
          tour: 'Quarts de finale',
          tour_court: 'Quarts de finale',
          statut: 'À venir',
          home_team: { flag: 'fr', country_name: 'France', id: 'espn-478', espn_id: '478', name: 'France', short: 'FRA', country: 'FRA', is_french: true },
          away_team: { flag: 'es', country_name: 'Espagne', id: 'espn-203', espn_id: '203', name: 'Espagne', short: 'ESP', country: 'ESP', is_french: false },
          stade: 'MetLife Stadium',
          ville: 'New York',
        }],
      }),
    });
  });

  await page.goto(`${base}/?c=ucl&${q}`);
  await page.waitForSelector('#comp-view:not([hidden]) #tour-btn', { timeout: 20000 });
  const uclTodayTour = await page.textContent('#tour-btn .tour-t');
  ok(/Journée 7/.test(uclTodayTour), 'defaultTour(ucl) : ouvre la journée du jour (Journée 7) même > 150 min après coup d\'envoi (' + uclTodayTour + ')');
  ok(await debord() <= 0, 'ucl tour du jour : 0 débordement horizontal');

  await page.goto(`${base}/?c=cdm&${q}`);
  await page.waitForSelector('#comp-view:not([hidden]) #tour-btn', { timeout: 20000 });
  const cdmTodayTour = await page.textContent('#tour-btn .tour-t');
  ok(/Quarts de finale/.test(cdmTodayTour), 'defaultTourIntl(cdm) : ouvre la phase du jour (Quarts de finale) même > 150 min après coup d\'envoi (' + cdmTodayTour + ')');
  ok(await debord() <= 0, 'cdm tour du jour : 0 débordement horizontal');
  await page.screenshot({ path: `${out}/d03-cdm-tour-du-jour.png` });

  // Vérification sans match du jour sur euro -> reste sur Finale
  await page.goto(`${base}/?c=euro&${q}`);
  await page.waitForSelector('#comp-view:not([hidden]) #tour-btn', { timeout: 20000 });
  const euroTour = await page.textContent('#tour-btn .tour-t');
  ok(euroTour === 'Finale', 'defaultTourIntl(euro) sans match aujourd\'hui : reste sur la dernière phase jouée (' + euroTour + ')');

  ok(erreurs.length === 0, 'console : ' + (erreurs.length ? erreurs.slice(0, 5).join(' | ') : '0 erreur'));
  await browser.close();
  console.log(echecs ? `[BILAN] ${echecs} échec(s)` : '[BILAN] tout est bon');
  process.exit(echecs ? 1 : 0);
})();
