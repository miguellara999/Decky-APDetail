# APDetail

Plugin para [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) que muestra a qué
punto de acceso WiFi (BSSID) está conectada la Steam Deck y permite cambiar a otro AP del mismo
SSID. Útil en redes con varios puntos de acceso (mesh, repetidores) cuando la Deck se queda
"pegada" al AP más lejano.

## Qué hace

- Muestra la conexión actual: SSID, BSSID, señal (% y dBm), banda, canal, velocidad e IP.
- Lista los APs visibles con el mismo SSID, ordenados por señal.
- Permite conectarse a un AP concreto fijando su BSSID en el perfil de NetworkManager.
- Permite quitar la fijación para volver al roaming automático.

## SteamOS e iwd (importante)

SteamOS (3.5+) usa **iwd** como backend WiFi de NetworkManager. iwd agrupa los APs por red y
no expone la elección de BSSID a NetworkManager, así que:

- La lista de APs se obtiene directamente del driver con `iw` (NetworkManager solo enseña uno
  por SSID).
- Para cambiar de AP se usa `iwctl debug <dev> roam <bssid>`, que **solo existe si iwd corre en
  modo desarrollador**. El plugin ofrece un botón «Activar modo desarrollador de iwd» que crea el
  drop-in `/etc/systemd/system/iwd.service.d/apdetail-developer.conf` y reinicia iwd; el mismo
  botón pasa a «Revertir…» y deja iwd como estaba. Este modo solo expone comandos extra por D-Bus
  (solo para root); no cambia el escaneo, el roaming ni el consumo.

  Ojo: desinstalar el plugin **no** revierte el modo desarrollador (Decky también llama a
  `_uninstall` al actualizar el plugin). Pulsa «Revertir» antes de desinstalar, o hazlo a mano:

  Equivalente manual:

  ```bash
  sudo mkdir -p /etc/systemd/system/iwd.service.d
  sudo tee /etc/systemd/system/iwd.service.d/apdetail-developer.conf >/dev/null <<'EOF'
  [Service]
  ExecStart=
  ExecStart=/usr/lib/iwd/iwd --developer
  EOF
  sudo systemctl daemon-reload && sudo systemctl restart iwd
  ```

  El WiFi se cae unos segundos y reconecta solo. Para revertirlo, borra ese fichero y repite
  `daemon-reload` + `restart iwd`.

- Con iwd no hay "fijación": tras el cambio, iwd se queda en ese AP hasta que la señal baje de su
  umbral de roaming (−70 dBm por defecto).

En sistemas con wpa_supplicant (no SteamOS), el plugin fija `802-11-wireless.bssid` en el perfil
de NetworkManager; en ese caso el AP queda fijado hasta pulsar «Quitar fijación».

## Desarrollo

Requisitos: Node.js 18+, pnpm.

```bash
pnpm install
pnpm run build     # genera dist/index.js
pnpm run watch     # recompila al guardar
```

### Desplegar en la Deck por SSH

```bash
DECK_HOST=deck@steamdeck ./scripts/deploy.sh
```

### Generar zip para instalar a mano

```bash
./scripts/build-zip.sh   # -> out/APDetail.zip
```

Luego en la Deck: Decky > ⚙ > Desarrollador > «Instalar plugin desde zip».

## Cómo funciona

- **Backend** (`main.py`): usa `nmcli` para listar APs y modificar el perfil de conexión
  (`802-11-wireless.bssid`), e `iw` para obtener señal en dBm y bitrate. Requiere el flag `root`.
- **Frontend** (`src/index.tsx`): React + `@decky/ui`; se refresca cada 10 s mientras el panel
  está abierto.
