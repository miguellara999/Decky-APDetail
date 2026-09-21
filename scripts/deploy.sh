#!/usr/bin/env bash
# Compila el plugin y lo despliega en la Steam Deck por SSH.
#
# Uso:  DECK_HOST=deck@192.168.1.50 ./scripts/deploy.sh
#       (o exporta DECK_HOST en tu shell / en un fichero .env)
#
# Requisitos en la Deck: SSH habilitado y contraseña de sudo configurada
# (`passwd` en modo escritorio). Se pedirá la contraseña de sudo al final.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && source .env
: "${DECK_HOST:?Define DECK_HOST, p.ej. DECK_HOST=deck@steamdeck}"

PLUGIN=APDetail
REMOTE_TMP="/tmp/$PLUGIN"
REMOTE_DIR="/home/deck/homebrew/plugins/$PLUGIN"

echo ">> Compilando..."
pnpm run build

echo ">> Copiando a $DECK_HOST:$REMOTE_TMP"
ssh "$DECK_HOST" "rm -rf '$REMOTE_TMP' && mkdir -p '$REMOTE_TMP'"
rsync -az --delete \
  dist main.py plugin.json package.json README.md oui.json.gz \
  "$DECK_HOST:$REMOTE_TMP/"

echo ">> Instalando en $REMOTE_DIR y reiniciando Decky (pedirá la contraseña de sudo)"
ssh -t "$DECK_HOST" "sudo bash -c '
  rm -rf \"$REMOTE_DIR\" &&
  mv \"$REMOTE_TMP\" \"$REMOTE_DIR\" &&
  chown -R root:root \"$REMOTE_DIR\" &&
  chmod -R 555 \"$REMOTE_DIR\" &&
  systemctl restart plugin_loader
'"
echo ">> Listo. Abre el menú de acceso rápido (…) en la Deck."
