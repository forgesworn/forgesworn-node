#!/usr/bin/env python3
import argparse
import http.client
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
COMMAND = ROOT / "bin" / "forgesworn-node"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_decode(value):
    if value.lower() != value and value.upper() != value:
        raise ValueError("mixed-case npub")
    value = value.lower()
    separator = value.rfind("1")
    if separator < 1 or separator + 7 > len(value):
        raise ValueError("invalid npub")
    hrp, encoded = value[:separator], value[separator + 1:]
    if any(character not in BECH32 for character in encoded):
        raise ValueError("invalid npub")
    values = [BECH32.index(character) for character in encoded]
    expanded = [ord(character) >> 5 for character in hrp] + [0] + [ord(character) & 31 for character in hrp]
    polymod = 1
    for item in expanded + values:
        top = polymod >> 25
        polymod = (polymod & 0x1ffffff) << 5 ^ item
        for index, generator in enumerate((0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)):
            if top >> index & 1:
                polymod ^= generator
    if polymod != 1:
        raise ValueError("invalid npub checksum")
    payload = values[:-6]
    accumulator, bits, output = 0, 0, bytearray()
    for item in payload:
        accumulator = accumulator << 5 | item
        bits += 5
        while bits >= 8:
            bits -= 8
            output.append((accumulator >> bits) & 255)
    if hrp != "npub" or len(output) != 32:
        raise ValueError("expected an npub public key")
    return output.hex()


def owner_keys(value):
    keys = []
    for item in value.split(","):
        item = item.strip()
        if item.startswith("npub1"):
            item = bech32_decode(item)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", item):
            raise ValueError("owner keys must be npubs or 64-character hex public keys")
        keys.append(item.lower())
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("owner keys must be distinct")
    return ",".join(keys)


def control_relays(value):
    if value.strip().startswith("["):
        values = json.loads(value)
        if not isinstance(values, list):
            raise ValueError("control relays must be a list")
    else:
        values = value.split(",")
    relays = []
    for item in values:
        if not isinstance(item, str):
            raise ValueError("relay addresses must be strings")
        item = item.strip()
        if not item.startswith("wss://") or any(character.isspace() for character in item):
            raise ValueError("control relays must use wss://")
        if not re.fullmatch(r"wss://[^\s/?#]+(?:/[^\s?#]*)?(?:\?[^\s#]*)?", item):
            raise ValueError("invalid control relay")
        if "@" in item.split("/", 2)[2]:
            raise ValueError("relay credentials belong in the signer, not the URL")
        relays.append(item)
    if not 1 <= len(relays) <= 4 or len(set(relays)) != len(relays):
        raise ValueError("choose one to four distinct control relays")
    return json.dumps(relays, separators=(",", ":"))


def hostname(value):
    value = value.strip().rstrip(".")
    encoded = value.encode("idna").decode()
    if len(encoded) > 253 or "." not in encoded or not re.fullmatch(r"[a-zA-Z0-9.-]+", encoded):
        raise ValueError("use a DNS hostname such as relay.example.org")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in encoded.split(".")):
        raise ValueError("invalid DNS hostname")
    return encoded.lower()


def public_ip(value, local_test):
    address = ipaddress.IPv4Address(value.strip())
    if not local_test and not address.is_global:
        raise ValueError("PUBLIC_IP must be a globally reachable IPv4 address")
    return str(address)


def email(value):
    value = value.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("use an email address for certificate expiry notices")
    return value


def read_env():
    values = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return values


def write_env(values):
    lines = (ROOT / ".env.example").read_text().splitlines()
    result, used = [], set()
    for line in lines:
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            if key in values:
                line = f"{key}={values[key]}"
                used.add(key)
        result.append(line)
    for key, value in values.items():
        if key not in used:
            result.append(f"{key}={value}")
    temporary = ENV.with_suffix(".tmp")
    temporary.write_text("\n".join(result) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(ENV)


def ask(label, current=""):
    suffix = f" [{current}]" if current else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or current


def detect_ip():
    answer = input("Detect this host's public IPv4 with api.ipify.org? [Y/n]: ").strip().lower()
    if answer not in ("", "y", "yes"):
        return ""
    with urllib.request.urlopen("https://api.ipify.org", timeout=8) as response:
        return response.read(64).decode().strip()


def run(command):
    subprocess.run([str(COMMAND), command], cwd=ROOT, check=True)


def preflight():
    if platform.system() != "Linux":
        raise RuntimeError("this deployment profile needs Linux with host networking; use a Linux host or VPS")
    for tool in ("docker", "openssl"):
        if not shutil.which(tool):
            raise RuntimeError(f"install {tool} before running setup")
    subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True)


