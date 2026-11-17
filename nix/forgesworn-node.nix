{ config, lib, pkgs, ... }:

let
  cfg = config.services.forgesworn-node;
  bundle = pkgs.runCommand "forgesworn-node-bundle" { } ''
    mkdir -p $out/bin $out/certbot $out/gateway $out/nix $out/tests
    cp ${../.env.example} $out/.env.example
    cp ${../.gitignore} $out/.gitignore
    cp ${../LICENSE} $out/LICENSE
    cp ${../README.md} $out/README.md
    cp ${../compose.yaml} $out/compose.yaml
    cp -r ${../bin}/. $out/bin/
    cp -r ${../certbot}/. $out/certbot/
    cp -r ${../gateway}/. $out/gateway/
    cp -r ${../nix}/. $out/nix/
    cp -r ${../tests}/. $out/tests/
  '';
  environmentFile = pkgs.writeText "forgesworn-node.env" ''
    PUBLIC_HOST=${cfg.publicHost}
    ADMIN_HOST=${cfg.publicHost}
    PUBLIC_IP=${cfg.publicIp}
    ADMIN_BIND=${cfg.adminBind}
    OWNER_KEYS=${lib.concatStringsSep "," cfg.ownerKeys}
    CONTROL_RELAYS=${builtins.toJSON cfg.controlRelays}
    KITHMOOT_URL=${cfg.kithmootUrl}
    ALLOWED_ORIGINS=${lib.concatStringsSep "," cfg.allowedOrigins}
    ACME_EMAIL=${cfg.acmeEmail}
    SPRY_IMAGE=${cfg.spryImage}
    WOK_IMAGE=${cfg.wokImage}
    WILDBLOOM_IMAGE=${cfg.wildbloomImage}
    SPRY_LOCAL_TEST=false
    MAX_ALLOCATIONS=${toString cfg.maxAllocations}
    MAX_ALLOCATIONS_PER_USER=${toString cfg.maxAllocationsPerUser}
    MAX_TCP_CONNECTIONS=${toString cfg.maxTcpConnections}
    BYTES_PER_SECOND=${toString cfg.bytesPerSecond}
    AGGREGATE_BYTES_PER_SECOND=${toString cfg.aggregateBytesPerSecond}
  '';
in
{
  options.services.forgesworn-node = {
    enable = lib.mkEnableOption "the standalone ForgeSworn node";

    publicHost = lib.mkOption {
      type = lib.types.str;
      example = "relay.example.org";
      description = "Public DNS hostname for Spry, Wok and Wildbloom.";
    };
    publicIp = lib.mkOption {
      type = lib.types.str;
      example = "203.0.113.10";
      description = "Public IPv4 address clients reach.";
    };
    adminBind = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Loopback or VPN address for the private owner UI.";
    };
    ownerKeys = lib.mkOption {
      type = lib.types.nonEmptyListOf lib.types.str;
      description = "Hex Nostr public keys allowed to administer and write.";
    };
    controlRelays = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "WSS Nostr relays used for Spry control messages.";
    };
    acmeEmail = lib.mkOption {
      type = lib.types.str;
      description = "Email for certificate expiry notices.";
    };
    acceptAcmeTerms = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Register with the ACME provider and accept its terms during setup.";
    };
    kithmootUrl = lib.mkOption {
      type = lib.types.str;
      default = "https://kithmoot.app/j/";
      description = "HTTPS KithMoot pairing application URL.";
    };
    allowedOrigins = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "https://kithmoot.app" "https://kithmoot.forgesworn.dev" ];
      description = "HTTPS origins allowed to call the signed Spry API.";
    };
    spryImage = lib.mkOption {
      type = lib.types.str;
      default = "ghcr.io/forgesworn/spry-standalone@sha256:b5f004b0b796c8fc9937cc71e46f5279b3cf2178d25db1be844d6fb6fda864a2";
      description = "Spry image name.";
    };
    wokImage = lib.mkOption {
      type = lib.types.str;
      default = "ghcr.io/forgesworn/wok@sha256:ba6ac8f8999f963c6d9b85e300e66da129e3a9903f1bbb8c932dbbfb5574eb48";
      description = "Wok image name.";
    };
    wildbloomImage = lib.mkOption {
      type = lib.types.str;
      default = "ghcr.io/forgesworn/wildbloom-node@sha256:d4c85f69e37d4508dfbf13cc905cd7310a84e720aa707f6d06aec152851d701b";
      description = "Reviewed Wildbloom image.";
    };
    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/forgesworn-node";
      description = "Writable bundle, configuration, backup and certificate directory.";
    };
    maxAllocations = lib.mkOption { type = lib.types.int; default = 32; };
    maxAllocationsPerUser = lib.mkOption { type = lib.types.int; default = 8; };
    maxTcpConnections = lib.mkOption { type = lib.types.int; default = 64; };
    bytesPerSecond = lib.mkOption { type = lib.types.int; default = 1000000; };
    aggregateBytesPerSecond = lib.mkOption { type = lib.types.int; default = 8000000; };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = cfg.ownerKeys != [ ]; message = "At least one owner Nostr public key is required."; }
      { assertion = cfg.controlRelays != [ ]; message = "Choose at least one WSS control relay."; }
      { assertion = cfg.acmeEmail != ""; message = "An ACME contact email is required."; }
      { assertion = builtins.match ".*[[:space:]].*" cfg.publicHost == null; message = "publicHost must be a DNS hostname."; }
    ];

    environment.systemPackages = [ pkgs.docker-compose pkgs.openssl pkgs.python3 ];
    virtualisation.docker = {
      enable = true;
      package = pkgs.docker_29;
    };

    networking.firewall = {
      allowedTCPPorts = [ 80 443 3478 5349 ];
      allowedUDPPorts = [ 3478 5349 ] ++ lib.range 49160 49191;
    };

    systemd.services.forgesworn-node = {
      description = "Standalone ForgeSworn Spry, Wok and Wildbloom services";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" "docker.service" ];
      path = [ pkgs.docker-compose pkgs.openssl pkgs.python3 pkgs.coreutils pkgs.gnutar ];
      preStart = ''
        mkdir -p ${cfg.stateDir}/bundle
        cp -r ${bundle}/. ${cfg.stateDir}/bundle/
        chmod -R u+w ${cfg.stateDir}/bundle
        cp ${environmentFile} ${cfg.stateDir}/bundle/.env
        chmod 600 ${cfg.stateDir}/bundle/.env
        cd ${cfg.stateDir}/bundle
        ./bin/forgesworn-node init
      '';
      script = ''
        cd ${cfg.stateDir}/bundle
        ./bin/forgesworn-node up
        ${lib.optionalString cfg.acceptAcmeTerms "./bin/forgesworn-node certify"}
      '';
      postStop = ''
        cd ${cfg.stateDir}/bundle
        ./bin/forgesworn-node down
      '';
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        TimeoutStartSec = "30min";
        TimeoutStopSec = "2min";
        WorkingDirectory = cfg.stateDir;
      };
    };
  };
}
