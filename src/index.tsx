import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import React, { useCallback, useEffect, useState } from "react";
import { FaWifi } from "react-icons/fa";

// ---------------------------------------------------------------------------
// Tipos que devuelve el backend (main.py)
// ---------------------------------------------------------------------------

type Status = {
  ok: boolean;
  error?: string;
  device?: string;
  state?: string;
  connected?: boolean;
  connection?: string;
  ssid?: string;
  bssid?: string;
  vendor?: string;
  signal?: number; // 0-100 (nmcli)
  signal_dbm?: number; // iw
  freq?: number;
  band?: string;
  chan?: number;
  tx_bitrate?: number;
  rx_bitrate?: number;
  ip4?: string;
  pinned_bssid?: string;
  backend?: "iwd" | "wpa";
  iwd_dev_mode?: boolean;
  iwd_dropin?: boolean; // el drop-in lo creó este plugin
  iwd_autoconnect?: boolean | null; // null = no legible (sin modo desarrollador)
};

type AccessPoint = {
  in_use: boolean;
  bssid: string;
  vendor: string;
  ssid: string;
  signal: number;
  freq: number;
  band: string;
  chan: number;
  rate: number;
  security: string;
};

type ScanResult = {
  ok: boolean;
  error?: string;
  ssid?: string;
  same_ssid?: AccessPoint[];
  all?: AccessPoint[];
};

type ActionResult = {
  ok: boolean;
  error?: string;
  warning?: string;
  bssid?: string;
  needs_dev_mode?: boolean;
};

// ---------------------------------------------------------------------------
// Llamadas al backend
// ---------------------------------------------------------------------------

const getStatus = callable<[], Status>("get_status");
const scan = callable<[rescan: boolean], ScanResult>("scan");
const connectBssid = callable<[bssid: string], ActionResult>("connect_bssid");
const clearBssid = callable<[], ActionResult>("clear_bssid");
const setIwdDevMode = callable<[enable: boolean], ActionResult>("set_iwd_dev_mode");

const REFRESH_MS = 10_000;

// ---------------------------------------------------------------------------
// Helpers de presentación
// ---------------------------------------------------------------------------

function signalBars(signal: number): string {
  if (signal >= 80) return "▂▄▆█";
  if (signal >= 60) return "▂▄▆_";
  if (signal >= 40) return "▂▄__";
  if (signal >= 20) return "▂___";
  return "____";
}

