"""Contrôle statique des workflows : chaque bloc `run:` doit passer `bash -n` (les expressions ${{ … }} sont
remplacées par une valeur neutre). Usage : python tools/verifier_workflows.py"""
import glob, re, subprocess, sys, tempfile

try:
    import yaml
except ImportError:  # PyYAML absent : rien à vérifier ici (la CI de GitHub n'en a pas besoin)
    print("[INFO] PyYAML absent : contrôle des workflows ignoré"); sys.exit(0)

erreurs = 0
for f in sorted(glob.glob(".github/workflows/*.yml")):
    doc = yaml.safe_load(open(f, encoding="utf-8"))
    for nom_job, job in (doc.get("jobs") or {}).items():
        for i, etape in enumerate(job.get("steps") or []):
            script = etape.get("run")
            if not script:
                continue
            script = re.sub(r"\$\{\{.*?\}\}", "X", script)
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as t:
                t.write(script)
            r = subprocess.run(["bash", "-n", t.name], capture_output=True, text=True)
            if r.returncode:
                erreurs += 1
                print("[ERREUR] %s / %s / étape %d (%s) :\n%s" % (f, nom_job, i, etape.get("name"), r.stderr.strip()))
print("[OK] blocs run des workflows" if not erreurs else "[ÉCHEC] %d bloc(s) invalide(s)" % erreurs)
sys.exit(1 if erreurs else 0)
