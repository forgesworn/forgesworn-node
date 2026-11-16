#!/usr/bin/env python3
import sys

from setup import bech32_encode, hostname, owner_keys


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: wok-config.py PUBLIC_HOST OWNER_KEYS")
    host = hostname(sys.argv[1])
    owners = owner_keys(sys.argv[2]).split(",")
    members = ", ".join(f'"{bech32_encode("npub", bytes.fromhex(owner))}"' for owner in owners)
    print(f'''listen = "127.0.0.1:7447"
url = "wss://{host}/events"
data_dir = "/data"
max_store_bytes = 1073741824
min_free_bytes = 268435456
members = [{members}]
auth_deadline_secs = 30
relay_information = true
workers = 2
''')


if __name__ == "__main__":
    main()
