# Working in this repo

Project repo for Louis's HAOS setup, deployed by Vibe deploy (louishather/haos-vibe) in
packages mode: `packages/` becomes `/config/vibe/packages/haos_wireguard/`.

Shared rules for every repo (naming, alerts, dashboards, how to build a feature, branches,
CI) are in `CONVENTIONS.md` in louishather/haos-vibe. Read it before adding anything.

## What it is
Monitoring and client provisioning for Home Assistant's WireGuard add-on
(`a0d7b954_wireguard`), mainly for the portable ESP32s in louishather/esphome-config that
reach HA through the tunnel (esphome-config `common/wireguard.yaml`).

## Rules
- One package, `packages/wireguard.yaml`. Line 1 is `# <Title>: what it does`; every
  `unique_id` and key starts with `wireguard`.
- Built as a `.vibe` script (CONVENTIONS "How to build a feature", option 3): it uses the
  Supervisor API and files, which templates can't. `packages/.vibe/wireguard.py` is stdlib
  only, prints one JSON object and always exits 0. `packages/.vibe/run.sh` is a copy of
  haos-vibe's.
- The script owns the add-on's `server.post_up` / `server.post_down` and the generated
  `/config/esphome/wireguard/secrets.yaml`. It never edits `secrets.yaml` itself, and
  never touches add-on peers it didn't create (phones etc.).
- ESP32 peers are named after the device in upper case (`ESP32-C3-BLE-4`); secret keys,
  file names and YAML use the lower-case slug (`esp32_c3_ble_4_...`).
- The dashboard (`packages/.dashboards/wireguard.yaml`, `/wireguard-vibe`) is registered in
  haos-vibe's `packages/dashboards.yaml`. It follows haos-vibe's boilerplate standard tabs
  (overview, settings, history, debug) and includes shared sections from haos-vibe's
  `packages/.dashboards/_shared/` via `../../repo/.dashboards/_shared/...`.
- Run `yamllint packages ci` before committing.
- Work on `feat/<thing>` or `fix/<thing>`. Louis deploys the branch from his phone, then merges.
  On long work keep `state.md` at the branch root, and delete it before merging.
- CI: `.github/workflows/validate.yml` (yamllint + HA config check), cut down from
  haos-vibe's. Keep it lean per CONVENTIONS "CI".
- New command_line sensors and shell_commands need "Restart instead of reload".
