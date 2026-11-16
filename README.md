# ForgeSworn standalone node

An operator-owned Spry pairing and STUN/TURN service without Archipelago.
KithMoot remains the calling application. No ForgeSworn account, telemetry,
public administrator or anonymous credential issuer is installed.

Status: deployment candidate, not a published or production-qualified release.
The included image is built locally from a reviewed checkout; a pinned published
image is a separate release step.

## Requirements

- Linux x86-64 or ARM64 with Docker and the Compose plugin.
- A public IPv4 address and ports available on the host. The current profile
  uses host networking for native TURN sockets and is not a macOS/Windows
  deployment recipe.
- `relay.example.org` and `turn.relay.example.org` in DNS, replaced with names
  you control. TCP 80 and 443, UDP/TCP 3478, TCP 5349 and UDP 49160–49191 must
  reach the host. Outbound UDP is still required when clients use TCP or TLS.
- An owner Nostr public key and the Nostr relays the owner deliberately uses.
- OpenSSL for the local bootstrap certificate.

## Set up

```sh
./bin/forgesworn-node setup
```

The guided setup asks for one hostname, the owner npub or hex key, the owner's
Nostr relays and an email for certificate notices. It can detect the public
IPv4 with your permission, checks DNS, generates private state, starts the
service, obtains a trusted certificate and verifies the public restrictions and
TURNS listener. It is safe to resume after correcting a failed step.

The ACME command registers or uses the configured Certbot account and accepts
its terms. It opens no dashboard. Certificate replacement restarts Spry and
closes active TURN allocations.

Leave `ADMIN_BIND=127.0.0.1` to administer through the SSH tunnel printed at the
end, or set the host's VPN address and restrict that address/port in the host
and VPN firewalls. Clients never need the admin listener. Do not expose it
publicly.

The advanced `.env` file is written with mode 0600. Normal operators do not need
to edit allocation limits, origins or image settings. `SPRY_SOURCE` points at a
checkout used for a local image build and will be replaced by a pinned published
image before release. Do not use `SPRY_LOCAL_TEST=true` outside generated local
fixtures.

For unattended setup, the same command accepts `--public-host`, `--public-ip`,
`--owner-key`, `--control-relays`, `--acme-email` and `--non-interactive`.
Use `./bin/forgesworn-node verify` to repeat the external checks.

Then open the owner URL through the private administration path and choose
**Pair with KithMoot**. Public TCP 443 routes `turn.PUBLIC_HOST` to Spry's TURN
TLS listener and `PUBLIC_HOST` only to these signed API paths:

- pairing claim and removal;
- room grants, device registration, vouching and removal;
- short-lived credentials and peer registration.

The public gateway returns 404 for the owner UI, owner statistics, status and
anonymous public-credential path. `SPRY_PUBLIC` remains off.

## Operate

```sh
./bin/forgesworn-node status
./bin/forgesworn-node restart
./bin/forgesworn-node renew
./bin/forgesworn-node down
```

Run `renew` from a host timer. It restarts Spry and the gateway after every
renewal attempt; every restart closes active allocations. A hot certificate
reload and seamless call migration are not implemented.

`state/` contains the TURN root secret, private TLS material and ACME state.
Pairing state is in the separate `spry-state` Docker volume. Keep both private
and include both in an operator-controlled encrypted backup. The Compose
secrets are mounted into the container rather than placed in its inspected
environment. The Spry process runs as uid 10001 with a read-only root
and no capabilities. Host networking reduces network-namespace isolation; the
host firewall remains an exposure boundary.

## Privacy and scope

Spry handles connecting and peer addresses, credential identifiers, allocation
state and forwarded encrypted packets. Pairing state and public keys persist.
The relay does not receive room media keys. Nginx access logs are disabled, but
host, journald, crash, VPN and provider logging require separate inspection.
This is metadata minimisation, not a claim of no metadata or no applicable law.

Wok, Wildbloom, backup automation and the NixOS module are separate delivery
milestones and are not included in this Compose profile.
