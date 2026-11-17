#!/bin/sh
set -eu

install -m 0644 "$RENEWED_LINEAGE/fullchain.pem" /tls/fullchain.pem
install -m 0600 "$RENEWED_LINEAGE/privkey.pem" /tls/privkey.pem
install -m 0644 "$RENEWED_LINEAGE/fullchain.pem" /tls/turn-fullchain.pem
install -m 0600 "$RENEWED_LINEAGE/privkey.pem" /tls/turn-privkey.pem
