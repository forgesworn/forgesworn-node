# ForgeSworn standalone node

An operator-owned Spry pairing and STUN/TURN service, private Wok Nostr relay
and Wildbloom encrypted-blob store, without Archipelago. KithMoot remains the
calling application. No ForgeSworn account, telemetry, public administrator or
anonymous credential issuer is installed.

Status: deployment candidate, not a production-qualified release. Spry, Wok and
Wildbloom default to pinned public GHCR image digests. A live public host,
cross-network TURN and physical-device acceptance are separate qualification
steps.

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
service, obtains a trusted certificate and verifies the public restrictions,
Wok relay information and TURNS listener. It is safe to resume after correcting
a failed step.

The ACME command registers or uses the configured Certbot account and accepts
its terms. It opens no dashboard. Certificate replacement restarts Spry and
closes active TURN allocations.

Leave `ADMIN_BIND=127.0.0.1` to administer through the SSH tunnel printed at the
end, or set the host's VPN address and restrict that address/port in the host
and VPN firewalls. Clients never need the admin listener. Do not expose it
publicly.

The advanced `.env` file is written with mode 0600. Normal operators do not need
to edit allocation limits, origins or image settings. Do not use
`SPRY_LOCAL_TEST=true` outside generated local fixtures.

For unattended setup, the same command accepts `--public-host`, `--public-ip`,
`--owner-key`, `--control-relays`, `--acme-email` and `--non-interactive`.
Use `./bin/forgesworn-node verify` to repeat the external checks.

## Existing Caddy host

Docker hosts already serving other HTTPS sites can use `--shared-proxy`. This
keeps Caddy on public 80/443, binds the node's public HTTP gateway to
`127.0.0.1:9080`, and adds an SNI-only route for `turn.PUBLIC_HOST` to Spry's
TLS listener. Other Caddy sites stay on their existing TLS path. The shared
profile defaults to TURN 3479, TLS 5350, relay ports 49500–49531 and Wildbloom
`127.0.0.1:3743`; change those values if the host already uses them. Open the
selected TURN UDP/TCP and relay UDP ports in both host and provider firewalls.
The direct TLS port needs no public rule: Caddy reaches it over the host's own
public address and external access remains through TLS/443. TLS/443 still
requires outbound UDP for the peer connections it relays.

Render `caddy/forgesworn-node.Caddyfile.template` with `PUBLIC_HOST` and import
it from Caddy. Render `caddy/layer4-turn.route.template` with `PUBLIC_HOST`,
`PUBLIC_IP` and `SPRY_TLS_PORT`, then insert it inside the
existing `servers :443` layer4 listener wrapper, before Caddy's normal `tls`
wrapper; this requires Caddy's layer4 plugin. Validate the complete Caddy
configuration and reload it. Do not replace an existing layer4 configuration or
its other routes. The public site and `turn.` site each need their own Caddy
certificate. Spry's direct TLS URL is omitted in this profile because that
certificate is for the TURN name; the SNI-proxied TLS/443 URL remains. Caddy's
existing ACME account and terms are reused; shared setup needs no separate ACME
email and does not run Certbot.

Install `caddy/forgesworn-node-certs.service` and `.timer`, adjust the unit's
`/opt/forgesworn-node` path if needed, then enable the timer. The service runs
`caddy/sync-certs.sh` as root to copy both certificate pairs out of Caddy's
private store and restarts Spry and the gateway only when a certificate changes.
Run `./bin/forgesworn-node sync-certs` once after Caddy has issued both
certificates, then `./bin/forgesworn-node verify`. `setup --shared-proxy` also
runs this certificate step. Certificate replacement closes active TURN
allocations, as in the dedicated profile.

This is shared-host operation, not machine isolation: the containers share the
host kernel, network, firewall and capacity with every other tenant. Host
networking remains in use. Keep the owner UI on loopback or a restricted VPN
address and review host/provider logging separately.

Then open the owner URL through the private administration path and choose
**Pair with KithMoot**. Public TCP 443 routes `turn.PUBLIC_HOST` to Spry's TURN
TLS listener and `PUBLIC_HOST` only to these signed API paths:

- pairing claim and removal;
- room grants, device registration, vouching and removal;
- short-lived credentials and peer registration.

