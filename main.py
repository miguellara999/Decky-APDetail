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


class Plugin:
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

    async def _list_aps(self, device: str, rescan: bool) -> list[dict[str, Any]]:
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
            return await self._list_aps(device, rescan=False)
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
            })
        aps.sort(key=lambda a: (not a["in_use"], -a["signal"]))
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
            return {
                "ok": True,
                "ssid": ssid,
                "same_ssid": [a for a in aps if ssid and a["ssid"] == ssid],
                "all": aps,
            }
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("scan")
            return {"ok": False, "error": str(e)}

    async def connect_bssid(self, bssid: str) -> dict[str, Any]:
        """Fija el BSSID en el perfil de conexión actual y reconecta."""
        try:
            bssid = (bssid or "").strip().upper()
            if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", bssid):
                return {"ok": False, "error": f"BSSID inválido: {bssid}"}
            dev = await self._wifi_device()
            if dev is None or not dev["connection"]:
                return {"ok": False, "error": "No hay una conexión WiFi activa"}
            conn = dev["connection"]
            rc, _, err = await _run("nmcli", "connection", "modify", conn, "802-11-wireless.bssid", bssid)
            if rc != 0:
                return {"ok": False, "error": err.strip() or "No se pudo modificar la conexión"}
            rc, _, err = await _run("nmcli", "connection", "up", conn, "ifname", dev["device"], timeout=60)
            if rc != 0:
                # Revertimos el pin para no dejar la conexión inutilizable
                await _run("nmcli", "connection", "modify", conn, "802-11-wireless.bssid", "")
                await _run("nmcli", "connection", "up", conn, "ifname", dev["device"], timeout=60)
                return {"ok": False, "error": err.strip() or "No se pudo conectar al AP; se ha revertido"}
            decky.logger.info("Conectado a BSSID %s en %s", bssid, conn)
            return {"ok": True, "bssid": bssid, "connection": conn}
        except Exception as e:  # noqa: BLE001
            decky.logger.exception("connect_bssid")
            return {"ok": False, "error": str(e)}

    async def clear_bssid(self) -> dict[str, Any]:
        """Quita el BSSID fijado del perfil actual (vuelve al roaming automático)."""
        try:
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

    async def _unload(self):
        decky.logger.info("APDetail descargado")

    async def _uninstall(self):
        decky.logger.info("APDetail desinstalado")

    async def _migration(self):
        # Migración de logs/settings de versiones antiguas: no aplica todavía.
        _ = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
