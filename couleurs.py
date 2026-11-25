"""Couleurs des équipes : fonctions PURES (aucun réseau, aucune dépendance), jumelles de bloc `COULEURS` d'index.html.

Règle validée par le propriétaire le 25/11/2026 (docs/etude_fiches_clubs.md, § Couleurs et § Décisions) :
  1. couleur d'une équipe dans un match = maillot PORTÉ dans ce match (`shirt_color` des compositions UEFA) ;
  2. sinon couleur principale du club (`clubs/index.json`, champ `couleurs`, calculée ici par `couleurs_clubs`) ;
  3. sinon repli neutre (bleu domicile, rouge extérieur : les couleurs historiques de la page).
  Garde-fou : si les deux couleurs d'un match sont trop proches (ΔE76 < SEUIL_DE), l'équipe à l'extérieur prend sa
  couleur secondaire (maillot `pl02`), à défaut un repli neutre. Aucune couleur n'est jamais inventée : un champ
  absent reste absent, seul le repli neutre (couleur d'interface, pas une donnée) comble.
  Lisibilité : texte blanc ou noir sur l'aplat selon le meilleur contraste WCAG (>= 4,5 garanti : le pire cas d'un
  fond de luminance relative 0,179 donne 4,58 avec du noir pur) ; liseré pour un aplat quasi blanc (luminance > 0,85)
  ou quasi noir (< 0,04) ; `encre` = la couleur éclaircie / assombrie (mélange vers le texte de la page) jusqu'à
  atteindre 4,5 sur le fond de page, pour les chiffres et noms colorés.

Tout changement ici doit être répercuté dans le bloc `COULEURS` d'index.html (`python couleurs.py --test` compare les deux
implémentations sur des milliers de couleurs avec Node, quand il est disponible).
"""
import json
import math
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

SEUIL_DE = 25.0
SEUIL_TEXTE = 4.5
LUM_BLANC = 0.85
LUM_NOIR = 0.04
NEUTRE_DOM = "#38bdf8"
NEUTRE_EXT = "#f43f5e"
FONDS_PAGE = ["#151c28", "#0b0f17", "#202b3d"]   # --bg-card, --bg-main, --bg-elevated (thème sombre de la page)
BORDS = ["#e2e8f0", "#7c8799", "#1e293b"]
SOURCE = "compositions_uefa"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def hex_valide(h: Any) -> bool:
    return isinstance(h, str) and bool(HEX.match(h))


def hex_rgb(h: str) -> Tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def rgb_hex(r: float, g: float, b: float) -> str:
    def c(x: float) -> int:
        return max(0, min(255, int(x + 0.5)))
    return "#%02x%02x%02x" % (c(r), c(g), c(b))


def _lin(v: int) -> float:
    s = v / 255.0
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(h: str) -> float:
    r, g, b = hex_rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contraste(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def lab(h: str) -> Tuple[float, float, float]:
    """CIELAB (D65) d'un hex sRGB."""
    r, g, b = (_lin(v) for v in hex_rgb(h))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 216.0 / 24389.0 else (24389.0 / 27.0 * t + 16.0) / 116.0
    fx, fy, fz = f(x), f(y), f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def delta_e76(a: str, b: str) -> float:
    la, lb = lab(a), lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb)))


def texte_sur(fond: str) -> str:
    """Texte posé sur l'aplat : blanc ou noir, le plus contrasté (>= 4,5 toujours atteint)."""
    return "#ffffff" if contraste("#ffffff", fond) >= contraste("#000000", fond) else "#000000"


def _page_sombre(fonds: List[str]) -> bool:
    return sum(luminance(f) for f in fonds) / len(fonds) < 0.5


def bord_pour(fond: str, fonds_page: List[str]) -> Optional[str]:
    """Liseré d'un aplat quasi blanc ou quasi noir (sinon None) : le neutre de BORDS qui contraste le plus, au pire,
    avec l'aplat et avec la page."""
    lum = luminance(fond)
    if not (lum > LUM_BLANC or lum < LUM_NOIR):
        return None
    meilleur, score = BORDS[0], -1.0
    for b in BORDS:
        s = min(contraste(b, fond), min(contraste(b, p) for p in fonds_page))
        if s > score + 1e-9:
            meilleur, score = b, s
    return meilleur


