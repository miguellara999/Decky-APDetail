# APDetail — Notas de desarrollo

Documento de referencia para retomar el plugin. Explica cómo está montado, por qué se tomaron
ciertas decisiones (sobre todo lo de iwd) y cómo depurar en la Steam Deck.

## 1. Qué hace y por qué existe

En redes con varios puntos de acceso bajo el mismo SSID (mesh, repetidores, PLC con WiFi) la
Deck a veces se queda "pegada" al AP más lejano. Steam no muestra a qué AP estás conectado ni
permite elegir. El plugin:

1. Muestra el AP actual: BSSID, fabricante, señal (% y dBm), banda, canal, bitrate, IP.
2. Lista los demás APs del mismo SSID (y opcionalmente todas las redes).
3. Permite cambiarse a un AP concreto.

Red de referencia con la que se desarrolló (2 APs, 2 fabricantes):

| BSSID | Fabricante | Radios |
|---|---|---|
| `AA:BB:CC:11:22:42/43` | devolo AG | 2.4 GHz + 5 GHz |
| `DD:EE:FF:33:44:03/04` | MikroTik (Routerboard.com) | 5 GHz + 2.4 GHz (SSID oculto) |

## 2. Estructura del repo

```
main.py               Backend Python (corre como root dentro de Decky)
src/index.tsx         Frontend React (@decky/ui + @decky/api)
plugin.json           Metadatos Decky. flags: ["root"] es imprescindible
oui.json.gz           Base de datos OUI → fabricante (IEEE), ~600 KB
scripts/build-zip.sh  Compila y genera out/APDetail.zip (instalable desde Decky)
scripts/deploy.sh     Compila y despliega por SSH (DECK_HOST=deck@ip)
scripts/build-oui.py  Regenera oui.json.gz descargando los CSV del IEEE
.devtest/             (gitignored) stub de `decky` y scripts para probar main.py en el PC
```

Compilación: `pnpm install && pnpm run build` → `dist/index.js` (rollup vía `@decky/rollup`).

## 3. Entorno de desarrollo (gotchas)

- **VS Code en Flatpak**: Claude Code corre dentro del sandbox y no ve `node`, `pnpm`, `nmcli`
  ni `pacman`. Hay que ejecutar en el host: `flatpak-spawn --host sh -c 'cd … && pnpm run build'`.
  El `/tmp` del sandbox no es visible desde el host: los ficheros que el host deba leer van
  dentro del proyecto (p. ej. `.devtest/`).
- **pnpm 11** ya no lee el campo `pnpm` de `package.json`; la regla `peerDependencyRules` vive en
  `pnpm-workspace.yaml`.
- **`"jsx": "react"`** en `tsconfig.json` obliga a `import React from "react"` en `index.tsx`,
  aunque no se use explícitamente.
- No hay `zip` en el host: `build-zip.sh` empaqueta con Python.
- Probar el backend sin la Deck: `.devtest/decky.py` es un stub con `logger`,
  `DECKY_PLUGIN_DIR` y `DECKY_PLUGIN_SETTINGS_DIR`; los scripts hacen `sys.path.insert(0, "..")`
  e importan `main`. `nmcli`/`iw` del PC sirven para probar el parseo (en el PC NM usa
  wpa_supplicant, así que la parte iwd no se puede probar aquí).

## 4. Cómo funciona el backend (`main.py`)

Todos los comandos se lanzan con `_run()` (subprocess async, `LC_ALL=C` para que la salida no
esté localizada, `PATH` explícito porque corremos como root con entorno mínimo).

### Detección del backend WiFi

`_wifi_backend()` → `"iwd"` si `systemctl is-active iwd` está activo, si no `"wpa"`. Se cachea.
**SteamOS ≥ 3.5 usa iwd**; esto condiciona todo lo demás.

### Estado (`get_status`)

1. `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status` → interfaz wifi y perfil activo.
2. `iw dev <dev> link` → BSSID real, señal dBm, freq, rx/tx bitrate.
3. `nmcli -g IP4.ADDRESS dev show <dev>` → IP.
4. Con iwd: `iwd_dev_mode` (¿existe la interfaz debug?) e `iwd_dropin` (¿el drop-in es nuestro?).
   Con wpa: `802-11-wireless.bssid` del perfil (`pinned_bssid`).
5. Completa SSID/canal/señal % con la entrada `in_use` de la lista de APs.

