"""WireGuard: monitor HA's WireGuard add-on and provision ESP32 clients, for packages/wireguard.yaml.

    run.sh wireguard status                      peers, handshakes and traffic (polled by a sensor)
    run.sh wireguard check                       can this script do its job? changes nothing
    run.sh wireguard provision <NAME> <HOME_IP>  add an ESP32 peer and write its secrets
    run.sh wireguard adopt                       copy ESP32s set up by hand into the generated file

Provisioning (NAME like ESP32-C3-BLE-4, HOME_IP a free 10.250.5.x address):
  1. picks the next free tunnel IP (from 172.27.66.10) and port pair (API from 6053, OTA from 3232),
  2. adds the peer to the add-on with no keys, so the add-on generates them,
  3. rebuilds server.post_up / post_down: the add-on's default rules plus a DNAT pair per device,
     so HA and ESPHome Builder reach each device at a0d7b954-wireguard:<port>,
  4. saves the options, restarts the add-on, waits for the peer's private key,
  5. rewrites /config/esphome/auto-wireguard-secrets.yaml (secrets.yaml includes it with
     `<<: !include auto-wireguard-secrets.yaml`).

That generated file is the list of managed devices: blocks added to it by hand count too.

Adopt is for ESP32s tunnelled before this existed (forwarded in post_up, keys in
secrets.yaml): it finds each one by the tunnel address its forwards point at, takes the
ports from those forwards, and the rest from secrets.yaml (or the add-on's key file), then
adds them to the generated file. It changes nothing in the add-on.

The script only reads secrets.yaml, never edits it, and never touches peers it didn't create.

Stdlib only. Prints one JSON object and always exits 0.
"""

import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ADDON = "a0d7b954_wireguard"
STATUS_URL = "http://a0d7b954-wireguard/"  # the add-on's own status API (port 80)
SUPERVISOR = "http://supervisor"
SSL_DIR = "/ssl/wireguard"
ESPHOME_DIR = "/config/esphome"
AUTO_FILE = os.path.join(ESPHOME_DIR, "auto-wireguard-secrets.yaml")
SECRETS_FILE = os.path.join(ESPHOME_DIR, "secrets.yaml")
INCLUDE_LINE = "<<: !include auto-wireguard-secrets.yaml"

TUNNEL_FIRST = ipaddress.ip_address("172.27.66.10")
TUNNEL_NET = ipaddress.ip_network("172.27.66.0/24")
HOME_NET = ipaddress.ip_network("10.250.5.0/24")
API_FIRST, OTA_FIRST = 6053, 3232
CONNECTED_WITHIN = 180  # s since last handshake (keepalive is 25 s, rekey every 2 min)

NAME_RE = re.compile(r"^ESP32-[A-Z0-9]+(-[A-Z0-9]+)*$")
FIELDS = {  # secret key suffix -> field
    "wireguard_private_key": "private_key",
    "wireguard_internal_address": "address",
    "home_static_ip": "home_ip",
    "wireguard_api_port": "api_port",
    "wireguard_ota_port": "ota_port",
}
KEY_RE = re.compile(r"^([a-z0-9_]+?)_(" + "|".join(FIELDS) + r")\s*:\s*['\"]?([^'\"#]*?)['\"]?\s*(#.*)?$")

# The add-on's own defaults (used when post_up is empty), kept so phones etc. still work.
DEFAULT_UP = [
    "iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE",
    "iptables -A FORWARD -i %i -j ACCEPT",
    "iptables -A FORWARD -o %i -j ACCEPT",
]


def out(**kw):
    print(json.dumps(kw, default=str))
    sys.exit(0)


def fail(message, **kw):
    out(ok=False, state="error", message=message, **kw)


# ------------------------------------------------------------------ Supervisor and add-on

def supervisor(method, path, body=None, timeout=20):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("no SUPERVISOR_TOKEN in Home Assistant's environment")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SUPERVISOR + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message")
        except Exception:
            msg = None
        raise RuntimeError(f"Supervisor {method} {path}: HTTP {e.code} {msg or ''}".strip())
    if res.get("result") not in (None, "ok"):
        raise RuntimeError(f"Supervisor {method} {path}: {res.get('message')}")
    return res.get("data") or {}


def addon_info():
    return supervisor("GET", f"/addons/{ADDON}/info")