def check_dns(host, address):
    for name in (host, "turn." + host):
        addresses = {item[4][0] for item in socket.getaddrinfo(name, 443, socket.AF_INET)}
        if address not in addresses:
            raise RuntimeError(f"{name} resolves to {sorted(addresses) or 'no IPv4 address'}, not {address}")


def request(host, port, path, ca_file, method="GET", body=None):
    context = ssl.create_default_context(cafile=str(ca_file))
    connection = http.client.HTTPSConnection(host, port, timeout=10, context=context)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    response.read(1024)
    status = response.status
    connection.close()
    return status


def verify(values):
    host = values["PUBLIC_HOST"]
    ca_file = ROOT / "state" / "tls" / "fullchain.pem"
    for path in ("/", "/v1/status", "/v1/public/credentials", "/v1/owner/stats"):
        if request(host, 443, path, ca_file) != 404:
            raise RuntimeError(f"public gateway did not hide {path}")
    if request(host, 443, "/v1/pairings/claim", ca_file, "POST", "{}") != 401:
        raise RuntimeError("unsigned pairing was not refused")
    if request(host, 443, "/v1/pairings", ca_file, "POST", "{}") != 404:
        raise RuntimeError("owner pairing creation is publicly reachable")
    if request(host, 8443, "/", ca_file) != 200:
            raise RuntimeError("private owner UI did not answer")
    context = ssl.create_default_context(cafile=str(ca_file))
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname="turn." + host):
            pass
    print("Verified public API restrictions, private owner UI and trusted TURNS on 443.")


def main():
    parser = argparse.ArgumentParser(description="Guided standalone ForgeSworn node setup")
    parser.add_argument("command", nargs="?", choices=("setup", "verify"), default="setup")
    parser.add_argument("--public-host")
    parser.add_argument("--public-ip")
    parser.add_argument("--owner-key")
    parser.add_argument("--control-relays")
    parser.add_argument("--acme-email")
    parser.add_argument("--self-signed", action="store_true")
    parser.add_argument("--skip-dns-check", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()
    current = read_env()
    if args.command == "verify":
        verify(current)
        return
    try:
        preflight()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Setup cannot continue: {error}\n")
    local_test = args.self_signed or current.get("SPRY_LOCAL_TEST") == "true"
    interactive = not args.non_interactive
    host = args.public_host or (ask("Public hostname", current.get("PUBLIC_HOST", "")) if interactive else current.get("PUBLIC_HOST", ""))
    address = args.public_ip or current.get("PUBLIC_IP", "")
    if not address and interactive:
        address = detect_ip() or ask("Public IPv4 address")
    owner = args.owner_key or (ask("Owner npub or hex public key", current.get("OWNER_KEYS", "")) if interactive else current.get("OWNER_KEYS", ""))
    relays = args.control_relays or (ask("Your Nostr relays, comma-separated", current.get("CONTROL_RELAYS", "")) if interactive else current.get("CONTROL_RELAYS", ""))
    contact = args.acme_email or (ask("Email for certificate notices", current.get("ACME_EMAIL", "")) if interactive else current.get("ACME_EMAIL", ""))
    try:
        host = hostname(host)
        address = public_ip(address, local_test)
        owner = owner_keys(owner)
        relays = control_relays(relays)
        contact = email(contact)
        if not args.skip_dns_check and not local_test:
            check_dns(host, address)
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"Setup cannot continue: {error}\n")
    current.update(PUBLIC_HOST=host, ADMIN_HOST=host, PUBLIC_IP=address,
                   OWNER_KEYS=owner, CONTROL_RELAYS=relays, ACME_EMAIL=contact,
                   ADMIN_BIND=current.get("ADMIN_BIND", "127.0.0.1"),
                   SPRY_LOCAL_TEST="true" if local_test else "false")
    write_env(current)
    try:
        run("init")
        run("up")
        if not args.self_signed:
            run("certify")
        if not args.skip_verify:
            verify(current)
    except (subprocess.CalledProcessError, OSError, RuntimeError, ssl.SSLError) as error:
        print(f"Setup has not completed: {error}", file=sys.stderr)
        print("Configuration and private state are retained. Correct the problem and run setup again.", file=sys.stderr)
        raise SystemExit(1)
    print("\nYour standalone Spry node is running.")
    print(f"Owner URL: https://{host}:8443")
    if current["ADMIN_BIND"] == "127.0.0.1":
        print(f"SSH tunnel: ssh -N -L 8443:127.0.0.1:8443 <ssh-user>@{address}")
        print("Then open https://localhost:8443")
    print("Next: choose Pair with KithMoot. Public admin and anonymous credentials remain closed.")


if __name__ == "__main__":
    main()