### Lista de APs (`scan` → `_list_aps`)

Se **fusionan dos fuentes** por BSSID:

- `_list_aps_nm`: `nmcli -t -f IN-USE,BSSID,SSID,SIGNAL,FREQ,CHAN,RATE,SECURITY dev wifi list
  ifname <dev> --rescan yes|no`. En modo terse los `:` del BSSID vienen escapados como `\:`,
  de ahí `_split_terse()`. Si NM rechaza el rescan (lo limita en frecuencia) se usa la caché.
- `_iw_scan`: `iw dev <dev> scan` (fuerza escaneo; suele fallar con *Device or resource busy*
  si NM está escaneando) y como fallback `iw dev <dev> scan dump`. Se parsean los bloques `BSS`,
  `freq`, `signal`, `SSID`, `DS Parameter set`/`primary channel`, `RSN`/`WPA`. SSID oculto sale
  como `\x00\x00…` y se normaliza a `""`. dBm → % con `(dBm + 100) * 2`.

**Por qué hace falta `iw`**: con backend iwd, `nmcli dev wifi list` **muestra un solo BSSID por
SSID** (iwd modela "redes", no "BSS"). El driver sí ve todos los APs; `iw` los recupera. En el
log aparece `iw aporta N APs que NM no listaba` cuando esto ocurre.

Cada AP lleva `source: "nm" | "iw"`, `vendor` (OUI) y `band` (calculada de la frecuencia).
`same_ssid` filtra por el SSID del AP `in_use`.

### Señal: una sola fuente y una sola escala

Síntoma que llevó a esto: "el otro AP siempre parece tener más señal; cambio y se invierten las
tornas sin moverme". Causa: el AP en uso tomaba el % de `nmcli` (iwd → NM, señal de la *red*,
fórmula de NM, dato viejo) y el resto el dBm de `iw scan dump` con una fórmula distinta y más
generosa, además congelado desde el último escaneo (estando asociado, el driver solo refresca el
AP propio con cada beacon).

Ahora:
- **dBm del driver para todos** (`iw scan dump`, campo `signal_dbm`), y para el AP en uso el
  valor **en vivo** de `iw dev <dev> link` (`age_ms = 0`).
- **Un único %**: fórmula de NetworkManager (`_dbm_to_percent`: −40 dBm → 100 %, −100 → 0 %,
  lineal), que es la de las barras de Steam.
- **Antigüedad** (`age_ms`, de `last seen: N ms ago`) mostrada como "hace N s" si supera 3 s.
- **Escaneo real vía iwd** (`_trigger_scan`): `iwctl station <dev> scan` y espera a que
  `iwctl station <dev> show` diga `Scanning no` (máx. 10 s; la salida puede llevar códigos ANSI,
  se limpian con `_ANSI`). Con wpa_supplicant se sigue usando `iw scan`.

Sobre la fiabilidad en general: el RSSI oscila ±3-5 dB por ruido/multipath incluso quieto;
diferencias menores de ~6 dB no significan nada. Comparar siempre en dBm, no en %.

### Cambiar de AP (`connect_bssid`)

- **iwd** (`_connect_bssid_iwd`): `iwctl debug <dev> roam <bssid>` (reasociación rápida sin
  perder la conexión); si falla, `iwctl debug <dev> connect <bssid>`. Luego se espera hasta 10 s
  a que `iw link` refleje el nuevo BSSID. Requiere **modo desarrollador de iwd** (ver §5).
  No hay "fijación": iwd se queda en ese AP hasta que la señal baje de su umbral de roaming
  (−70 dBm por defecto) y vuelva a decidir por sí mismo.
- **wpa_supplicant** (`_connect_bssid_nm`): `nmcli connection modify <perfil>
  802-11-wireless.bssid <bssid>` + `connection up`. Si `up` falla, se revierte el pin para no
  dejar el perfil inutilizable. `clear_bssid` quita el pin. **Con iwd NM ignora esta propiedad**,
  por eso el enfoque original no servía en la Deck.

### Fabricante (`OuiDb`)

`oui.json.gz` es un dict `prefijo hex → organización` con los registros MA-L (24 bits),
MA-M (28) y MA-S (36) del IEEE. La búsqueda prueba 9, 7 y 6 caracteres hex. Las MACs con el bit
*locally administered* se marcan como "MAC local (sin fabricante)". Se carga en `_main` en un
executor para no bloquear. Regenerar: `python3 scripts/build-oui.py`.