def encre_pour(fond: str, fonds_page: List[str]) -> str:
    """Couleur lisible comme TEXTE sur la page : l'aplat tel quel s'il contraste >= 4,5 avec tous les fonds de page,
    sinon mélangé (pas de 5 %) vers le blanc (page sombre) ou le noir (page claire)."""
    cible = "#ffffff" if _page_sombre(fonds_page) else "#000000"
    r0, g0, b0 = hex_rgb(fond)
    r1, g1, b1 = hex_rgb(cible)
    for k in range(0, 21):
        t = k / 20.0
        c = rgb_hex(r0 + (r1 - r0) * t, g0 + (g1 - g0) * t, b0 + (b1 - b0) * t)
        if min(contraste(c, p) for p in fonds_page) >= SEUIL_TEXTE:
            return c
    return cible


def habiller(fond: str, source: str, fonds_page: Optional[List[str]] = None) -> Dict[str, Any]:
    fonds_page = fonds_page or FONDS_PAGE
    return {"fond": fond, "texte": texte_sur(fond), "bord": bord_pour(fond, fonds_page), "encre": encre_pour(fond, fonds_page),
            "source": source}


def _choix(equipe: Dict[str, Any], neutre: str) -> Tuple[str, str]:
    if hex_valide(equipe.get("maillot")):
        return equipe["maillot"].lower(), "maillot"
    if hex_valide(equipe.get("principale")):
        return equipe["principale"].lower(), "club"
    return neutre, "neutre"


def couleurs_match(dom: Dict[str, Any], ext: Dict[str, Any], fonds_page: Optional[List[str]] = None,
                   seuil: float = SEUIL_DE) -> Dict[str, Dict[str, Any]]:
    """`dom` / `ext` = {maillot, principale, secondaire} (chaque clé facultative). Renvoie {home, away} = {fond, texte,
    bord, encre, source}. Voir l'en-tête du module."""
    h, hs = _choix(dom, NEUTRE_DOM)
    a, as_ = _choix(ext, NEUTRE_EXT)
    if delta_e76(h, a) < seuil:
        candidats = []
        if hex_valide(ext.get("secondaire")):
            candidats.append((ext["secondaire"].lower(), "secondaire"))
        candidats += [(NEUTRE_EXT, "neutre"), (NEUTRE_DOM, "neutre")]
        for hexa, src in candidats:
            if delta_e76(h, hexa) >= seuil:
                a, as_ = hexa, src
                break
    return {"home": habiller(h, hs, fonds_page), "away": habiller(a, as_, fonds_page)}


# ------------------------------------------------------------------------------
# Couleur principale d'un club : mode des maillots portés (compositions UEFA)
# ------------------------------------------------------------------------------
KIT_URL = re.compile(r"/Kits/([a-z]{2}\d{2})\.png")
KITS_CLUB = ["pl01", "pl02", "pl03"]


def code_maillot(url: Any) -> Optional[str]:
    """`pl01` / `pl02` / `pl03` (ou `gk01`) lu dans l'URL de l'image UEFA du maillot ; None si illisible."""
    m = KIT_URL.search(url) if isinstance(url, str) else None
    return m.group(1) if m else None


def _mode(valeurs: List[Tuple[str, str]]) -> Optional[str]:
    """Hex le plus fréquent ; à égalité, celui du match le plus récent. `valeurs` = [(date, hex)]."""
    if not valeurs:
        return None
    n: Dict[str, int] = {}
    dernier: Dict[str, str] = {}
    for d, h in valeurs:
        n[h] = n.get(h, 0) + 1
        dernier[h] = max(dernier.get(h, ""), d)
    return sorted(n, key=lambda h: (-n[h], tuple(-ord(c) for c in dernier[h]), h))[0]


