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

> Al fijar un BSSID, NetworkManager **no** cambiará de AP automáticamente aunque te alejes.
> Usa «Quitar fijación» para volver al comportamiento normal.

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
