#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
set -a
. "$ROOT/.env"
set +a

STORE=${CADDY_STORE:-/var/lib/caddy/.local/share/caddy/certificates}
TLS="$ROOT/state/tls"
PUBLIC_CERT=$(find "$STORE" -type f -name "$PUBLIC_HOST.crt" -print -quit 2>/dev/null || true)
TURN_CERT=$(find "$STORE" -type f -name "turn.$PUBLIC_HOST.crt" -print -quit 2>/dev/null || true)

if [[ -z "$PUBLIC_CERT" || -z "$TURN_CERT" ]]; then
    echo "Caddy must hold certificates for $PUBLIC_HOST and turn.$PUBLIC_HOST." >&2
    exit 1
fi
[[ -s "${PUBLIC_CERT%.crt}.key" && -s "${TURN_CERT%.crt}.key" ]]

OWNER_USER=$(stat -c '%u' "$TLS")
OWNER_GROUP=$(stat -c '%g' "$TLS")
changed=0

sync_one() {
    local source=$1 destination=$2 mode=$3
    if [[ ! -f "$destination" ]] || ! cmp -s "$source" "$destination"; then
        install -m "$mode" -o "$OWNER_USER" -g "$OWNER_GROUP" "$source" "$destination.tmp"
        mv -f "$destination.tmp" "$destination"
        changed=1
    fi
}

sync_one "$PUBLIC_CERT" "$TLS/fullchain.pem" 0644
sync_one "${PUBLIC_CERT%.crt}.key" "$TLS/privkey.pem" 0600
sync_one "$TURN_CERT" "$TLS/turn-fullchain.pem" 0644
sync_one "${TURN_CERT%.crt}.key" "$TLS/turn-privkey.pem" 0600

if [[ "$changed" -eq 1 ]]; then
    docker compose --env-file "$ROOT/.env" -f "$ROOT/compose.yaml" restart spry gateway
fi