def peer_status():
    """{peer name: {endpoint, latest_handshake, transfer_rx, transfer_tx}} from the add-on."""
    with urllib.request.urlopen(STATUS_URL, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def bare(addr):
    return str(addr).split("/")[0].strip()


# ------------------------------------------------------------------ the generated secrets file

def slug_of(name):
    return name.lower().replace("-", "_")


def name_of(slug):
    return slug.upper().replace("_", "-")


def read_devices():
    """{slug: {private_key, address, home_ip, api_port, ota_port}} from the generated file."""
    devices = {}
    try:
        with open(AUTO_FILE) as f:
            for line in f:
                m = KEY_RE.match(line.strip())
                if m:
                    devices.setdefault(m.group(1), {})[FIELDS[m.group(2)]] = m.group(3).strip()
    except FileNotFoundError:
        pass
    return devices


def write_devices(devices):
    lines = [
        "# Generated by louishather/haos-wireguard (packages/.vibe/wireguard.py provision / adopt).",
        "# secrets.yaml includes this file with:",
        f"#   {INCLUDE_LINE}",
        "# Keys written in secrets.yaml itself win over these. The script rewrites this file on",
        "# every provision; it keeps every device block below, including ones added by hand.",
    ]
    for slug in sorted(devices):
        d = devices[slug]
        lines += ["", f"# {name_of(slug)}"]
        for suffix, field in FIELDS.items():
            if d.get(field):
                lines.append(f'{slug}_{suffix}: "{d[field]}"')
    tmp = AUTO_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, AUTO_FILE)


def secrets_includes_file():
    try:
        with open(SECRETS_FILE) as f:
            return any(l.split("#")[0].strip() == INCLUDE_LINE for l in f)
    except OSError:
        return None


# ------------------------------------------------------------------ post_up / post_down

def forward_rules(devices, verb):
    rules = []
    for slug in sorted(devices):
        d = devices[slug]
        for port in (d.get("api_port"), d.get("ota_port")):
            if port and d.get("address"):
                rules.append(f"iptables -t nat -{verb} PREROUTING -i eth0 -p tcp --dport {port} "
                             f"-j DNAT --to-destination {d['address']}:{port}")
    return rules


def build_rules(devices):
    up = DEFAULT_UP + forward_rules(devices, "A") + ["iptables -t nat -A POSTROUTING -o %i -j MASQUERADE"]
    down = [r.replace(" -A ", " -D ") for r in up]
    return "; ".join(up), "; ".join(down)


