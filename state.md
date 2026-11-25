# feat/clients — state

Resume notes for Claude. Delete before merging to main.

Plan agreed with Louis 2026-11-25 (see chat): monitoring + ESP32 client provisioning for the
WireGuard add-on, dashboard on haos-vibe's boilerplate tabs with shared `_shared/` sections.

## Decisions (Louis)
- Own repo (this one). haos-vibe read-only token has access.
- BLE-2 / BLE-3 (already flashed): Louis moves their secrets into auto-wireguard-secrets.yaml
  himself; the script refuses to provision while post_up forwards to an address that isn't in
  that file. No adoption code.
- post_up/post_down: script owns them (only ESP32 rules there today).
- No alerts for now.
- Peer names upper case (ESP32-C3-BLE-4); slugs lower case in keys/files.

## Done
- main: scaffold (CI, yamllint, run.sh, CLAUDE.md).
- haos-vibe feat/boilerplate: `_shared/section_links.yaml`, demo uses it, /wireguard-vibe
  registered + in smart_notify button list.
- `.vibe/wireguard.py` status/check/provision, tested locally with a fake Supervisor.

## Next
- DONE: packages/wireguard.yaml, dashboard (templates rendered against live HA), README.
- DONE: esphome-config feat/wireguard-port-secrets (BLE-2 + README + CI) and
  feat/as5600-ble-3 (BLE-3) read ports from secrets.
- NEXT: Louis: secrets include line + move BLE-2/BLE-3 into auto file (5 keys each), deploy
  haos-vibe feat/boilerplate (restart), deploy this branch (restart), Run check, then a real
  provision. Unverified live: SUPERVISOR_TOKEN in shell_command's env, /ssl readable from core,
  cross-repo !include of _shared/section_links.yaml.
