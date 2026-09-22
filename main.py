import asyncio
import gzip
import json
import os
import re
from typing import Any

import decky

# Entorno para los comandos: forzamos LC_ALL=C para que la salida de nmcli/iw
# no esté localizada y PATH explícito porque el plugin corre como root.
_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


async def _run(*args: str, timeout: float = 25) -> tuple[int, str, str]:
    """Ejecuta un comando y devuelve (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_ENV,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Timeout ejecutando: {' '.join(args)}")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _split_terse(line: str) -> list[str]:
    """Divide una línea en modo terse de nmcli (-t). Los ':' del BSSID vienen
    escapados como '\\:', así que no basta con split(':')."""
    fields: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    fields.append("".join(cur))
    return fields


def _band(freq_mhz: int) -> str:
    if freq_mhz <= 0:
        return "?"
    if freq_mhz < 2500:
        return "2.4 GHz"
    if freq_mhz < 5900:
        return "5 GHz"
    return "6 GHz"


def _dbm_to_percent(dbm: float) -> int:
    return max(0, min(100, int(round((dbm + 100) * 2))))


def _freq_to_chan(freq: int) -> int:
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if freq == 2484:
        return 14
    if 5000 <= freq < 5900:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return 0


def _to_int(value: str) -> int:
    m = re.search(r"-?\d+", value or "")
    return int(m.group(0)) if m else 0


class OuiDb:
    """Tabla OUI -> fabricante generada con scripts/build-oui.py (oui.json.gz)."""

    def __init__(self) -> None:
        self._table: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._table is None:
            path = os.path.join(decky.DECKY_PLUGIN_DIR, "oui.json.gz")
            try:
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    self._table = json.load(f)
                decky.logger.info("OUI cargada: %d prefijos", len(self._table))
            except Exception:  # noqa: BLE001
                decky.logger.exception("No se pudo cargar %s", path)
                self._table = {}
        return self._table

    def lookup(self, mac: str) -> str:
        hexmac = re.sub(r"[^0-9A-F]", "", (mac or "").upper())
        if len(hexmac) != 12:
            return ""
        # Bit "locally administered": MAC aleatoria/virtual, sin fabricante.
        if int(hexmac[1], 16) & 0x2:
            return "MAC local (sin fabricante)"
        table = self._load()
        # MA-S (36 bits) > MA-M (28 bits) > MA-L (24 bits)
        for n in (9, 7, 6):
            if (org := table.get(hexmac[:n])):
                return org
        return ""


_oui = OuiDb()


IWD_DROPIN_DIR = "/etc/systemd/system/iwd.service.d"
IWD_DROPIN = os.path.join(IWD_DROPIN_DIR, "apdetail-developer.conf")
IWD_DROPIN_CONTENT = """# Añadido por el plugin APDetail de Decky: arranca iwd en modo desarrollador
# para poder cambiar de punto de acceso (iwctl debug <dev> roam <bssid>).
# Se elimina desde el propio plugin o al desinstalarlo.
[Service]
ExecStart=
ExecStart=/usr/lib/iwd/iwd --developer
"""


class Plugin:
    _backend: str | None = None

    async def _wifi_backend(self) -> str:
        """'iwd' si NetworkManager usa iwd (SteamOS >= 3.5), si no 'wpa'."""
        if self._backend is None:
            rc, out, _ = await _run("systemctl", "is-active", "iwd")
            self._backend = "iwd" if rc == 0 and out.strip() == "active" else "wpa"
            decky.logger.info("Backend WiFi: %s", self._backend)
        return self._backend

    async def _iwd_dev_mode(self, device: str) -> bool:
        """True si iwd corre con --developer (existe la interfaz StationDebug)."""
        rc, out, err = await _run("iwctl", "debug", device, "get-networks")
        return rc == 0 and "not found" not in (out + err).lower()

    # ------------------------------------------------------------------
    # Autoconnect de iwd en modo desarrollador
    #
    # En modo desarrollador iwd crea la estación con autoconnect=false
    # (src/station.c, station_create), así que tras suspender la Deck no
    # reconecta sola. La propiedad AutoConnect de StationDebug es escribible:
    # la vigilamos y la volvemos a activar cuando haga falta.
    # ------------------------------------------------------------------

    _iwd_station_path: str | None = None
    _autoconnect_task: asyncio.Task | None = None

    async def _find_iwd_station_path(self) -> str | None:
        if self._iwd_station_path:
            return self._iwd_station_path
        rc, out, _ = await _run("busctl", "tree", "net.connman.iwd", "--list")
        if rc != 0:
            return None
        for path in out.split():
            if not re.fullmatch(r"/net/connman/iwd/\d+/\d+", path):
                continue
            rc, _, _ = await _run(
                "busctl", "get-property", "net.connman.iwd", path,
                "net.connman.iwd.StationDebug", "AutoConnect",
            )
            if rc == 0:
                self._iwd_station_path = path
                return path
        return None

    async def _iwd_get_autoconnect(self) -> bool | None:
        """True/False, o None si no se puede leer (sin modo desarrollador, etc.)."""
        path = await self._find_iwd_station_path()
        if not path:
            return None
        rc, out, _ = await _run(
            "busctl", "get-property", "net.connman.iwd", path,
            "net.connman.iwd.StationDebug", "AutoConnect",
        )
        if rc != 0:
            self._iwd_station_path = None  # la interfaz pudo recrearse tras suspender
            return None
        return out.strip().endswith("true")

    async def _iwd_set_autoconnect(self, enable: bool) -> bool:
        path = await self._find_iwd_station_path()
        if not path:
            return False
        rc, _, err = await _run(
            "busctl", "set-property", "net.connman.iwd", path,
            "net.connman.iwd.StationDebug", "AutoConnect", "b", "true" if enable else "false",
        )
        if rc != 0:
            decky.logger.warning("No se pudo fijar AutoConnect: %s", err.strip())
            self._iwd_station_path = None
            return False
        return True

    async def _autoconnect_watchdog(self) -> None:
        """Bucle en segundo plano: mantiene AutoConnect=true mientras iwd esté
        en modo desarrollador. Barato (una llamada busctl cada pocos segundos)."""
        while True:
            try:
                if await self._wifi_backend() != "iwd":
                    return
                state = await self._iwd_get_autoconnect()
                if state is None:
                    await asyncio.sleep(15)  # sin modo desarrollador: nada que vigilar
                    continue
                if not state:
                    if await self._iwd_set_autoconnect(True):
                        decky.logger.info("AutoConnect de iwd estaba desactivado; reactivado")
                await asyncio.sleep(4)
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                decky.logger.exception("autoconnect watchdog")
                await asyncio.sleep(15)

    async def _current_bssid(self, device: str) -> str:
        link = await self._iw_link(device)
        return link.get("bssid", "")

    async def _wifi_device(self) -> dict[str, str] | None:
        """Devuelve el primer dispositivo wifi: {device, state, connection}."""
        rc, out, err = await _run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status")
        if rc != 0:
            raise RuntimeError(err.strip() or "nmcli dev status falló")
        for line in out.splitlines():
            f = _split_terse(line)
            if len(f) >= 4 and f[1] == "wifi":
                return {"device": f[0], "state": f[2], "connection": f[3]}
        return None

    async def _iw_link(self, device: str) -> dict[str, Any]:
        """Detalle extra de la conexión vía `iw dev <dev> link`."""
        info: dict[str, Any] = {}
        rc, out, _ = await _run("iw", "dev", device, "link")
        if rc != 0:
            return info
        m = re.search(r"Connected to ([0-9a-f:]{17})", out, re.I)
        if m:
            info["bssid"] = m.group(1).upper()
        m = re.search(r"signal:\s*(-?\d+)\s*dBm", out)
        if m:
            info["signal_dbm"] = int(m.group(1))
        m = re.search(r"freq:\s*(\d+)", out)
        if m:
            info["freq"] = int(m.group(1))
        m = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", out)
        if m:
            info["tx_bitrate"] = float(m.group(1))
        m = re.search(r"rx bitrate:\s*([\d.]+)\s*MBit/s", out)
        if m:
            info["rx_bitrate"] = float(m.group(1))
        return info

    async def _pinned_bssid(self, connection: str) -> str:
        rc, out, _ = await _run("nmcli", "-g", "802-11-wireless.bssid", "connection", "show", connection)
        return out.strip().upper() if rc == 0 else ""

    async def _ip4(self, device: str) -> str:
        rc, out, _ = await _run("nmcli", "-g", "IP4.ADDRESS", "dev", "show", device)
        return out.strip().split("\n")[0] if rc == 0 else ""

    async def _iw_scan(self, device: str, rescan: bool) -> list[dict[str, Any]]:
        """Escaneo directo al driver. `scan` fuerza un escaneo nuevo; si el
        dispositivo está ocupado (p.ej. NM escaneando) caemos a `scan dump`."""
        out = ""
        if rescan:
            rc, out, err = await _run("iw", "dev", device, "scan", timeout=40)
            if rc != 0:
                decky.logger.warning("iw scan falló (%s); usando scan dump", err.strip())
                out = ""
        if not out:
            rc, out, _ = await _run("iw", "dev", device, "scan", "dump")
            if rc != 0:
                return []

        aps: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        for line in out.splitlines():
            m = re.match(r"BSS ([0-9a-f:]{17})\(on \S+\)(.*)", line)
            if m:
                cur = {
                    "in_use": "associated" in m.group(2),
                    "bssid": m.group(1).upper(),
                    "ssid": "",
                    "signal": 0,
                    "freq": 0,
                    "chan": 0,
                    "rate": 0,
                    "security": "",
                    "source": "iw",
                }
                aps.append(cur)
                continue
            if cur is None:
                continue
            t = line.strip()
            if t.startswith("freq:"):
                cur["freq"] = int(float(t.split(":", 1)[1]))
            elif t.startswith("signal:"):
                m = re.search(r"(-?[\d.]+)\s*dBm", t)
                if m:
                    cur["signal_dbm"] = float(m.group(1))
                    cur["signal"] = _dbm_to_percent(float(m.group(1)))
            elif t.startswith("SSID:"):
                cur["ssid"] = t[5:].strip()
            elif t.startswith("DS Parameter set: channel"):
                cur["chan"] = _to_int(t)
            elif t.startswith("* primary channel:"):
                cur["chan"] = _to_int(t)
            elif t.startswith("RSN:"):
                cur["security"] = cur["security"] or "WPA2"
            elif t.startswith("WPA:"):
                cur["security"] = cur["security"] or "WPA1"
        for ap in aps:
            if not ap["chan"]:
                ap["chan"] = _freq_to_chan(ap["freq"])
            ap["band"] = _band(ap["freq"])
            ap["vendor"] = _oui.lookup(ap["bssid"])
            # El SSID oculto lo muestra iw como "\x00\x00..."
            if re.fullmatch(r"(\\x00)+", ap["ssid"]):
                ap["ssid"] = ""
        return aps

    async def _list_aps(self, device: str, rescan: bool) -> list[dict[str, Any]]:
        """Fusiona la lista de NetworkManager con la del driver (iw)."""
        nm_aps = await self._list_aps_nm(device, rescan)
        try:
            iw_aps = await self._iw_scan(device, rescan)
        except Exception:  # noqa: BLE001
            decky.logger.exception("iw scan")
            iw_aps = []
        seen = {a["bssid"] for a in nm_aps}
        extra = [a for a in iw_aps if a["bssid"] not in seen]
        if extra:
            decky.logger.info("iw aporta %d APs que NM no listaba: %s", len(extra), [a["bssid"] for a in extra])
        aps = nm_aps + extra
        aps.sort(key=lambda a: (not a["in_use"], -a["signal"]))
        return aps

    async def _list_aps_nm(self, device: str, rescan: bool) -> list[dict[str, Any]]:
        rc, out, err = await _run(
            "nmcli", "-t",
            "-f", "IN-USE,BSSID,SSID,SIGNAL,FREQ,CHAN,RATE,SECURITY",
            "dev", "wifi", "list", "ifname", device,
            "--rescan", "yes" if rescan else "no",
            timeout=40,
        )
        if rc != 0 and rescan:
            # NetworkManager limita la frecuencia de escaneo; si lo rechaza,
            # devolvemos la caché en lugar de fallar.
            decky.logger.warning("Rescan rechazado (%s); usando caché", err.strip())
            return await self._list_aps_nm(device, rescan=False)
        if rc != 0:
            raise RuntimeError(err.strip() or "nmcli dev wifi list falló")
        aps: list[dict[str, Any]] = []
        for line in out.splitlines():
            f = _split_terse(line)
            if len(f) < 8:
                continue
            in_use, bssid, ssid, signal, freq, chan, rate, security = f[:8]
            freq_mhz = _to_int(freq)
            aps.append({
                "in_use": in_use.strip() == "*",
                "bssid": bssid.upper(),
                "vendor": _oui.lookup(bssid),
                "ssid": ssid,
                "signal": _to_int(signal),
                "freq": freq_mhz,
                "band": _band(freq_mhz),
                "chan": _to_int(chan),
                "rate": _to_int(rate),
                "security": security,
                "source": "nm",
            })
        return aps

    # ---------------------------------------------------------------------
    # Métodos expuestos al frontend
    # ---------------------------------------------------------------------

    async def get_status(self) -> dict[str, Any]:
        """Estado de la conexión wifi actual."""
        try:
            dev = await self._wifi_device()
            if dev is None:
                return {"ok": False, "error": "No se encontró un dispositivo WiFi"}
            connected = dev["state"].startswith("connected") and bool(dev["connection"])
            result: dict[str, Any] = {
                "ok": True,
                "device": dev["device"],
                "state": dev["state"],
                "connected": connected,
                "connection": dev["connection"],
            }
            if not connected:
                return result

            link = await self._iw_link(dev["device"])
            result.update(link)
            if "freq" in link:
                result["band"] = _band(link["freq"])
            backend = await self._wifi_backend()
            result["backend"] = backend
            if backend == "iwd":
                result["iwd_dev_mode"] = await self._iwd_dev_mode(dev["device"])
                result["iwd_dropin"] = os.path.exists(IWD_DROPIN)
                result["iwd_autoconnect"] = await self._iwd_get_autoconnect()
                result["pinned_bssid"] = ""
            else:
                result["pinned_bssid"] = await self._pinned_bssid(dev["connection"])
            result["ip4"] = await self._ip4(dev["device"])
            if "bssid" in result:
                result["vendor"] = _oui.lookup(result["bssid"])

            # Completar con la info del AP en uso según nmcli (SSID, canal, señal %)
            aps = await self._list_aps(dev["device"], rescan=False)
            current = next((a for a in aps if a["in_use"]), None)
            if current:
                result.setdefault("bssid", current["bssid"])
                result.setdefault("vendor", current["vendor"])
                result["ssid"] = current["ssid"]
                result["signal"] = current["signal"]
                result["chan"] = current["chan"]
                result.setdefault("freq", current["freq"])
                result.setdefault("band", current["band"])
            return result
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("get_status")
            return {"ok": False, "error": str(e)}

    async def scan(self, rescan: bool = True) -> dict[str, Any]:
        """Lista los APs visibles. `same_ssid` contiene solo los del SSID actual."""
        try:
            dev = await self._wifi_device()
            if dev is None:
                return {"ok": False, "error": "No se encontró un dispositivo WiFi"}
            aps = await self._list_aps(dev["device"], rescan=rescan)
            current = next((a for a in aps if a["in_use"]), None)
            ssid = current["ssid"] if current else ""
            same = [a for a in aps if ssid and a["ssid"] == ssid]
            decky.logger.info(
                "scan(rescan=%s): ssid=%r total=%d same_ssid=%s",
                rescan, ssid, len(aps), [(a["bssid"], a["signal"], a["source"]) for a in same],
            )
            return {"ok": True, "ssid": ssid, "same_ssid": same, "all": aps}
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("scan")
            return {"ok": False, "error": str(e)}

    async def connect_bssid(self, bssid: str) -> dict[str, Any]:
        """Cambia al AP indicado. Con iwd usa `iwctl debug roam`; con
        wpa_supplicant fija el BSSID en el perfil de NetworkManager."""
        try:
            bssid = (bssid or "").strip().upper()
            if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", bssid):
                return {"ok": False, "error": f"BSSID inválido: {bssid}"}
            dev = await self._wifi_device()
            if dev is None or not dev["connection"]:
                return {"ok": False, "error": "No hay una conexión WiFi activa"}
            if await self._wifi_backend() == "iwd":
                return await self._connect_bssid_iwd(dev["device"], bssid)
            return await self._connect_bssid_nm(dev["device"], dev["connection"], bssid)
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("connect_bssid")
            return {"ok": False, "error": str(e)}

    async def _connect_bssid_iwd(self, device: str, bssid: str) -> dict[str, Any]:
        if not await self._iwd_dev_mode(device):
            return {
                "ok": False,
                "needs_dev_mode": True,
                "error": "iwd no está en modo desarrollador (ver README)",
            }
        before = await self._current_bssid(device)
        if before == bssid:
            return {"ok": True, "bssid": bssid, "unchanged": True}
        # roam = reasociación rápida sin perder la conexión; connect = reconexión completa
        rc, out, err = await _run("iwctl", "debug", device, "roam", bssid.lower(), timeout=30)
        if rc != 0:
            decky.logger.warning("iwctl roam falló (%s %s); probando connect", out.strip(), err.strip())
            rc, out, err = await _run("iwctl", "debug", device, "connect", bssid.lower(), timeout=60)
            if rc != 0:
                return {"ok": False, "error": (out + err).strip() or "iwctl no pudo cambiar de AP"}
        # Esperamos a que el driver refleje el cambio
        for _ in range(20):
            await asyncio.sleep(0.5)
            if await self._current_bssid(device) == bssid:
                decky.logger.info("Roam OK: %s -> %s", before, bssid)
                return {"ok": True, "bssid": bssid}
        now = await self._current_bssid(device)
        return {"ok": False, "error": f"iwd no cambió de AP (sigue en {now or 'desconocido'})"}

    async def _connect_bssid_nm(self, device: str, conn: str, bssid: str) -> dict[str, Any]:
        rc, _, err = await _run("nmcli", "connection", "modify", conn, "802-11-wireless.bssid", bssid)
        if rc != 0:
            return {"ok": False, "error": err.strip() or "No se pudo modificar la conexión"}
        rc, _, err = await _run("nmcli", "connection", "up", conn, "ifname", device, timeout=60)
        if rc != 0:
            # Revertimos el pin para no dejar la conexión inutilizable
            await _run("nmcli", "connection", "modify", conn, "802-11-wireless.bssid", "")
            await _run("nmcli", "connection", "up", conn, "ifname", device, timeout=60)
            return {"ok": False, "error": err.strip() or "No se pudo conectar al AP; se ha revertido"}
        decky.logger.info("Conectado a BSSID %s en %s", bssid, conn)
        return {"ok": True, "bssid": bssid, "connection": conn}

    async def _wait_connected(self, seconds: float) -> bool:
        for _ in range(int(seconds * 2)):
            await asyncio.sleep(0.5)
            dev = await self._wifi_device()
            if dev and dev["state"].startswith("connected") and dev["connection"]:
                return True
        return False

    async def _restart_iwd_and_wait(self) -> dict[str, Any]:
        # Recordamos el perfil activo: NetworkManager (backend iwd) no siempre
        # reasocia solo cuando iwd se reinicia debajo, así que lo levantamos nosotros.
        dev = await self._wifi_device()
        conn = dev["connection"] if dev else ""
        device = dev["device"] if dev else ""

        rc, _, err = await _run("systemctl", "daemon-reload")
        if rc != 0:
            return {"ok": False, "error": err.strip() or "daemon-reload falló"}
        rc, _, err = await _run("systemctl", "restart", "iwd", timeout=60)
        if rc != 0:
            return {"ok": False, "error": err.strip() or "No se pudo reiniciar iwd"}

        # En modo desarrollador iwd arranca con autoconnect=false: lo activamos
        # ya para que reconecte solo (y siga haciéndolo tras suspender).
        self._iwd_station_path = None
        for _ in range(10):
            await asyncio.sleep(0.5)
            if await self._iwd_get_autoconnect() is not None:
                await self._iwd_set_autoconnect(True)
                break
        if await self._wait_connected(8):
            return {"ok": True}
        if conn:
            decky.logger.info("Reconectando %r tras reiniciar iwd", conn)
            args = ["nmcli", "connection", "up", conn] + (["ifname", device] if device else [])
            rc, _, err = await _run(*args, timeout=60)
            if rc != 0:
                decky.logger.warning("nmcli connection up falló: %s", err.strip())
            if await self._wait_connected(12):
                return {"ok": True}
        return {"ok": True, "warning": "iwd reiniciado; reconecta el WiFi desde el menú de la Deck"}

    async def set_iwd_dev_mode(self, enable: bool) -> dict[str, Any]:
        """Activa/revierte el modo desarrollador de iwd mediante un drop-in de
        systemd y reinicia iwd (el WiFi se cae unos segundos y reconecta solo)."""
        try:
            if await self._wifi_backend() != "iwd":
                return {"ok": False, "error": "El sistema no usa iwd"}
            if enable:
                os.makedirs(IWD_DROPIN_DIR, exist_ok=True)
                with open(IWD_DROPIN, "w", encoding="utf-8") as f:
                    f.write(IWD_DROPIN_CONTENT)
                decky.logger.info("Drop-in creado: %s", IWD_DROPIN)
            else:
                if os.path.exists(IWD_DROPIN):
                    os.remove(IWD_DROPIN)
                    decky.logger.info("Drop-in eliminado: %s", IWD_DROPIN)
                # Si el directorio queda vacío lo quitamos para dejarlo como estaba
                try:
                    os.rmdir(IWD_DROPIN_DIR)
                except OSError:
                    pass
            result = await self._restart_iwd_and_wait()
            if result["ok"]:
                decky.logger.info("iwd reiniciado en modo %s", "desarrollador" if enable else "normal")
            return result
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("set_iwd_dev_mode")
            return {"ok": False, "error": str(e)}

    async def clear_bssid(self) -> dict[str, Any]:
        """Quita el BSSID fijado del perfil actual (vuelve al roaming automático)."""
        try:
            if await self._wifi_backend() == "iwd":
                return {"ok": False, "error": "Con iwd no hay BSSID fijado"}
            dev = await self._wifi_device()
            if dev is None or not dev["connection"]:
                return {"ok": False, "error": "No hay una conexión WiFi activa"}
            conn = dev["connection"]
            rc, _, err = await _run("nmcli", "connection", "modify", conn, "802-11-wireless.bssid", "")
            if rc != 0:
                return {"ok": False, "error": err.strip() or "No se pudo modificar la conexión"}
            rc, _, err = await _run("nmcli", "connection", "up", conn, "ifname", dev["device"], timeout=60)
            if rc != 0:
                return {"ok": False, "error": err.strip() or "No se pudo reconectar"}
            decky.logger.info("BSSID liberado en %s", conn)
            return {"ok": True, "connection": conn}
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("clear_bssid")
            return {"ok": False, "error": str(e)}

    # ---------------------------------------------------------------------
    # Ciclo de vida
    # ---------------------------------------------------------------------

    async def _main(self):
        decky.logger.info("APDetail cargado")
        await asyncio.get_running_loop().run_in_executor(None, _oui._load)
        self._autoconnect_task = asyncio.create_task(self._autoconnect_watchdog())

    async def _unload(self):
        if self._autoconnect_task:
            self._autoconnect_task.cancel()
            self._autoconnect_task = None
        decky.logger.info("APDetail descargado")

    async def _uninstall(self):
        # No revertimos aquí el modo desarrollador de iwd: Decky también llama a
        # _uninstall al reinstalar/actualizar el plugin y reiniciaría el WiFi
        # cada vez. Se revierte desde el botón del plugin.
        if os.path.exists(IWD_DROPIN):
            decky.logger.warning("Queda activo el modo desarrollador de iwd (%s)", IWD_DROPIN)
        decky.logger.info("APDetail desinstalado")

    async def _migration(self):
        # Migración de logs/settings de versiones antiguas: no aplica todavía.
        _ = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
