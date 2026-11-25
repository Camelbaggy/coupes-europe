// Test Playwright 390 x 844 tactile des couleurs d'équipe (CLAUDE.md, § Couleurs des équipes). Usage : python -m http.server 8765 &, puis node tools/test_couleurs_ui.js http://localhost:8765 <dossier de captures>
const { chromium } = require(process.env.PLAYWRIGHT_PATH || '/opt/node-tools/node_modules/playwright');
const OUT = process.argv[3];
const BASE = process.argv[2];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error' && !/flagcdn|img\.uefa|ERR_|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await page.goto(BASE + '/index.html?c=ucl', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof couleursMatch === 'function' && clubIndex && clubIndex.size > 0);

  // 1. Toutes les soirées : écart minimal, contraste, sources
  const bilan = await page.evaluate(async () => {
    const idx = await (await fetch('soirees/index.json')).json();
    const r = { soirees: 0, matchs: 0, sources: {}, minDE: 1e9, minDE_match: null, sousSeuil: [], contrasteTexteMin: 99, encreMin: 99, substitutions: [], sansMaillot: 0, sansRien: [] };
    const pages = coulFondsPage();
    for (const l of idx) {
      const d = await (await fetch('soirees/' + l.date + '.json')).json();
      r.soirees++;
      for (const comp of Object.values(d.competitions || {})) for (const m of comp.matches || []) {
        r.matchs++;
        const c = couleursMatch(m);
        const de = coulDeltaE76(c.home.fond, c.away.fond);
        if (de < r.minDE) { r.minDE = de; r.minDE_match = l.date + ' ' + m.home_team.short + '-' + m.away_team.short; }
        if (de < COUL_SEUIL_DE) r.sousSeuil.push(l.date + ' ' + m.home_team.short + '-' + m.away_team.short + ' ' + de.toFixed(1));
        for (const k of ['home', 'away']) {
          r.sources[c[k].source] = (r.sources[c[k].source] || 0) + 1;
          r.contrasteTexteMin = Math.min(r.contrasteTexteMin, coulContraste(c[k].texte, c[k].fond));
          for (const p of pages) r.encreMin = Math.min(r.encreMin, coulContraste(c[k].encre, p));
          if (c[k].source !== 'maillot') r.sansMaillot++;
        }
        if (c.away.source === 'secondaire' || (c.away.source === 'neutre' && m.away_team.shirt_color !== undefined)) r.substitutions.push(l.date + ' ' + m.home_team.short + '-' + m.away_team.short);
        if (c.home.source === 'neutre' || c.away.source === 'neutre') r.sansRien.push(l.date + ' ' + m.home_team.short + '-' + m.away_team.short + ' ' + c.home.source + '/' + c.away.source);
      }
    }
    return r;
  });
  console.log('BILAN', JSON.stringify(bilan, null, 1));

  // 2. Rendu : fiche de match (3 onglets) + fiche de club, contrastes mesurés dans le DOM
  const mesurer = () => page.evaluate(() => {
    const rgb = (s) => { const m = s.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
    const hex = (a) => '#' + a.slice(0, 3).map(x => x.toString(16).padStart(2, '0')).join('');
    const lis = [];
    const fonds = coulFondsPage();
    const res = { texteSurAplat: [], encreSurPage: [], debordement: document.documentElement.scrollWidth - innerWidth };
    const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    document.querySelectorAll('.player-dot, .cl-loc').forEach(el => {
      if (!visible(el)) return;
      const cs = getComputedStyle(el); const bg = rgb(cs.backgroundColor), fg = rgb(cs.color);
      if (bg && fg && bg[3] === 1) res.texteSurAplat.push({ cls: el.className, ratio: coulContraste(hex(fg), hex(bg)) });
    });
    document.querySelectorAll('.st-team, .poss-v, .st-v.dom, .momentum-legend span:not(#momentum-readout), .subs-list b, #club-tabs .subtab-btn.active, .cl-rank b').forEach(el => {
      if (!visible(el)) return;
      const fg = rgb(getComputedStyle(el).color);
      if (fg) res.encreSurPage.push({ cls: el.className || el.tagName, ratio: Math.min(...fonds.map(f => coulContraste(hex(fg), f))) });
    });
    const scrollers = [...document.querySelectorAll('.modal-body, .club-body, .pitch-container')].filter(visible);
    res.debordScroller = scrollers.map(s => s.scrollWidth - s.clientWidth).filter(x => x > 0);
    return res;
  });
  const ouvrir = async (date, id) => {
    await page.evaluate(async ([date, id]) => {
      let d = soireeCache.get(date) || await (await fetch('soirees/' + date + '.json')).json();
      soireeCache.set(date, d);
      for (const k of COMP_KEYS) if (openMatchModal(id, d, k)) return;
    }, [date, id]);
    await sleep(300);
  };
  const choix = await page.evaluate(async () => {
    // 3 matchs aux couleurs variées + 1 cas proche fabriqué
    const out = [];
    const idx = await (await fetch('soirees/index.json')).json();
    const cible = [];
    for (const l of idx) {
      const d = await (await fetch('soirees/' + l.date + '.json')).json();
      for (const comp of Object.values(d.competitions)) for (const m of comp.matches) {
        if (!(m.lineups && m.lineups.home && m.lineups.home.length && m.momentum && m.momentum.length && m.stats && m.stats.all && m.stats.all.length)) continue;
        const c = couleursMatch(m);
        cible.push({ date: l.date, id: m.match_id, h: c.home.fond, a: c.away.fond, hb: !!c.home.bord, ab: !!c.away.bord, nom: m.home_team.short + '-' + m.away_team.short });
      }
    }
    return cible;
  });
  const prendre = (f) => choix.find(f);
  const A = prendre(x => !x.hb && !x.ab);                       // deux couleurs franches
  const B = prendre(x => x.hb || x.ab) || choix[1];            // un aplat quasi blanc / noir (liseré)
  const C = choix.find(x => x !== A && x !== B && /^#(0|1|2)/.test(x.h)) || choix[2];
  console.log('MATCHS', JSON.stringify([A, B, C]));
  const tous = [];
  for (const [i, M] of [['A', A], ['B', B], ['C', C]]) {
    await ouvrir(M.date, M.id);
    for (const v of ['lineups', 'stats']) {
      await page.evaluate((v) => switchModalView(v), v);
      await sleep(400);
      tous.push({ m: i, v, ...(await mesurer()) });
      await page.screenshot({ path: `${OUT}/${i}-${M.nom}-${v}.png` });
      if (v === 'stats') {   // momentum seul, en haut de l'onglet
        await page.evaluate(() => { document.getElementById('modal-body-content').scrollTop = 0; });
        await page.screenshot({ path: `${OUT}/${i}-${M.nom}-momentum.png`, clip: { x: 0, y: 150, width: 390, height: 420 } });
      }
    }
    await page.evaluate(() => closeMatchModal());
    await sleep(200);
  }
  // cas de couleurs proches fabriqué : les deux maillots portés quasi identiques (donnée modifiée en mémoire, jamais écrite)
  const P = A;
  await page.evaluate(async ([date, id]) => {
    const d = JSON.parse(JSON.stringify(soireeCache.get(date)));
    for (const comp of Object.values(d.competitions)) for (const m of comp.matches) if (m.match_id === id) {
      m.away_team.shirt_color = m.home_team.shirt_color || '#cc0000';
      if (!m.home_team.shirt_color) m.home_team.shirt_color = '#cc0000';
      m.away_team.shirt_color = m.home_team.shirt_color.replace(/.$/, c => (parseInt(c, 16) ^ 1).toString(16));
    }
    soireeCache.set(date, d);
    const t = (d.competitions); for (const k of COMP_KEYS) if (openMatchModal(id, d, k)) return;
  }, [P.date, P.id]);
  await sleep(300);
  const proche = await page.evaluate(([date, id]) => {
    const d = soireeCache.get(date); let r = null;
    for (const comp of Object.values(d.competitions)) for (const m of comp.matches) if (m.match_id === id) { const c = couleursMatch(m); r = { home: c.home, away: c.away, de: coulDeltaE76(c.home.fond, c.away.fond), hs: m.home_team.shirt_color, as: m.away_team.shirt_color }; }
    return r;
  }, [P.date, P.id]);
  console.log('PROCHE', JSON.stringify(proche));
  for (const v of ['lineups', 'stats']) {
    await page.evaluate((v) => switchModalView(v), v); await sleep(400);
    tous.push({ m: 'proche', v, ...(await mesurer()) });
    await page.screenshot({ path: `${OUT}/D-proche-${v}.png` });
  }
  await page.evaluate(() => closeMatchModal()); await sleep(200);
  // fiches de club : un club français, un à couleur sombre, un à couleur claire
  const clubs = await page.evaluate(() => [...clubIndex.values()].filter(c => c.couleurs).map(c => ({ id: c.id, nom: c.nom, f: c.couleurs.principale, fr: c.francais, lum: coulLuminance(c.couleurs.principale) })));
  const pick = [clubs.find(c => c.fr), clubs.find(c => c.lum < 0.06), clubs.find(c => c.lum > 0.5 && c.lum < 0.85)].filter(Boolean);
  for (const c of pick) {
    await page.evaluate((id) => openClub(id), c.id); await sleep(1200);
    for (const v of ['apercu', 'matchs']) {
      await page.evaluate((v) => switchClubView(v), v); await sleep(300);
      tous.push({ m: 'club ' + c.nom, v, ...(await mesurer()) });
      await page.screenshot({ path: `${OUT}/club-${c.nom.replace(/[^A-Za-z0-9]+/g, '_')}-${v}.png` });
    }
    await page.evaluate(() => closeClub()); await sleep(200);
  }
  // accueil (tuiles, cartes)
  await page.evaluate(() => window.scrollTo(0, 0)); await sleep(200);
  await page.screenshot({ path: `${OUT}/accueil.png` });
  tous.push({ m: 'accueil', v: '', ...(await mesurer()) });

  let pire = 99, pireEncre = 99, deb = 0, nTexte = 0, nEncre = 0;
  for (const t of tous) {
    t.texteSurAplat.forEach(x => { pire = Math.min(pire, x.ratio); nTexte++; });
    t.encreSurPage.forEach(x => { pireEncre = Math.min(pireEncre, x.ratio); nEncre++; });
    deb = Math.max(deb, t.debordement, ...(t.debordScroller.length ? t.debordScroller : [0]));
  }
  console.log('RENDU', JSON.stringify({ vues: tous.length, texteSurAplat: { n: nTexte, pire: +pire.toFixed(2) }, encreSurPage: { n: nEncre, pire: +pireEncre.toFixed(2) }, debordementMax: deb, erreursConsole: errs }));
  await browser.close();
  const ok = bilan.sousSeuil.length === 0 && bilan.contrasteTexteMin >= 4.5 && bilan.encreMin >= 4.5 && pire >= 4.5 && pireEncre >= 4.5 && deb <= 0 && errs.length === 0;
  console.log(ok ? 'RESULTAT OK' : 'RESULTAT ECHEC');
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