## 5. iwd y el modo desarrollador (lo más delicado)

`iwctl debug …` solo existe si iwd arranca con `--developer` (`-E`). Ese flag registra
interfaces D-Bus extra (`StationDebug`: roam, connect, get-networks, autoconnect), restringidas a
root, y tiene **un efecto secundario importante**: en `station_create()` (`src/station.c`) iwd
pone `autoconnect = false` cuando está en modo desarrollador. Consecuencia: tras suspender la Deck
(o tras reiniciar iwd) no reconecta sola; hay que entrar al menú WiFi y elegir la red (sin clave).

Mitigación (`_autoconnect_watchdog`, tarea asyncio creada en `_main` y cancelada en `_unload`):
cada 4 s lee la propiedad `AutoConnect` de `net.connman.iwd.StationDebug` con
`busctl get-property net.connman.iwd /net/connman/iwd/<phy>/<ifindex> …` y, si está a `false`,
la pone a `true` con `busctl set-property … AutoConnect b true`. El object path se descubre con
`busctl tree net.connman.iwd --list` y se invalida si falla la lectura (la estación se recrea
tras suspender). Sin modo desarrollador la propiedad no existe y el bucle duerme 15 s.
`set_iwd_dev_mode(True)` también activa `AutoConnect` justo tras reiniciar iwd.
Escaneo, roaming, logging y consumo no cambian.

Fuente consultada: mirror de iwd en GitHub (`kernelorg-mirror/network_wireless_iwd`),
`src/station.c` y `doc/station-debug-api.txt` (git.kernel.org bloquea las descargas automáticas).

El plugin lo activa/revierte con `set_iwd_dev_mode(enable)`:

1. Escribe (o borra) el drop-in `/etc/systemd/system/iwd.service.d/apdetail-developer.conf`:
   ```ini
   [Service]
   ExecStart=
   ExecStart=/usr/lib/iwd/iwd --developer
   ```
2. `systemctl daemon-reload && systemctl restart iwd`.
3. Espera 8 s a que NM reconecte; si no, lanza `nmcli connection up <perfil>` (NetworkManager
   con backend iwd no siempre reasocia cuando iwd se reinicia debajo — en la primera prueba hubo
   que reconectar a mano desde el menú de la Deck; la clave no se perdió).

Decisiones:

- El botón solo ofrece "Revertir" si el drop-in es nuestro (`iwd_dropin`), para no tocar una
  configuración ajena.
- **Revertir al desinstalar** (`_uninstall`). Restricciones de Decky (vistas en
  `browser.py`/`plugin.py`/`sandboxed_plugin.py`): `_install` llama a `uninstall_plugin` →
  `stop(uninstall=True)` también al **actualizar**, y tras el mensaje manda `SIGTERM` y a los
  **5 s** `SIGKILL`. No se puede distinguir actualización de desinstalación ni reiniciar iwd ahí.
  Solución:
  1. `_uninstall` (solo operaciones instantáneas): programa con `systemd-run --on-active=90
     --unit=apdetail-iwd-revert sh -c 'systemctl daemon-reload; systemctl restart iwd'`, borra
     el drop-in y escribe la marca `DECKY_PLUGIN_SETTINGS_DIR/iwd-dev-mode-pending` (el
     directorio de ajustes sobrevive a ambos casos).
  2. `_main` → `_resume_after_update()`: si hay marca, la borra, para el timer
     (`systemctl stop apdetail-iwd-revert.timer`) y, si iwd sigue en modo desarrollador,
     recrea el drop-in + `daemon-reload` (sin reiniciar iwd: ya está en dev mode).
  3. Si nadie cancela (desinstalación real), a los 90 s iwd se reinicia en modo normal y, con
     autoconnect por defecto, reconecta solo.
  Test de esta lógica con stubs: `.devtest/uninstall_test.py`.
- El drop-in vive en `/etc`, que en SteamOS persiste entre actualizaciones del sistema.

Pendiente de comprobar: el `ExecStart` original de iwd en SteamOS se sobrescribió con la ruta de
Arch (`/usr/lib/iwd/iwd`) sin haber visto el unit de la Deck. Funciona, pero si en algún momento
falla, mirar `systemctl cat iwd` en la Deck y copiar los argumentos originales al drop-in.

## 6. Frontend (`src/index.tsx`)

