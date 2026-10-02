# APDetail

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that shows which WiFi
access point (BSSID) your Steam Deck is connected to, and lets you switch to a different AP on the
same SSID. Useful on networks with several access points (mesh, repeaters, powerline adapters)
where the Deck gets "stuck" on the furthest one.

## Features

- Current connection at a glance: SSID, BSSID, AP vendor, signal (live dBm and %), band, channel,
  link rate and IP address.
- All visible APs on the same SSID, sorted by signal, each with vendor, MAC, band, channel, dBm/%
  and how old the reading is. A toggle shows every network instead.
- Switch to a specific AP by tapping it — a fast reassociation that does not drop the connection.

## Usage

1. Open the Quick Access Menu (…) → APDetail.
2. The first time, press **Enable iwd developer mode**. This is required on SteamOS in order to
   choose an AP — see [SteamOS and iwd](#steamos-and-iwd) below. WiFi drops for a few seconds and
   reconnects on its own.
3. Tap the AP you want to switch to. A toast confirms the change and the BSSID at the top updates.

The plugin follows the Steam UI language: Spanish when Steam is in Spanish, English otherwise.

While the panel is open the list refreshes every 10 s, and every 30 s it runs a scan targeted at
the channels your SSID uses. **Rescan** runs a full scan. Nothing is scanned once the panel is
closed.

**Reading the signal:** compare APs in **dBm** — every AP is measured from the same source on the
same scale, and the one in use is read live from the link. Differences under ~6 dB are noise.
"N s ago" means the reading comes from the last scan in which that AP was heard; "last seen N s
ago" means the kernel already expired it and the plugin is showing it from its own memory (up to
3 minutes).

## SteamOS and iwd

SteamOS (3.5+) uses **iwd** as NetworkManager's WiFi backend. iwd groups APs by network and does
not expose BSSID selection to NetworkManager, which has two consequences:

- The AP list is read straight from the driver with `iw`, because NetworkManager only ever shows
  one BSSID per SSID.
- Switching AP uses `iwctl debug <dev> roam <bssid>`, which **only exists when iwd runs in
  developer mode**. The plugin has a button that creates the drop-in
  `/etc/systemd/system/iwd.service.d/apdetail-developer.conf` and restarts iwd; the same button
  then offers to revert it and leave iwd exactly as it was.

  Developer mode exposes extra D-Bus interfaces (root only) and **disables iwd's autoconnect**
  (`station_create` in iwd's `src/station.c`), which would stop the Deck from reconnecting by
  itself after suspend. The plugin compensates for this: a background watchdog re-enables the
  `AutoConnect` property (on `StationDebug`) whenever it finds it off. Scanning, roaming and power
  consumption are unaffected.

  **Uninstalling** the plugin reverts developer mode on its own: the drop-in is removed and iwd is
  restarted in normal mode 90 s later (it reconnects by itself). **Updating** the plugin changes
  nothing — the new version cancels that pending restart.

  Manual equivalent:

  ```bash
  sudo mkdir -p /etc/systemd/system/iwd.service.d
  sudo tee /etc/systemd/system/iwd.service.d/apdetail-developer.conf >/dev/null <<'EOF'
  [Service]
  ExecStart=
  ExecStart=/usr/lib/iwd/iwd --developer
  EOF
  sudo systemctl daemon-reload && sudo systemctl restart iwd
  ```

  WiFi drops for a few seconds and reconnects. To revert, delete that file and repeat
  `daemon-reload` + `restart iwd`.

- With iwd there is no BSSID "pinning": after a switch, iwd stays on that AP until the signal
  falls below its roaming threshold (−70 dBm by default) and it decides for itself again.

On systems using wpa_supplicant (not SteamOS) the plugin pins `802-11-wireless.bssid` on the
NetworkManager profile instead, and the AP stays pinned until you press the button that clears it.

## Installing

Grab a release zip, or build one yourself (see below), then on the Deck:
Decky → ⚙ → Developer → **Install plugin from zip**.

## Development

Requirements: Node.js 18+, pnpm.

```bash
pnpm install
pnpm run build     # builds dist/index.js
pnpm run watch     # rebuild on save
```

### Deploy to the Deck over SSH

```bash
DECK_HOST=deck@steamdeck ./scripts/deploy.sh
```

### Build an installable zip

```bash
./scripts/build-zip.sh   # -> out/APDetail.zip
```

## How it works

- **Backend** (`main.py`, runs as root): `nmcli` for connection state, `iw` for the BSS list and
  live signal, `iwctl`/`busctl` (iwd's `StationDebug` API) to switch AP, scan specific channels and
  keep autoconnect enabled. Vendor lookup uses an embedded IEEE OUI database and works offline.
- **Frontend** (`src/index.tsx`): React + `@decky/ui`.
- Tested on SteamOS (iwd backend) with a two-AP network (devolo + MikroTik) sharing one SSID.

See [DESARROLLO.md](DESARROLLO.md) for the full architecture, the reasoning behind each decision
and debugging notes. **That document is written in Spanish**; the sections above cover what you
need to use the plugin, and the code is the best reference beyond that. Backend log messages are
also in Spanish.

## Contributing

Issues and pull requests are welcome. Two things that would help most:

- **More UI languages.** All user-facing strings live in `src/i18n.ts`, which currently ships
  Spanish and English. Adding a language means copying the `en` block, translating the values and
  listing the locale prefix in `LOCALE_PREFIXES` — no changes anywhere else.
- **Testing on other setups** — other mesh systems, 6 GHz APs, or SteamOS versions where the iwd
  unit differs from upstream.

## License

[MIT](LICENSE)
