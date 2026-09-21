import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
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
  signal?: number; // 0-100 (nmcli)
  signal_dbm?: number; // iw
  freq?: number;
  band?: string;
  chan?: number;
  tx_bitrate?: number;
  rx_bitrate?: number;
  ip4?: string;
  pinned_bssid?: string;
};

type AccessPoint = {
  in_use: boolean;
  bssid: string;
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

type ActionResult = { ok: boolean; error?: string; bssid?: string };

// ---------------------------------------------------------------------------
// Llamadas al backend
// ---------------------------------------------------------------------------

const getStatus = callable<[], Status>("get_status");
const scan = callable<[rescan: boolean], ScanResult>("scan");
const connectBssid = callable<[bssid: string], ActionResult>("connect_bssid");
const clearBssid = callable<[], ActionResult>("clear_bssid");

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
  const [aps, setAps] = useState<AccessPoint[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const refresh = useCallback(async (rescan: boolean) => {
    if (rescan) setScanning(true);
    try {
      const s = await getStatus();
      setStatus(s);
      const r = await scan(rescan);
      if (r.ok) setAps(r.same_ssid ?? []);
      else if (rescan) toaster.toast({ title: "APDetail", body: r.error ?? "Error al escanear" });
    } catch (e) {
      setStatus({ ok: false, error: String(e) });
    } finally {
      if (rescan) setScanning(false);
    }
  }, []);

  useEffect(() => {
    void refresh(false);
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
                description={pinned ? "BSSID fijado en el perfil" : "Roaming automático"}
                focusable
              >
                {status.bssid ?? "?"}
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
        {pinned && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => void onClear()}>
              {busy === "clear" ? "Aplicando…" : "Quitar fijación (roaming automático)"}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title={status?.ssid ? `Puntos de acceso de "${status.ssid}"` : "Puntos de acceso"}>
        {aps.length === 0 && (
          <PanelSectionRow>
            <Field label="No se han encontrado otros APs" description="Pulsa «Volver a escanear»" />
          </PanelSectionRow>
        )}
        {aps.map((ap) => (
          <PanelSectionRow key={ap.bssid}>
            <ButtonItem
              layout="below"
              disabled={busy !== null || ap.in_use}
              description={`${ap.band} · canal ${ap.chan} · ${ap.signal}% ${signalBars(ap.signal)}`}
              onClick={() => void onConnect(ap)}
            >
              {ap.in_use ? "● " : ""}
              {ap.bssid}
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
