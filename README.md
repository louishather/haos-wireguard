# haos-wireguard

Monitoring and ESP32 client provisioning for Home Assistant's WireGuard add-on
(`a0d7b954_wireguard`). Mainly for the portable ESP32s in louishather/esphome-config, which
reach HA through the tunnel at `a0d7b954-wireguard:<port>` (esphome-config
`common/wireguard.yaml`). Deployed by Vibe deploy (louishather/haos-vibe), packages mode.

Dashboard: **WireGuard** at `/wireguard-vibe` (registered in haos-vibe), on the boilerplate
standard tabs: Overview (peers, handshakes, traffic), Settings (add an ESP32), History, Debug.

## Entities

| Entity | Notes |
|---|---|
| `sensor.wireguard_status` | Every minute. `ok`, `partial` or `error`. Attrs: `peers` (name, tunnel address, endpoint, handshake, rx/tx, and home IP + ports for provisioned ESP32s), `connected`, `peer_count`, `addon_state`, `secrets_included`, `errors` |
| `sensor.wireguard_peers_connected` | Peers with a handshake in the last 3 min |
| `sensor.wireguard_received` / `_sent` | Bytes, all peers (reset when the add-on restarts) |
| `script.wireguard_provision` | Provisions the device typed into `input_text.wireguard_new_device` / `_new_home_ip` |
| `script.wireguard_adopt` | Copies ESP32s tunnelled by hand into the generated file; changes nothing in the add-on |
| `script.wireguard_check` | Checks provisioning can work; changes nothing |

## Provisioning an ESP32

On the dashboard's Settings tab, type the device name (`ESP32-C3-BLE-4`) and a free
10.250.5.x home IP, then **Provision**. `packages/.vibe/wireguard.py`:

1. picks the next free tunnel address (from 172.27.66.10) and port pair (API from 6053, OTA
   from 3232),
2. adds the peer to the add-on with no keys, so the add-on generates them,
3. rebuilds the add-on's `server.post_up` / `post_down`: its default rules plus a forward pair
   per ESP32, so HA and Builder reach each one at `a0d7b954-wireguard:<port>`,
4. saves the options and restarts the add-on (every tunnel drops for a few seconds),
5. writes the device's five secrets to `/config/esphome/auto-wireguard-secrets.yaml`:
   `<slug>_wireguard_private_key`, `_wireguard_internal_address`, `_home_static_ip`,
   `_wireguard_api_port`, `_wireguard_ota_port`.

That file is the list of managed devices, and blocks added to it by hand count too. Provisioning
refuses to run while the add-on forwards to a tunnel address the file doesn't list, so it can't
drop a device's forwards. It never edits `secrets.yaml` and never touches other peers (phones).

Then the device file in esphome-config reads those secrets (the dashboard shows the snippet),
gets flashed, and is added to HA's ESPHome integration at `a0d7b954-wireguard` and its API port.

## Install

1. In `/config/esphome/secrets.yaml`, add:
   ```yaml
   <<: !include auto-wireguard-secrets.yaml
   ```
2. ESP32s that are already tunnelled: on the dashboard's Settings tab, press **Adopt existing
   ESP32s**. For each tunnel address the add-on forwards to, it finds the device from the
   `<slug>_wireguard_internal_address` key in `secrets.yaml` (or an `ESP32-...` peer name), takes
   the ports from the forwards and the private key and home IP from `secrets.yaml` (or the add-on's
   key file), and adds the five keys to `auto-wireguard-secrets.yaml`. Then delete those keys
   from `secrets.yaml` (they'd win over the generated ones anyway). Or add the blocks by hand.
3. Deploy haos-vibe (it registers the dashboard and ships the shared dashboard sections), then
   watch and deploy this repo from the GitHub dashboard's **Repos** card, with **Restart instead
   of reload** the first time (new command_line sensor and shell_commands).
4. On the dashboard's Debug tab, **Run check**.
