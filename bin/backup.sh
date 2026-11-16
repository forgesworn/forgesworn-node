#!/bin/sh
set -eu

backup_password() {
    if [ -n "${FORGESWORN_BACKUP_PASSWORD:-}" ]; then
        PASSWORD=$FORGESWORN_BACKUP_PASSWORD
    else
        printf 'Backup passphrase: ' >&2
        IFS= read -r PASSWORD
    fi
    if [ -z "$PASSWORD" ]; then
        echo 'A backup passphrase is required.' >&2
        exit 1
    fi
}

backup_salt() {
    openssl rand -hex 8
}

backup_derive() {
    derive_salt=$1
    material=$(printf '%s\n' "$PASSWORD" | openssl enc -aes-256-ctr -pbkdf2 -iter 600000 -salt -S "$derive_salt" -P -pass stdin)
    DERIVED_KEY=$(printf '%s\n' "$material" | sed -n 's/^key=//p')
    DERIVED_IV=$(printf '%s\n' "$material" | sed -n 's/^iv =//p')
    test -n "$DERIVED_KEY" && test -n "$DERIVED_IV"
}

backup_encrypt() {
    input=$1
    output=$2
    salt=$(backup_salt)
    backup_derive "$salt"
    openssl enc -aes-256-ctr -K "$DERIVED_KEY" -iv "$DERIVED_IV" -in "$input" -out "$output"
    mac_salt=$(backup_salt)
    backup_derive "$mac_salt"
    mac=$(openssl dgst -sha256 -hmac "$DERIVED_KEY" -hex "$output")
    mac=${mac##* }
    printf 'version=1\nsalt=%s\nmac_salt=%s\nhmac=%s\n' "$salt" "$mac_salt" "$mac" > "$output.meta"
}

backup_verify() {
    input=$1
    test -f "$input" && test -f "$input.meta"
    salt=$(sed -n 's/^salt=//p' "$input.meta")
    mac_salt=$(sed -n 's/^mac_salt=//p' "$input.meta")
    expected=$(sed -n 's/^hmac=//p' "$input.meta")
    test -n "$salt" && test -n "$mac_salt" && test -n "$expected"
    backup_derive "$mac_salt"
    actual=$(openssl dgst -sha256 -hmac "$DERIVED_KEY" -hex "$input")
    actual=${actual##* }
    if [ "$actual" != "$expected" ]; then
        echo 'Backup authentication failed. No state was changed.' >&2
        exit 1
    fi
    backup_derive "$salt"
    openssl enc -d -aes-256-ctr -K "$DERIVED_KEY" -iv "$DERIVED_IV" -in "$input" -out "$2"
}

backup_create() {
    backup_password
    mkdir -p "$ROOT/backup"
    work=$(mktemp -d "$ROOT/backup/work.XXXXXX")
    trap '$COMPOSE start; rm -rf "$work"' EXIT INT TERM
    $COMPOSE stop
    docker run --rm \
        -v "$ROOT/state:/state:ro" \
        -v forgesworn-node_spry-state:/spry:ro \
        -v forgesworn-node_wok-state:/wok:ro \
        -v forgesworn-node_wildbloom-state:/wildbloom:ro \
        -v "$work:/backup" \
        debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 \
        tar -C / -cf /backup/bundle.tar state spry wok wildbloom
    name=$(date -u +%Y%m%dT%H%M%SZ)
    backup_encrypt "$work/bundle.tar" "$ROOT/backup/forgesworn-node-$name.tar.enc"
    $COMPOSE start
    trap - EXIT INT TERM
    rm -rf "$work"
    echo "Created backup/forgesworn-node-$name.tar.enc and .meta. Keep the passphrase separately."
}

backup_restore() {
    input=${1:-}
    if [ -z "$input" ]; then
        input=$(ls -1t "$ROOT"/backup/forgesworn-node-*.tar.enc | head -n 1)
    fi
    backup_password
    mkdir -p "$ROOT/backup"
    work=$(mktemp -d "$ROOT/backup/restore.XXXXXX")
    trap 'rm -rf "$work"' EXIT INT TERM
    backup_verify "$input" "$work/bundle.tar"
    docker run --rm -v "$work:/backup" debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 \
        tar -C /backup -xf /backup/bundle.tar
    test -s "$work/state/spry-turn-secret"
    test -s "$work/state/tls/fullchain.pem"
    test -s "$work/state/tls/privkey.pem"
    test -s "$work/state/wokd.toml"
    test -d "$work/spry" && test -d "$work/wok" && test -d "$work/wildbloom"
    if [ "${FORGESWORN_RESTORE_YES:-}" != "1" ]; then
        printf 'Restore %s and replace current state? [y/N] ' "$input" >&2
        IFS= read -r answer
        if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
            echo 'Restore cancelled. No state was changed.' >&2
            exit 1
        fi
    fi
    $COMPOSE down -v
    rm -rf "$ROOT/state"
    mkdir -p "$ROOT/state"
    cp -a "$work/state/." "$ROOT/state/"
    docker run --rm \
        -v "$work:/restore:ro" \
        -v forgesworn-node_spry-state:/spry \
        -v forgesworn-node_wok-state:/wok \
        -v forgesworn-node_wildbloom-state:/wildbloom \
        debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 \
        sh -c 'cp -a /restore/spry/. /spry/; cp -a /restore/wok/. /wok/; cp -a /restore/wildbloom/. /wildbloom/'
    $COMPOSE up -d --wait
    trap - EXIT INT TERM
    rm -rf "$work"
    echo 'Restore completed and services are healthy. Run setup verify and your room/storage checks.'
}
