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
import { confirmLang, detectLang, strings, type Lang } from "./i18n";

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
  signal: number; // 0-100, fórmula de NetworkManager sobre signal_dbm
  signal_dbm?: number;
  age_ms?: number; // antigüedad de la medición (0 = en vivo)
  stale?: boolean; // ya no está en la lista del kernel; viene de la memoria del backend
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
const scan = callable<[rescan: boolean, quick: boolean], ScanResult>("scan");
const connectBssid = callable<[bssid: string], ActionResult>("connect_bssid");
const clearBssid = callable<[], ActionResult>("clear_bssid");
const setIwdDevMode = callable<[enable: boolean], ActionResult>("set_iwd_dev_mode");

const REFRESH_MS = 10_000;
// Cada N refrescos hacemos un escaneo dirigido (el kernel caduca los APs no oídos en 30 s)
const RESCAN_EVERY = 3;

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

type T = ReturnType<typeof strings>;

function signalText(ap: AccessPoint): string {
  const dbm = ap.signal_dbm != null ? `${Math.round(ap.signal_dbm)} dBm · ` : "";
  return `${dbm}${ap.signal}% ${signalBars(ap.signal)}`;
}

function ageText(ap: AccessPoint, t: T): string {
  const ageMs = ap.age_ms ?? 0;
  if (ageMs < 3000) return "";
  const s = Math.round(ageMs / 1000);
  const ago = s < 90 ? t.agoSeconds(s) : t.agoMinutes(Math.round(s / 60));
  return ap.stale ? ` · ${t.lastSeen(ago)}` : ` · ${ago}`;
}

/** Idioma de la interfaz de Steam, confirmado de forma asíncrona tras el primer render. */
function useLang(): Lang {
  const [lang, setLang] = useState<Lang>(detectLang);
  useEffect(() => {
    void confirmLang().then((l) => {
      if (l) setLang(l);
    });
  }, []);
  return lang;
}