def couleurs_clubs(observations: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """`observations` = {match_id: {"d": date, "e": {team_id: [code_maillot|None, hex|None]}}} (maillots portés, compositions
    UEFA). Par club : `principale` = mode des maillots `pl01` (à défaut `pl02`, puis `pl03`), `secondaire` = mode des `pl02`
    (à défaut `pl03`) si la principale vient de `pl01`, `maillot` = code de la principale, `nb_matchs` = matchs qui la
    fondent. Un club sans maillot lisible n'apparaît pas (rien n'est inventé)."""
    par_club: Dict[str, Dict[str, List[Tuple[str, str]]]] = {}
    for obs in observations.values():
        date = str((obs or {}).get("d") or "")
        for tid, v in ((obs or {}).get("e") or {}).items():
            kit, h = (v + [None, None])[:2] if isinstance(v, list) else (None, None)
            if kit in KITS_CLUB and hex_valide(h):
                par_club.setdefault(str(tid), {}).setdefault(kit, []).append((date, h.lower()))
    out: Dict[str, Dict[str, Any]] = {}
    for tid, kits in par_club.items():
        ordre = [k for k in KITS_CLUB if k in kits]
        k0 = ordre[0]
        principale = _mode(kits[k0])
        reste = [k for k in ordre[1:]] if k0 == "pl01" else []
        secondaire = _mode(kits[reste[0]]) if reste else None
        out[tid] = {"principale": principale, "secondaire": secondaire, "maillot": k0, "nb_matchs": len(kits[k0]),
                    "source": SOURCE}
    return out


# ------------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------------------
def _bloc_js(chemin: str = "index.html") -> str:
    with open(chemin, "r", encoding="utf-8") as f:
        t = f.read()
    m = re.search(r"// ===== COULEURS : début =====\n(.*?)// ===== COULEURS : fin =====", t, re.S)
    if not m:
        raise AssertionError("bloc COULEURS introuvable dans index.html")
    return m.group(1)


def _parite_js() -> str:
    """Compare Python et le bloc JS d'index.html (Node) sur des couleurs pseudo-aléatoires reproductibles."""
    import random
    import shutil
    import tempfile
    node = shutil.which("node")
    if not node or not os.path.exists("index.html"):
        return "parité JS ignorée (node ou index.html absent)"
    rnd = random.Random(2511)
    hexes = ["#000000", "#ffffff", "#38bdf8", "#f43f5e", "#ff0000", "#c63349", "#ffe600", "#1e3a8a"] + [
        "#%06x" % rnd.randrange(0x1000000) for _ in range(1500)]
    paires = [[rnd.choice(hexes), rnd.choice(hexes)] for _ in range(600)]
    matchs = [[{"maillot": rnd.choice(hexes + [None]), "principale": rnd.choice(hexes + [None]), "secondaire": rnd.choice(hexes + [None])},
               {"maillot": rnd.choice(hexes + [None]), "principale": rnd.choice(hexes + [None]), "secondaire": rnd.choice(hexes + [None])}]
              for _ in range(600)]
    attendu = {
        "tex": [texte_sur(h) for h in hexes], "bord": [bord_pour(h, FONDS_PAGE) for h in hexes],
        "enc": [encre_pour(h, FONDS_PAGE) for h in hexes],
        "de": [round(delta_e76(a, b), 6) for a, b in paires], "ct": [round(contraste(a, b), 6) for a, b in paires],
        "match": [couleurs_match(d, e) for d, e in matchs],
    }
    prog = _bloc_js() + """
const E = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const S = { hexes: E.hexes, paires: E.paires, matchs: E.matchs };
const r = {
  tex: S.hexes.map(coulTexteSur), bord: S.hexes.map(h => coulBordPour(h, COUL_FONDS_PAGE)),
  enc: S.hexes.map(h => coulEncrePour(h, COUL_FONDS_PAGE)),
  de: S.paires.map(p => Math.round(coulDeltaE76(p[0], p[1]) * 1e6) / 1e6),
  ct: S.paires.map(p => Math.round(coulContraste(p[0], p[1]) * 1e6) / 1e6),
  match: S.matchs.map(p => coulChoisir(p[0], p[1], COUL_FONDS_PAGE)),
};
process.stdout.write(JSON.stringify(r));
"""
    with tempfile.TemporaryDirectory() as d:
        fj, fe = os.path.join(d, "p.js"), os.path.join(d, "e.json")
        with open(fj, "w", encoding="utf-8") as f:
            f.write(prog)
        with open(fe, "w", encoding="utf-8") as f:
            json.dump({"hexes": hexes, "paires": paires, "matchs": matchs}, f)
        res = subprocess.run([node, fj, fe], capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise AssertionError("Node a échoué : " + res.stderr[-400:])
    js = json.loads(res.stdout)
    for cle in attendu:
        a, b = attendu[cle], js[cle]
        if cle == "match":   # le JS ne porte que home / away avec les mêmes clés
            for i, (x, y) in enumerate(zip(a, b)):
                assert x == y, f"parité {cle}[{i}] : python {x} / js {y} pour {matchs[i]}"
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                assert x == y, f"parité {cle}[{i}] : python {x} / js {y}"
    return f"parité Python / JS : {len(hexes)} couleurs, {len(paires)} paires, {len(matchs)} matchs identiques"


def _tests() -> None:
    def check(cond: bool, msg: str) -> None:
        if not cond:
            raise AssertionError(msg)

    # contraste / luminance : valeurs de référence WCAG
    check(abs(contraste("#ffffff", "#000000") - 21.0) < 1e-9, "contraste blanc/noir")
    check(abs(luminance("#ffffff") - 1.0) < 1e-9 and luminance("#000000") == 0.0, "luminance extrêmes")
    check(abs(contraste("#777777", "#ffffff") - 4.48) < 0.01, "contraste #777 / blanc ~ 4,48")
    # ΔE76 : blanc / noir = 100 ; identiques = 0 ; Bayern / Arsenal quasi identiques (cas réel du plan)
    check(abs(delta_e76("#ffffff", "#000000") - 100.0) < 0.01, "ΔE blanc/noir")
    check(delta_e76("#c8102e", "#c8102e") == 0.0, "ΔE identique")
    check(delta_e76("#dc052d", "#db0a1c") < 25 and delta_e76("#38bdf8", "#f43f5e") > 25, "ΔE proches / éloignées")
    # texte : au pire (fond de luminance ~ 0,179) le noir pur donne >= 4,5 ; vérifié sur toute la ligne de gris
    pire = min(max(contraste("#ffffff", "#%02x%02x%02x" % (v, v, v)), contraste("#000000", "#%02x%02x%02x" % (v, v, v))) for v in range(256))
    check(pire >= SEUIL_TEXTE, f"texte lisible sur tous les gris (pire {pire:.2f})")
    for h in ("#ff0000", "#00ff00", "#0000ff", "#ffe600", "#7f7f7f", "#c63349", "#1e3a8a"):
        check(contraste(texte_sur(h), h) >= SEUIL_TEXTE, f"texte sur {h}")
    # liseré : seulement les aplats quasi blancs / quasi noirs
    check(bord_pour("#ffffff", FONDS_PAGE) is not None and bord_pour("#000000", FONDS_PAGE) is not None, "liseré blanc / noir")
    check(bord_pour("#ff0000", FONDS_PAGE) is None and bord_pour("#38bdf8", FONDS_PAGE) is None, "pas de liseré pour une couleur")
    check(bord_pour("#0a0a0a", FONDS_PAGE) == "#e2e8f0", "liseré clair pour un aplat noir sur page sombre")
    check(bord_pour("#fafafa", FONDS_PAGE) == "#7c8799", "liseré gris moyen pour un aplat blanc")
    # encre : toujours >= 4,5 sur tous les fonds de page
    for h in ("#000000", "#1e3a8a", "#c8102e", "#ffffff", "#0b0f17"):
        check(min(contraste(encre_pour(h, FONDS_PAGE), p) for p in FONDS_PAGE) >= SEUIL_TEXTE, f"encre de {h}")
    check(encre_pour("#ffffff", FONDS_PAGE) == "#ffffff", "encre : une couleur déjà lisible ne change pas")
    # choix : maillot porté > principale du club > neutre
    c = couleurs_match({"maillot": "#ff0000", "principale": "#00ff00"}, {"principale": "#0000ff"})
    check(c["home"]["fond"] == "#ff0000" and c["home"]["source"] == "maillot", "maillot porté prioritaire")
    check(c["away"]["fond"] == "#0000ff" and c["away"]["source"] == "club", "couleur principale du club")
    c = couleurs_match({}, {})
    check(c["home"]["fond"] == NEUTRE_DOM and c["away"]["fond"] == NEUTRE_EXT and c["home"]["source"] == "neutre", "repli neutre sans donnée")
    c = couleurs_match({"maillot": "zzz", "principale": "#12345"}, {"maillot": None})
    check(c["home"]["source"] == "neutre" and c["away"]["source"] == "neutre", "hex invalides ignorés")
    # couleurs proches : l'extérieur prend sa secondaire, sinon le neutre ; le domicile ne change jamais
    c = couleurs_match({"principale": "#dc052d"}, {"principale": "#db0a1c", "secondaire": "#ffffff"})
    check(c["home"]["fond"] == "#dc052d" and c["away"]["fond"] == "#ffffff" and c["away"]["source"] == "secondaire", "proches : secondaire")
    c = couleurs_match({"maillot": "#1e3a8a"}, {"maillot": "#1c3c88"})
    check(c["away"]["fond"] == NEUTRE_EXT and c["away"]["source"] == "neutre", "proches sans secondaire : neutre")
    c = couleurs_match({"maillot": "#1e3a8a"}, {"maillot": "#1c3c88", "secondaire": "#203a8c"})
    check(c["away"]["fond"] == NEUTRE_EXT, "proches, secondaire aussi proche : neutre")
    c = couleurs_match({"maillot": "#dc052d"}, {"maillot": "#db0a1c"})   # rouge contre rouge : le neutre rouge est trop proche aussi
    check(c["away"]["fond"] == NEUTRE_DOM, "rouge contre rouge sans secondaire : repli bleu")
    c = couleurs_match({"maillot": "#f43f5e"}, {})   # extérieur neutre rouge, domicile rouge : bascule sur le bleu
    check(delta_e76(c["home"]["fond"], c["away"]["fond"]) >= SEUIL_DE and c["away"]["fond"] == NEUTRE_DOM, "neutre rouge évité")
    # le garde-fou garantit l'écart minimal dans tous les cas tirés
    import random
    rnd = random.Random(7)
    for _ in range(2000):
        hx = lambda: "#%06x" % rnd.randrange(0x1000000)
        d = {"maillot": hx() if rnd.random() < .7 else None, "principale": hx() if rnd.random() < .7 else None}
        e = {"maillot": hx() if rnd.random() < .7 else None, "principale": hx() if rnd.random() < .7 else None, "secondaire": hx() if rnd.random() < .6 else None}
        r = couleurs_match(d, e)
        check(delta_e76(r["home"]["fond"], r["away"]["fond"]) >= SEUIL_DE or all(
            delta_e76(r["home"]["fond"], x) < SEUIL_DE for x in (NEUTRE_EXT, NEUTRE_DOM)), "écart minimal ou plus aucun repli possible")
        for k in ("home", "away"):
            check(contraste(r[k]["texte"], r[k]["fond"]) >= SEUIL_TEXTE, "texte lisible sur l'aplat")
    # codes de maillot
    check(code_maillot("https://img.uefa.com/imgml/teamkits/1/2027/50129/Kits/pl01.png") == "pl01", "code pl01")
    check(code_maillot("https://x/Kits/gk01.png") == "gk01" and code_maillot(None) is None and code_maillot("rien") is None, "codes divers")
    # agrégation : mode des pl01, secondaire = mode des pl02, ex æquo -> match le plus récent, rien d'inventé
    obs = {
        "1": {"d": "2026-09-01", "e": {"10": ["pl01", "#c63349"], "20": ["pl02", "#ffffff"]}},
        "2": {"d": "2026-09-15", "e": {"10": ["pl01", "#ff0000"], "30": ["pl02", "#112233"]}},
        "3": {"d": "2026-10-01", "e": {"10": ["pl01", "#ff0000"], "20": ["pl01", "#0000ff"]}},
        "4": {"d": "2026-10-10", "e": {"10": ["pl02", "#ffffff"], "20": ["pl01", "#0000aa"]}},
        "5": {"d": "2026-10-20", "e": {"40": [None, None], "50": ["gk01", "#00ff00"], "60": ["pl01", "pas-un-hex"]}},
        "6": {"d": "2026-10-21", "e": {"20": ["pl02", "#eeeeee"]}},
    }
    r = couleurs_clubs(obs)
    check(r["10"]["principale"] == "#ff0000" and r["10"]["secondaire"] == "#ffffff" and r["10"]["nb_matchs"] == 3 and r["10"]["maillot"] == "pl01", f"club 10 : {r['10']}")
    check(r["20"]["principale"] == "#0000aa" and r["20"]["nb_matchs"] == 2, "club 20 : ex æquo -> match le plus récent")
    check(r["20"]["secondaire"] == "#eeeeee", "club 20 : secondaire = mode des pl02 (ex æquo -> le plus récent)")
    check(r["30"]["principale"] == "#112233" and r["30"]["secondaire"] is None and r["30"]["maillot"] == "pl02", "club sans pl01 : pl02, sans secondaire")
    check("40" not in r and "50" not in r and "60" not in r, "aucune valeur inventée pour un maillot illisible")
    check(all(v["source"] == SOURCE for v in r.values()), "source")
    print("[OK] couleurs : tests purs")
    print("[OK] " + _parite_js())


if __name__ == "__main__":
    if "--test" in sys.argv:
        _tests()
    else:
        print(__doc__)