`PUBLIC_HOST/events` is the Wok WebSocket endpoint. Every room read and write
requires NIP-42 authentication as an operator-listed keeper or as a guest with
a current signed room grant. Its unauthenticated NIP-11 document names no
keeper or guest. Ordinary guest grants cover room text and presence, not calls,
new invitations, rekeys or protected MLS.

Wildbloom accepts signed uploads and mirrors from owner keys at `/upload` and
`/mirror`, plus signed listing at `/list/<pubkey>`. Blob downloads by SHA-256
need no token, as Blossom intends. Uploads are capped at 256 MiB and total
storage at 10 GiB. Direct HTTPS mirrors accept only publicly reachable sources;
loopback origins are refused. Discovery and checkout remain closed.

The public gateway returns 404 for the owner UI, owner statistics, status and
anonymous public-credential path. `SPRY_PUBLIC` remains off.

## Operate

```sh
./bin/forgesworn-node status
./bin/forgesworn-node restart
./bin/forgesworn-node renew
./bin/forgesworn-node down
```

Run `renew` from a host timer in the dedicated profile. It restarts Spry and the
gateway after every renewal attempt. The shared profile instead uses its Caddy
certificate timer and restarts only when certificate bytes change. Every restart
closes active allocations. A hot certificate reload and seamless call migration
are not implemented.

`state/` contains the TURN root secret, private TLS material and ACME state,
plus the non-secret generated Wok configuration. Pairing state is in
`spry-state`, Wok events and grant authority in `wok-state`, and encrypted
blobs and their metadata in `wildbloom-state`. Keep all three volumes and the
host directory private and include them in every backup. Compose secrets are
mounted into containers rather than placed in their inspected environments.
Spry and Wok run as uid 10001 with read-only roots and no capabilities. The
state directories are mode 0700. Secret and private-key files beneath them are
mode 0644 so Docker's bind-mounted secrets remain readable by that uid; do not
broaden the containing directory permissions. Host networking reduces
network-namespace isolation; the host firewall remains an exposure boundary.

## Privacy and scope

Spry handles connecting and peer addresses, credential identifiers, allocation
state and forwarded encrypted packets. Pairing state and public keys persist.
Wok stores public keys, signed grants, event metadata and whatever clients send;
its relay grant does not replace KithMoot's invitation or room-key admission.
Wildbloom stores ciphertext, blob hashes and signing keys; anyone with a hash
can request the ciphertext. None of these services receives room media keys.
Nginx access logs are disabled, but host, journald, crash, VPN and provider
logging require separate inspection. This is metadata minimisation, not a claim
of no metadata or no applicable law.

## Back up and restore

```sh
./bin/forgesworn-node backup
./bin/forgesworn-node restore [backup/forgesworn-node-YYYYMMDDTHHMMSSZ.tar.enc]
```

Backup stops the writers, archives `state/` and all three Docker volumes, then
encrypts and authenticates the result with an operator passphrase. Restore
verifies that passphrase and the archive before replacing current state. Keep
the passphrase separately; losing it makes the backup unusable. Restore prompts
before replacing anything (`FORGESWORN_RESTORE_YES=1` skips that prompt for
automation). There is no scheduled backup or off-host copy: put the encrypted
file somewhere durable and test recovery yourself.

## NixOS

Import `nix/` and set the same inputs. For example:

```nix
services.forgesworn-node = {
  enable = true;
  publicHost = "relay.example.org";
  publicIp = "203.0.113.10";
  ownerKeys = [ "1b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f" ];
  controlRelays = [ "wss://relay.primal.net" ];
  acmeEmail = "operator@example.org";
  acceptAcmeTerms = true;
};
```

The module enables Docker, applies the public firewall ports and reuses the
Compose bundle and backup commands. Its Nix store bundle uses an explicit file
allowlist: local `.git`, `state/` and `backup/` content is never copied. It
creates no Nostr secret and accepts no ACME terms unless `acceptAcmeTerms = true`.
Keep `adminBind` on loopback or a VPN address. The module selects Docker 29:
NixOS 25.11's default Docker 28 package is now refused by Nixpkgs as insecure.
A complete NixOS 25.11 machine configuration, its assertions, firewall and
service commands evaluate successfully. The generated ARM64 bundle builds with
the required filenames and no operator state. The module has not been exercised
on a NixOS host. Docker on Linux is the tested deployment path.