function shortBssid(bssid: string): string {
  // Los 3 últimos octetos suelen bastar para distinguir APs del mismo fabricante
  return bssid.split(":").slice(3).join(":");
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [sameSsid, setSameSsid] = useState<AccessPoint[]>([]);
  const [allAps, setAllAps] = useState<AccessPoint[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const refresh = useCallback(async (rescan: boolean) => {
    if (rescan) setScanning(true);
    try {
      const s = await getStatus();
      setStatus(s);
      const r = await scan(rescan);
      if (r.ok) {
        setSameSsid(r.same_ssid ?? []);
        setAllAps(r.all ?? []);
      } else if (rescan) {
        toaster.toast({ title: "APDetail", body: r.error ?? "Error al escanear" });
      }
    } catch (e) {
      setStatus({ ok: false, error: String(e) });
    } finally {
      if (rescan) setScanning(false);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
    const id = setInterval(() => void refresh(false), REFRESH_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const onConnect = async (ap: AccessPoint) => {
    setBusy(ap.bssid);
    try {
      const r = await connectBssid(ap.bssid);
      toaster.toast({
        title: "APDetail",
        body: r.ok ? `Conectado a ${shortBssid(ap.bssid)} (${ap.band})` : r.error ?? "Error",
      });
    } finally {
      setBusy(null);
      void refresh(false);
    }
  };

  const onClear = async () => {
    setBusy("clear");
    try {
      const r = await clearBssid();
      toaster.toast({
        title: "APDetail",
        body: r.ok ? "Roaming automático restaurado" : r.error ?? "Error",
      });
    } finally {
      setBusy(null);
      void refresh(false);
    }
  };

  const pinned = !!status?.pinned_bssid;
  const isIwd = status?.backend === "iwd";
  const iwdDevMode = !!status?.iwd_dev_mode;
  const iwdNeedsDevMode = isIwd && !iwdDevMode;
  // Solo ofrecemos revertir si el modo desarrollador lo activó este plugin
  const canRevertIwd = isIwd && iwdDevMode && !!status?.iwd_dropin;

  const onToggleIwd = async () => {
    const enable = !iwdDevMode;
    setBusy("iwd");
    try {
      const r = await setIwdDevMode(enable);
      toaster.toast({
        title: "APDetail",
        body: r.ok
          ? r.warning ??
            (enable ? "Modo desarrollador de iwd activado" : "iwd restaurado a su configuración por defecto")
          : r.error ?? "Error",
      });
    } finally {
      setBusy(null);
      void refresh(false);
    }
  };
  const aps = showAll ? allAps : sameSsid;
  // Solo permitimos conectar a APs del SSID actual: fijar el BSSID de otra red
  // en el perfil activo dejaría la conexión inutilizable.
  const isSameNetwork = (ap: AccessPoint) => !!status?.ssid && ap.ssid === status.ssid;

  return (
    <>
      <PanelSection title="Conexión actual">
        {!status && (
          <PanelSectionRow>
            <Field label="Cargando…" />
          </PanelSectionRow>
        )}
        {status && !status.ok && (
          <PanelSectionRow>
            <Field label="Error" description={status.error} />
          </PanelSectionRow>
        )}
        {status?.ok && !status.connected && (
          <PanelSectionRow>
            <Field label="Sin conexión WiFi" description={status.state} />
          </PanelSectionRow>
        )}
        {status?.ok && status.connected && (
          <>
            <PanelSectionRow>
              <Field label="SSID" focusable>
                {status.ssid ?? status.connection}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field
                label="Punto de acceso"
                description={
                  status.backend === "iwd"
                    ? status.iwd_dev_mode
                      ? status.iwd_autoconnect === false
                        ? "iwd · cambio de AP disponible · autoconnect desactivado (reactivando…)"
                        : "iwd · cambio de AP disponible"
                      : "iwd · modo desarrollador desactivado"
                    : pinned
                      ? "BSSID fijado en el perfil"
                      : "Roaming automático"
                }
                focusable
              >
                {status.bssid ?? "?"}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Fabricante" focusable>
                {status.vendor || "Desconocido"}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Señal" focusable>
                {status.signal != null ? `${status.signal}%` : ""}
                {status.signal_dbm != null ? ` (${status.signal_dbm} dBm)` : ""}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Banda / canal" focusable>
                {status.band ?? "?"}
                {status.chan ? ` · canal ${status.chan}` : ""}
                {status.freq ? ` · ${status.freq} MHz` : ""}
              </Field>
            </PanelSectionRow>
            {(status.tx_bitrate || status.rx_bitrate) && (
              <PanelSectionRow>
                <Field label="Velocidad" focusable>
                  {status.rx_bitrate ? `↓ ${status.rx_bitrate} ` : ""}
                  {status.tx_bitrate ? `↑ ${status.tx_bitrate} ` : ""}
                  Mbit/s
                </Field>
              </PanelSectionRow>
            )}
            {status.ip4 && (
              <PanelSectionRow>
                <Field label="IP" focusable>
                  {status.ip4}
                </Field>
              </PanelSectionRow>
            )}
          </>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={scanning} onClick={() => void refresh(true)}>
            {scanning ? "Escaneando…" : "Volver a escanear"}
          </ButtonItem>
        </PanelSectionRow>
        {(iwdNeedsDevMode || canRevertIwd) && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy !== null}
              description={
                iwdNeedsDevMode
                  ? "SteamOS usa iwd, que solo permite elegir AP en modo desarrollador. Se reinicia iwd: el WiFi se corta unos segundos y reconecta solo."
                  : "Elimina el ajuste añadido por el plugin y reinicia iwd con su configuración por defecto."
              }
              onClick={() => void onToggleIwd()}
            >
              {busy === "iwd"
                ? "Reiniciando iwd…"
                : iwdNeedsDevMode
                  ? "Activar modo desarrollador de iwd"
                  : "Revertir modo desarrollador de iwd"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {pinned && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => void onClear()}>
              {busy === "clear" ? "Aplicando…" : "Quitar fijación (roaming automático)"}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection
        title={
          showAll ? "Todas las redes" : status?.ssid ? `Puntos de acceso de "${status.ssid}"` : "Puntos de acceso"
        }
      >
        <PanelSectionRow>
          <ToggleField
            label="Mostrar todas las redes"
            description="Incluye otros SSID y redes ocultas"
            checked={showAll}
            onChange={setShowAll}
          />
        </PanelSectionRow>
        {aps.length === 0 && (
          <PanelSectionRow>
            <Field label="No se han encontrado otros APs" description="Pulsa «Volver a escanear»" />
          </PanelSectionRow>
        )}
        {aps.map((ap) => (
          <PanelSectionRow key={ap.bssid}>
            <ButtonItem
              layout="below"
              disabled={busy !== null || ap.in_use || (showAll && !isSameNetwork(ap))}
              description={
                (ap.vendor ? `${ap.vendor} · ` : "") +
                `${ap.bssid} · ${ap.band} · canal ${ap.chan} · ${ap.signal}% ${signalBars(ap.signal)}`
              }
              onClick={() => void onConnect(ap)}
            >
              {ap.in_use ? "● " : ""}
              {ap.ssid || "(SSID oculto)"}
              {busy === ap.bssid ? "  (conectando…)" : ap.in_use ? "  (en uso)" : ""}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "APDetail",
  titleView: <div className={staticClasses.Title}>APDetail</div>,
  content: <Content />,
  icon: <FaWifi />,
  onDismount() {
    // Nada que limpiar: los intervalos se cancelan al desmontar <Content />.
  },
}));
