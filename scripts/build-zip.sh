#!/usr/bin/env bash
# Compila y genera out/APDetail.zip listo para instalar desde Decky
# (Ajustes de Decky > Desarrollador > Instalar plugin desde zip).
set -euo pipefail

cd "$(dirname "$0")/.."
PLUGIN=APDetail

pnpm run build
rm -rf out && mkdir -p "out/$PLUGIN"
cp -r dist main.py plugin.json package.json README.md "out/$PLUGIN/"
[ -f LICENSE ] && cp LICENSE "out/$PLUGIN/"
rm -f "out/$PLUGIN/dist/index.js.map"

# Empaquetamos con Python para no depender de que `zip` esté instalado.
python3 - "$PLUGIN" <<'PY'
import os, sys, zipfile
name = sys.argv[1]
root = os.path.join("out", name)
with zipfile.ZipFile(f"out/{name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            z.write(p, os.path.relpath(p, "out"))
PY
echo ">> Generado out/$PLUGIN.zip"
