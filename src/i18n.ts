// Localización del plugin. Castellano si la interfaz de Steam está en español,
// inglés en cualquier otro caso. Para añadir un idioma: copia el bloque `en`,
// traduce los valores y añade su prefijo de locale en `detectLang()`.

export type Lang = "es" | "en";

const en = {
  // Secciones
  currentConnection: "Current connection",
  accessPoints: "Access points",
  accessPointsOf: (ssid: string) => `Access points on "${ssid}"`,
  allNetworks: "All networks",

  // Estado
  loading: "Loading…",
  error: "Error",
  genericError: "Error",
  noWifi: "No WiFi connection",
  ssid: "SSID",
  accessPoint: "Access point",
  vendor: "Vendor",
  unknownVendor: "Unknown",
  signal: "Signal",
  signalHint: "Live dBm from the link; % uses the Steam/NetworkManager formula",
  bandChannel: "Band / channel",
  channel: "channel",
  speed: "Speed",
  ip: "IP",

  // Estado del punto de acceso
  iwdCanSwitch: "iwd · AP switching available",
  iwdCanSwitchNoAutoconnect: "iwd · AP switching available · autoconnect off (re-enabling…)",
  iwdDevModeOff: "iwd · developer mode disabled",
  bssidPinned: "BSSID pinned on the profile",
  autoRoaming: "Automatic roaming",

  // Botones
  scanning: "Scanning…",
  rescan: "Rescan",
  enableIwdDevMode: "Enable iwd developer mode",
  revertIwdDevMode: "Revert iwd developer mode",
  restartingIwd: "Restarting iwd…",
  enableIwdDevModeHint:
    "SteamOS uses iwd, which only allows choosing an AP in developer mode. iwd is restarted: " +
    "WiFi drops for a few seconds and reconnects on its own.",
  revertIwdDevModeHint:
    "Removes the setting added by the plugin and restarts iwd with its default configuration.",
  applying: "Applying…",
  clearPin: "Clear pin (automatic roaming)",

  // Lista de APs
  showAllNetworks: "Show all networks",
  showAllNetworksHint: "Includes other SSIDs and hidden networks",
  noOtherAps: "No other APs found",
  noOtherApsHint: 'Press "Rescan"',
  hiddenSsid: "(hidden SSID)",
  inUse: "(in use)",
  connecting: "(connecting…)",

  // Avisos
  scanError: "Error while scanning",
  connectedTo: (bssid: string, band: string) => `Connected to ${bssid} (${band})`,
  roamingRestored: "Automatic roaming restored",
  devModeEnabled: "iwd developer mode enabled",
  devModeReverted: "iwd restored to its default configuration",

  // Antigüedad de la medición
  agoSeconds: (s: number) => `${s} s ago`,
  agoMinutes: (m: number) => `${m} min ago`,
  lastSeen: (ago: string) => `last seen ${ago}`,
};

type Strings = typeof en;

const es: Strings = {
  currentConnection: "Conexión actual",
  accessPoints: "Puntos de acceso",
  accessPointsOf: (ssid: string) => `Puntos de acceso de "${ssid}"`,
  allNetworks: "Todas las redes",

  loading: "Cargando…",
  error: "Error",
  genericError: "Error",
  noWifi: "Sin conexión WiFi",
  ssid: "SSID",
  accessPoint: "Punto de acceso",
  vendor: "Fabricante",
  unknownVendor: "Desconocido",
  signal: "Señal",
  signalHint: "dBm en vivo del enlace; % con la fórmula de Steam/NetworkManager",
  bandChannel: "Banda / canal",
  channel: "canal",
  speed: "Velocidad",
  ip: "IP",

  iwdCanSwitch: "iwd · cambio de AP disponible",
  iwdCanSwitchNoAutoconnect: "iwd · cambio de AP disponible · autoconnect desactivado (reactivando…)",
  iwdDevModeOff: "iwd · modo desarrollador desactivado",
  bssidPinned: "BSSID fijado en el perfil",
  autoRoaming: "Roaming automático",

  scanning: "Escaneando…",
  rescan: "Volver a escanear",
  enableIwdDevMode: "Activar modo desarrollador de iwd",
  revertIwdDevMode: "Revertir modo desarrollador de iwd",
  restartingIwd: "Reiniciando iwd…",
  enableIwdDevModeHint:
    "SteamOS usa iwd, que solo permite elegir AP en modo desarrollador. Se reinicia iwd: " +
    "el WiFi se corta unos segundos y reconecta solo.",
  revertIwdDevModeHint:
    "Elimina el ajuste añadido por el plugin y reinicia iwd con su configuración por defecto.",
  applying: "Aplicando…",
  clearPin: "Quitar fijación (roaming automático)",

  showAllNetworks: "Mostrar todas las redes",
  showAllNetworksHint: "Incluye otros SSID y redes ocultas",
  noOtherAps: "No se han encontrado otros APs",
  noOtherApsHint: "Pulsa «Volver a escanear»",
  hiddenSsid: "(SSID oculto)",
  inUse: "(en uso)",
  connecting: "(conectando…)",

  scanError: "Error al escanear",
  connectedTo: (bssid: string, band: string) => `Conectado a ${bssid} (${band})`,
  roamingRestored: "Roaming automático restaurado",
  devModeEnabled: "Modo desarrollador de iwd activado",
  devModeReverted: "iwd restaurado a su configuración por defecto",

  agoSeconds: (s: number) => `hace ${s} s`,
  agoMinutes: (m: number) => `hace ${m} min`,
  lastSeen: (ago: string) => `visto ${ago}`,
};

const STRINGS: Record<Lang, Strings> = { es, en };

/** Prefijos de locale y nombres de idioma de Steam que mapean a cada traducción. */
const LOCALE_PREFIXES: Record<Exclude<Lang, "en">, { locales: string[]; steam: string[] }> = {
  es: { locales: ["es"], steam: ["spanish", "latam"] },
};

function matchLang(value: string): Lang | null {
  const v = value.toLowerCase();
  for (const [lang, { locales, steam }] of Object.entries(LOCALE_PREFIXES)) {
    if (locales.some((p) => v.startsWith(p)) || steam.includes(v)) return lang as Lang;
  }
  return null;
}

/**
 * Idioma de la interfaz de Steam, de forma síncrona. `LocalizationManager`
 * lo expone como lista de locales (p. ej. ["es-ES", "es", "en"]); si no está
 * disponible caemos al idioma del navegador y, por último, a inglés.
 */
export function detectLang(): Lang {
  try {
    // El primer locale es el elegido por el usuario; el resto son los fallbacks
    // de Steam (siempre acaban en "en"), así que solo miramos ese.
    const preferred = window.LocalizationManager?.m_rgLocalesToUse?.[0];
    if (preferred) return matchLang(preferred) ?? "en";
  } catch {
    // LocalizationManager puede no existir en versiones futuras de Steam
  }
  try {
    const lang = matchLang(navigator.language ?? "");
    if (lang) return lang;
  } catch {
    // ignorado
  }
  return "en";
}

/**
 * Confirma el idioma con `SteamClient.Settings.GetCurrentLanguage()` (devuelve
 * nombres tipo "spanish"). Es asíncrono, así que se usa para corregir la
 * detección síncrona si hiciera falta.
 */
export async function confirmLang(): Promise<Lang | null> {
  try {
    const name = await SteamClient.Settings.GetCurrentLanguage();
    return name ? matchLang(name) ?? "en" : null;
  } catch {
    return null;
  }
}

export function strings(lang: Lang): Strings {
  return STRINGS[lang];
}
