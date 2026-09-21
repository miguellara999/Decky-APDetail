# APDetail (plugin Decky para Steam Deck)

Lee `DESARROLLO.md` antes de tocar nada: explica la arquitectura, por qué se usa `iw` + `iwctl debug`
(SteamOS usa iwd) y cómo depurar en la Deck.

- Compilar/probar: este VS Code corre en Flatpak; ejecuta node/pnpm en el host con
  `flatpak-spawn --host sh -c 'cd <proyecto> && pnpm run build'`.
- Zip instalable: `./scripts/build-zip.sh` → `out/APDetail.zip`.
- Pruebas del backend en el PC: scripts en `.devtest/` (gitignored, con stub de `decky`).
