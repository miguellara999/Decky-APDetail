# APDetail

Plugin para [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) que muestra a qué
punto de acceso WiFi (BSSID) está conectada la Steam Deck y permite cambiar a otro AP del mismo
SSID. Útil en redes con varios puntos de acceso (mesh, repetidores) cuando la Deck se queda
"pegada" al AP más lejano.

## Qué hace

- Muestra la conexión actual: SSID, BSSID, fabricante del AP, señal (dBm en vivo y %), banda,
  canal, velocidad e IP.
- Lista los APs visibles con el mismo SSID, ordenados por señal, con fabricante, MAC, banda,
  canal, dBm/% y antigüedad de la medición. Un interruptor permite ver todas las redes.
- Permite cambiarse a un AP concreto pulsando sobre él (reasociación rápida, sin cortar la
  conexión).

## Uso

1. Abre el menú de acceso rápido (…) → APDetail.
2. La primera vez pulsa **«Activar modo desarrollador de iwd»** (necesario en SteamOS para poder
   elegir AP; ver más abajo). El WiFi se corta unos segundos y reconecta solo.
3. Pulsa sobre el AP al que quieras cambiarte. Un aviso confirma el cambio y el BSSID de arriba
   se actualiza.

Con el panel abierto la lista se refresca cada 10 s y cada 30 s hace un escaneo dirigido a los
canales de tu SSID; «Volver a escanear» hace uno completo. Al cerrar el panel no se escanea.

Sobre la señal: compara en **dBm** (misma fuente y escala para todos los APs; el del AP en uso
es en vivo). Diferencias menores de ~6 dB son ruido. «hace N s» indica que el dato viene del
último escaneo en que se oyó ese AP; «visto hace N s» que el kernel ya lo caducó y se muestra
de memoria (hasta 3 min).

## SteamOS e iwd (importante)

SteamOS (3.5+) usa **iwd** como backend WiFi de NetworkManager. iwd agrupa los APs por red y
no expone la elección de BSSID a NetworkManager, así que:

- La lista de APs se obtiene directamente del driver con `iw` (NetworkManager solo enseña uno
  por SSID).
- Para cambiar de AP se usa `iwctl debug <dev> roam <bssid>`, que **solo existe si iwd corre en
  modo desarrollador**. El plugin ofrece un botón «Activar modo desarrollador de iwd» que crea el
  drop-in `/etc/systemd/system/iwd.service.d/apdetail-developer.conf` y reinicia iwd; el mismo
  botón pasa a «Revertir…» y deja iwd como estaba. Este modo expone comandos extra por D-Bus
  (solo para root) y **desactiva el autoconnect de iwd** (`station_create` en `src/station.c`),
  lo que haría que la Deck no reconectase sola tras suspender. El plugin lo compensa: un
  vigilante en segundo plano reactiva `AutoConnect` (propiedad de `StationDebug`) siempre que la
  encuentra desactivada. Escaneo, roaming y consumo no cambian.

  Al **desinstalar** el plugin, el modo desarrollador se revierte solo: se elimina el drop-in y
  iwd se reinicia en modo normal 90 s después (reconecta por sí mismo). Al **actualizar** el
  plugin no pasa nada: la versión nueva cancela ese reinicio.

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

## Documentación técnica

Ver [DESARROLLO.md](DESARROLLO.md) para arquitectura, decisiones y depuración.

## Cómo funciona (resumen)

- **Backend** (`main.py`, corre como root): `nmcli` para el estado, `iw` para la lista de BSS y la
  señal en vivo, `iwctl`/`busctl` (API `StationDebug` de iwd) para cambiar de AP, escanear canales
  concretos y mantener el autoconnect. Fabricante por base OUI del IEEE embebida (offline).
- **Frontend** (`src/index.tsx`): React + `@decky/ui`.
- Probado en SteamOS 3.7 (iwd) con una red de dos APs (devolo + MikroTik) en el mismo SSID.