function shortBssid(bssid: string): string {
  // Los 3 últimos octetos suelen bastar para distinguir APs del mismo fabricante
  return bssid.split(":").slice(3).join(":");
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

function Content() {
  const t = strings(useLang());
  const [status, setStatus] = useState<Status | null>(null);
  const [sameSsid, setSameSsid] = useState<AccessPoint[]>([]);
  const [allAps, setAllAps] = useState<AccessPoint[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  // rescan: forzar escaneo. quick: solo los canales donde ya hay APs de mi SSID
  // (rápido, sin cortar la conexión); false = escaneo completo para descubrir.
  const refresh = useCallback(async (rescan: boolean, quick = false) => {
    if (rescan && !quick) setScanning(true);
    try {
      const s = await getStatus();
      setStatus(s);
      const r = await scan(rescan, quick);
      if (r.ok) {
        setSameSsid(r.same_ssid ?? []);
        setAllAps(r.all ?? []);
      } else if (rescan) {
        toaster.toast({ title: "APDetail", body: r.error ?? t.scanError });
      }
    } catch (e) {
      setStatus({ ok: false, error: String(e) });
    } finally {
      if (rescan && !quick) setScanning(false);
    }
  }, [t]);

  useEffect(() => {
    // Primero la caché (instantánea), luego un escaneo real en segundo plano
    void refresh(false).then(() => refresh(true));
    let tick = 0;
    const id = setInterval(() => {
      tick += 1;
      void refresh(tick % RESCAN_EVERY === 0, true);
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const onConnect = async (ap: AccessPoint) => {
    setBusy(ap.bssid);
    try {
      const r = await connectBssid(ap.bssid);
      toaster.toast({
        title: "APDetail",
        body: r.ok ? t.connectedTo(shortBssid(ap.bssid), ap.band) : r.error ?? t.genericError,
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
        body: r.ok ? t.roamingRestored : r.error ?? t.genericError,
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
          ? r.warning ?? (enable ? t.devModeEnabled : t.devModeReverted)
          : r.error ?? t.genericError,
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
      <PanelSection title={t.currentConnection}>
        {!status && (
          <PanelSectionRow>
            <Field label={t.loading} />
          </PanelSectionRow>
        )}
        {status && !status.ok && (
          <PanelSectionRow>
            <Field label={t.error} description={status.error} />
          </PanelSectionRow>
        )}
        {status?.ok && !status.connected && (
          <PanelSectionRow>
            <Field label={t.noWifi} description={status.state} />
          </PanelSectionRow>
        )}
        {status?.ok && status.connected && (
          <>
            <PanelSectionRow>
              <Field label={t.ssid} focusable>
                {status.ssid ?? status.connection}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field
                label={t.accessPoint}
                description={
                  status.backend === "iwd"
                    ? status.iwd_dev_mode
                      ? status.iwd_autoconnect === false
                        ? t.iwdCanSwitchNoAutoconnect
                        : t.iwdCanSwitch
                      : t.iwdDevModeOff
                    : pinned
                      ? t.bssidPinned
                      : t.autoRoaming
                }
                focusable
              >
                {status.bssid ?? "?"}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label={t.vendor} focusable>
                {status.vendor || t.unknownVendor}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label={t.signal} description={t.signalHint} focusable>
                {status.signal_dbm != null ? `${status.signal_dbm} dBm` : ""}
                {status.signal != null ? ` (${status.signal}%)` : ""}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label={t.bandChannel} focusable>
                {status.band ?? "?"}
                {status.chan ? ` · ${t.channel} ${status.chan}` : ""}
                {status.freq ? ` · ${status.freq} MHz` : ""}
              </Field>
            </PanelSectionRow>
            {(status.tx_bitrate || status.rx_bitrate) && (
              <PanelSectionRow>
                <Field label={t.speed} focusable>
                  {status.rx_bitrate ? `↓ ${status.rx_bitrate} ` : ""}
                  {status.tx_bitrate ? `↑ ${status.tx_bitrate} ` : ""}
                  Mbit/s
                </Field>
              </PanelSectionRow>
            )}
            {status.ip4 && (
              <PanelSectionRow>
                <Field label={t.ip} focusable>
                  {status.ip4}
                </Field>
              </PanelSectionRow>
            )}
          </>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={scanning} onClick={() => void refresh(true)}>
            {scanning ? t.scanning : t.rescan}
          </ButtonItem>
        </PanelSectionRow>
        {(iwdNeedsDevMode || canRevertIwd) && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy !== null}
              description={
                iwdNeedsDevMode ? t.enableIwdDevModeHint : t.revertIwdDevModeHint
              }
              onClick={() => void onToggleIwd()}
            >
              {busy === "iwd"
                ? t.restartingIwd
                : iwdNeedsDevMode
                  ? t.enableIwdDevMode
                  : t.revertIwdDevMode}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {pinned && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy !== null} onClick={() => void onClear()}>
              {busy === "clear" ? t.applying : t.clearPin}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection
        title={
          showAll ? t.allNetworks : status?.ssid ? t.accessPointsOf(status.ssid) : t.accessPoints
        }
      >
        <PanelSectionRow>
          <ToggleField
            label={t.showAllNetworks}
            description={t.showAllNetworksHint}
            checked={showAll}
            onChange={setShowAll}
          />
        </PanelSectionRow>
        {aps.length === 0 && (
          <PanelSectionRow>
            <Field label={t.noOtherAps} description={t.noOtherApsHint} />
          </PanelSectionRow>
        )}
        {aps.map((ap) => (
          <PanelSectionRow key={ap.bssid}>
            <ButtonItem
              layout="below"
              disabled={busy !== null || ap.in_use || (showAll && !isSameNetwork(ap))}
              description={
                (ap.vendor ? `${ap.vendor} · ` : "") +
                `${ap.bssid} · ${ap.band} · ${t.channel} ${ap.chan} · ${signalText(ap)}${ageText(ap, t)}`
              }
              onClick={() => void onConnect(ap)}
            >
              {ap.in_use ? "● " : ""}
              {ap.ssid || t.hiddenSsid}
              {busy === ap.bssid ? `  ${t.connecting}` : ap.in_use ? `  ${t.inUse}` : ""}
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