def read_secrets():
    """{key: value} for the plain `key: "value"` lines of secrets.yaml (read only)."""
    found = {}
    try:
        with open(SECRETS_FILE) as f:
            for line in f:
                m = re.match(r"^([a-z0-9_]+)\s*:\s*['\"]?([^'\"#]*?)['\"]?\s*(#.*)?$", line.strip())
                if m:
                    found[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return found


def forwards(post_up):
    """{tunnel address: [ports]} from the DNAT rules in post_up."""
    out_ = {}
    for port, addr in re.findall(r"--dport\s+(\d+)\s+-j\s+DNAT\s+--to-destination\s+([\d.]+):\d+", post_up or ""):
        out_.setdefault(addr, []).append(int(port))
    return out_


def unmanaged_forwards(post_up, devices):
    """Tunnel addresses the current post_up forwards to that the generated file doesn't know."""
    managed = {d.get("address") for d in devices.values()}
    found = set(re.findall(r"--to-destination\s+([\d.]+):\d+", post_up or ""))
    return sorted(found - managed)


# ------------------------------------------------------------------ actions

def status():
    errors = []
    devices = read_devices()
    by_address = {d.get("address"): (slug, d) for slug, d in devices.items()}
    addon_state, peers_cfg = None, []
    try:
        info = addon_info()
        addon_state = info.get("state")
        peers_cfg = (info.get("options") or {}).get("peers") or []
    except Exception as e:
        errors.append(f"add-on: {e}")
    live = {}
    if addon_state in (None, "started"):
        try:
            live = peer_status()
        except Exception as e:
            errors.append(f"status API: {e}")

    now = time.time()
    peers, connected, rx_total, tx_total = [], 0, 0, 0
    names = [p.get("name") for p in peers_cfg] or sorted(live)
    for name in names:
        cfg = next((p for p in peers_cfg if p.get("name") == name), {})
        address = bare((cfg.get("addresses") or [""])[0])
        managed = by_address.get(address)
        s = live.get(name) or {}
        hs = int(s.get("latest_handshake") or 0)
        age = int(now - hs) if hs else None
        up = age is not None and age <= CONNECTED_WITHIN
        rx, tx = int(s.get("transfer_rx") or 0), int(s.get("transfer_tx") or 0)
        connected += up
        rx_total += rx
        tx_total += tx
        peers.append({
            "name": name, "address": address, "connected": up,
            "endpoint": None if s.get("endpoint") in (None, "", "(none)") else s.get("endpoint"),
            "handshake": hs or None, "handshake_age": age, "rx": rx, "tx": tx,
            "managed": managed is not None,
            "home_ip": managed[1].get("home_ip") if managed else None,
            "api_port": managed[1].get("api_port") if managed else None,
            "ota_port": managed[1].get("ota_port") if managed else None,
        })
    state = "error" if addon_state is None and not live else ("partial" if errors else "ok")
    out(ok=state != "error", state=state, message="; ".join(errors) or f"{connected} of {len(peers)} connected",
        errors=errors, addon_state=addon_state, peers=peers, peer_count=len(peers), connected=connected,
        rx_total=rx_total, tx_total=tx_total, managed=len(devices),
        secrets_included=secrets_includes_file())


def check():
    problems, notes = [], []
    try:
        info = addon_info()
        notes.append(f"add-on {info.get('version')} is {info.get('state')}")
        post_up = ((info.get("options") or {}).get("server") or {}).get("post_up") or ""
        stray = unmanaged_forwards(post_up, read_devices())
        if stray:
            problems.append("post_up forwards to " + ", ".join(stray) + ", which aren't in "
                            "auto-wireguard-secrets.yaml yet: press Adopt (or add their blocks by hand) "
                            "first, or provisioning will drop their forwards")
    except Exception as e:
        problems.append(f"Supervisor API: {e}")
    if not os.path.isdir(SSL_DIR):
        problems.append(f"can't see {SSL_DIR}")
    if not os.access(ESPHOME_DIR, os.W_OK):
        problems.append(f"can't write to {ESPHOME_DIR}")
    inc = secrets_includes_file()
    if inc is False:
        problems.append(f"secrets.yaml doesn't have the line `{INCLUDE_LINE}` yet")
    elif inc is None:
        problems.append("can't read secrets.yaml")
    notes.append(f"{len(read_devices())} device(s) in the generated file")
    out(ok=not problems, state="ok" if not problems else "error",
        message=("Ready. " if not problems else "") + "; ".join(problems + notes), problems=problems)


def provision(name, home_ip):
    name = (name or "").strip().upper()
    if not NAME_RE.match(name):
        fail(f"'{name}' isn't an ESP32 device name like ESP32-C3-BLE-4")
    try:
        if ipaddress.ip_address(home_ip.strip()) not in HOME_NET:
            raise ValueError
        home_ip = home_ip.strip()
    except ValueError:
        fail(f"home IP '{home_ip}' isn't a 10.250.5.x address")
    slug = slug_of(name)

    devices = read_devices()
    if slug in devices and devices[slug].get("private_key"):
        fail(f"{name} is already provisioned ({devices[slug].get('address')})")
    for other, d in devices.items():
        if d.get("home_ip") == home_ip and other != slug:
            fail(f"{home_ip} is already {name_of(other)}'s home IP")

    try:
        info = addon_info()
    except Exception as e:
        fail(f"can't reach the add-on: {e}")
    options = info.get("options") or {}
    server = options.get("server") or {}
    peers = options.get("peers") or []

    stray = unmanaged_forwards(server.get("post_up"), devices)
    if stray:
        fail("the add-on forwards to " + ", ".join(stray) + ", which aren't in "
             "auto-wireguard-secrets.yaml yet. Press Adopt (or add their blocks by hand) first, or "
             "this would drop their forwards.")

    # Tunnel address: reuse the peer's if a previous run added it, else the next free one.
    peer = next((p for p in peers if p.get("name") == name), None)
    used = {bare(a) for p in peers for a in (p.get("addresses") or [])}
    used |= {bare(a) for a in (server.get("addresses") or [])}
    used |= {d.get("address") for d in devices.values()}
    if peer and peer.get("addresses"):
        address = bare(peer["addresses"][0])
    else:
        ip = TUNNEL_FIRST
        while str(ip) in used:
            ip += 1
        if ip not in TUNNEL_NET or ip == TUNNEL_NET.broadcast_address:
            fail("no free tunnel address left in 172.27.66.0/24")
        address = str(ip)

    used_api = {int(d["api_port"]) for d in devices.values() if d.get("api_port", "").isdigit()}
    used_ota = {int(d["ota_port"]) for d in devices.values() if d.get("ota_port", "").isdigit()}
    api_port = next(p for p in range(API_FIRST, API_FIRST + 200) if p not in used_api)
    ota_port = next(p for p in range(OTA_FIRST, OTA_FIRST + 200) if p not in used_ota)

    devices[slug] = {"address": address, "home_ip": home_ip,
                     "api_port": str(api_port), "ota_port": str(ota_port)}
    if not peer:
        peers.append({"name": name, "addresses": [address]})
    server["post_up"], server["post_down"] = build_rules(devices)
    options["server"], options["peers"] = server, peers

    try:
        supervisor("POST", f"/addons/{ADDON}/options", {"options": options})
        supervisor("POST", f"/addons/{ADDON}/restart", timeout=40)
    except Exception as e:
        fail(f"couldn't update the add-on: {e}")

    key_file = os.path.join(SSL_DIR, name, "private_key")
    key = None
    for _ in range(15):
        try:
            with open(key_file) as f:
                key = f.read().strip() or None
        except OSError:
            pass
        if key:
            break
        time.sleep(1)
    if not key:
        fail(f"the peer was added and the add-on restarted, but {key_file} didn't appear; "
             "check the add-on's log, then run Provision again (it reuses the peer)",
             device=name, address=address)
    devices[slug]["private_key"] = key
    try:
        write_devices(devices)
    except OSError as e:
        fail(f"peer added, but couldn't write {AUTO_FILE}: {e}", device=name, address=address)

    note = "" if secrets_includes_file() else f" secrets.yaml still needs `{INCLUDE_LINE}`."
    out(ok=True, state="ok", device=name, slug=slug, address=address, home_ip=home_ip,
        api_port=api_port, ota_port=ota_port,
        message=f"{name}: tunnel {address}, home {home_ip}, ports {api_port}/{ota_port}.{note}")


def adopt():
    try:
        info = addon_info()
    except Exception as e:
        fail(f"can't reach the add-on: {e}")
    options = info.get("options") or {}
    peers = options.get("peers") or []
    fwd = forwards((options.get("server") or {}).get("post_up"))
    secrets = read_secrets()
    devices = read_devices()
    known = {d.get("address") for d in devices.values()}

    adopted, problems = [], []
    for address, ports in sorted(fwd.items()):
        if address in known:
            continue
        # Which device: the secrets.yaml key holding this tunnel address, else the peer's name.
        slug = next((k[: -len("_wireguard_internal_address")] for k, v in secrets.items()
                     if k.endswith("_wireguard_internal_address") and v == address), None)
        peer = next((p for p in peers if address in [bare(a) for a in p.get("addresses") or []]), None)
        if not slug and peer and NAME_RE.match((peer.get("name") or "").upper()):
            slug = slug_of(peer["name"].upper())
        if not slug:
            problems.append(f"{address}: no secrets.yaml key or ESP32-named peer says which device it is")
            continue
        api = next((p for p in ports if p >= API_FIRST), None)
        ota = next((p for p in ports if OTA_FIRST <= p < API_FIRST), None)
        key = secrets.get(f"{slug}_wireguard_private_key") or (peer or {}).get("private_key")
        if not key and peer:
            try:
                with open(os.path.join(SSL_DIR, peer.get("name", ""), "private_key")) as f:
                    key = f.read().strip() or None
            except OSError:
                pass
        home_ip = secrets.get(f"{slug}_home_static_ip")
        missing = [n for n, v in (("API port", api), ("OTA port", ota), ("private key", key),
                                  ("home IP", home_ip)) if not v]
        if missing:
            problems.append(f"{name_of(slug)}: couldn't find its {', '.join(missing)}")
            continue
        devices[slug] = {"private_key": key, "address": address, "home_ip": home_ip,
                         "api_port": str(api), "ota_port": str(ota)}
        adopted.append(f"{name_of(slug)} ({address}, ports {api}/{ota})")

    if adopted:
        try:
            write_devices(devices)
        except OSError as e:
            fail(f"couldn't write {AUTO_FILE}: {e}")
    msg = ("Adopted " + "; ".join(adopted) + ". You can now delete their keys from secrets.yaml."
           if adopted else "Nothing new to adopt.")
    if problems:
        msg += " Not adopted: " + "; ".join(problems) + "."
    out(ok=not problems, state="ok" if not problems else "partial", message=msg,
        adopted=adopted, problems=problems)


def main(argv):
    action = argv[0] if argv else ""
    try:
        if action == "status":
            status()
        elif action == "check":
            check()
        elif action == "provision" and len(argv) == 3:
            provision(argv[1], argv[2])
        elif action == "adopt":
            adopt()
        else:
            fail("usage: wireguard status | check | adopt | provision <NAME> <HOME_IP>")
    except SystemExit:
        raise
    except Exception as e:  # always one JSON object, never a traceback
        fail(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