- `callable<[args], Result>("metodo")` de `@decky/api` para cada método del backend.
- Al montar: `refresh(true)` (escaneo real) y luego un `setInterval` cada 10 s con
  `refresh(false)` (caché). El intervalo se limpia al desmontar.
- Estado: `status`, `sameSsid`, `allAps`, `showAll` (toggle "Mostrar todas las redes"), `busy`
  (BSSID en curso, `"clear"` o `"iwd"`), `scanning`.
- Cada AP es un `ButtonItem` con título = SSID (o "(SSID oculto)") y descripción
  `fabricante · MAC · banda · canal N · %señal ▂▄▆█`. Deshabilitado si está en uso o, en modo
  "todas las redes", si no es del SSID actual (fijar otro SSID rompería la conexión).
- Botón iwd: "Activar modo desarrollador de iwd" ↔ "Revertir modo desarrollador de iwd".
- Botón "Quitar fijación" solo aparece con backend wpa y BSSID fijado.
- Feedback siempre por `toaster.toast`.

## 7. Depurar en la Deck

Logs del backend: `/home/deck/homebrew/logs/APDetail/<fecha>.log` (uno por carga del plugin).
Líneas útiles: `Backend WiFi:`, `iw aporta N APs…`, `scan(rescan=…): … same_ssid=[…]`,
`Roam OK: A -> B`, `iwctl roam falló…`, `Drop-in creado/eliminado`.

Comandos para comparar con lo que ve el plugin:

```bash
nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status
nmcli dev wifi list --rescan yes                      # solo 1 BSSID por SSID con iwd
sudo iw dev wlan0 scan | grep -E "^BSS|SSID:|freq:|signal:"
iw dev wlan0 link                                     # BSSID real actual
iwctl station wlan0 show
iwctl station wlan0 get-bsses "<SSID>"                # BSS por red, según iwd
iwctl debug wlan0 get-networks                        # falla si no hay modo desarrollador
systemctl cat iwd                                     # unit + drop-in
systemctl list-timers apdetail-iwd-revert.timer       # reinicio diferido pendiente tras desinstalar
busctl tree net.connman.iwd --list                    # object path de la estación (/net/connman/iwd/N/M)
busctl get-property net.connman.iwd /net/connman/iwd/0/3 net.connman.iwd.StationDebug AutoConnect
sudo iwctl debug wlan0 roam <bssid>                   # lo que hace el plugin al pulsar un AP
```

Instalar un zip: Decky → ⚙ → Desarrollador → "Instalar plugin desde zip". Reinstalar encima
funciona (Decky desinstala e instala).

## 8. Historia de decisiones (resumen cronológico)

1. Primer enfoque: `nmcli` + fijar `802-11-wireless.bssid`. Funcionaba en el PC.
2. En la Deck solo aparecía un AP por SSID → NetworkManager usa **iwd**, que agrupa por red.
   Se añadió el escaneo con `iw` y la fusión de resultados.
3. Al descubrir que iwd ignora el BSSID fijado, se cambió a `iwctl debug roam`, que exige el
   modo desarrollador → botón activar/revertir con drop-in de systemd.
4. Tras el primer reinicio de iwd hubo que reconectar a mano → el plugin ahora hace
   `nmcli connection up` si NM no reasocia en 8 s.
5. Fabricante por OUI (IEEE) embebido y offline, a petición.
6. Tras suspender, la Deck dejó de reconectar sola → el modo desarrollador desactiva el
   autoconnect de iwd (visto en el código fuente). Vigilante por D-Bus que lo reactiva.
7. Revertir al desinstalar sin romper las actualizaciones: timer transitorio de systemd + marca.
8. La señal "se invertía" al cambiar de AP → fuentes/escalas mezcladas. dBm del driver para todos,
   en vivo para el AP en uso, % con la fórmula de NM, antigüedad visible y escaneo vía iwd.

## 9. Ideas para más adelante

- Marcar en la lista el AP "recomendado" (mejor señal en 5 GHz).
- Auto-roam opcional: si otro AP del mismo SSID supera al actual en X dB durante N segundos,
  cambiar solo. Cuidado con el ping-pong.
- Mostrar el estado del modo desarrollador de iwd también cuando no hay conexión WiFi.
- Verificar el `ExecStart` original de iwd en SteamOS y reflejarlo en el drop-in.
- Traducción (ahora todo está en castellano fijo).
