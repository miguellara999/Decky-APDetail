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
(cd out && zip -rq "$PLUGIN.zip" "$PLUGIN")
echo ">> Generado out/$PLUGIN.zip"
