import importlib.util
from pathlib import Path
import re
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("standalone_setup", ROOT / "bin" / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def bech32_npub(key):
    return setup.bech32_encode("npub", bytes.fromhex(key))


class BundleTest(unittest.TestCase):
    def test_every_service_caps_its_container_log(self):
        text = (ROOT / "compose.yaml").read_text()
        self.assertIn(
            'x-logging: &logging\n  driver: local\n  options:\n'
            '    max-size: "1m"\n    max-file: "1"\n    compress: "false"\n', text)
        services = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
        blocks = re.split(r"(?m)^  (?=[a-z][a-z0-9-]*:$)", services)[1:]
        self.assertGreaterEqual(len(blocks), 5)
        for block in blocks:
            self.assertIn("\n    logging: *logging\n", block, block.splitlines()[0])


class ValidationTest(unittest.TestCase):
    def test_owner_accepts_hex_and_rejects_unknown_keys(self):
        key = "ab" * 32
        self.assertEqual(setup.owner_keys(key), key)
        with self.assertRaises(ValueError):
            setup.owner_keys("not-a-key")
        with self.assertRaises(ValueError):
            setup.owner_keys(f"{key},{key}")

    def test_owner_accepts_an_npub_and_checks_its_checksum(self):
        self.assertEqual(bech32_npub("01" * 32), "npub1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs8j9gdm")
        self.assertEqual(setup.owner_keys("npub1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs8j9gdm"), "01" * 32)
        with self.assertRaises(ValueError):
            setup.owner_keys("npub1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs8j9gdx")

    def test_wok_config_uses_the_same_host_and_owner(self):
        key = "01" * 32
        text = subprocess.check_output([sys.executable, str(ROOT / "bin" / "wok-config.py"), "relay.example.org", key], text=True)
        self.assertIn('url = "wss://relay.example.org/events"', text)
        self.assertIn(bech32_npub(key), text)
        self.assertIn('data_dir = "/data"', text)
        self.assertNotIn(key, text)

    def test_control_relays_are_bounded_and_wss_only(self):
        self.assertEqual(setup.control_relays("wss://one.example, wss://two.example/events"), '["wss://one.example","wss://two.example/events"]')
        for value in ("ws://one.example", "https://one.example", "", "wss://one.example,wss://one.example"):
            with self.assertRaises(ValueError):
                setup.control_relays(value)

    def test_host_and_address_validation(self):
        self.assertEqual(setup.hostname("Relay.Example.org."), "relay.example.org")
        self.assertEqual(setup.public_ip("127.0.0.1", True), "127.0.0.1")
        with self.assertRaises(ValueError):
            setup.hostname("https://relay.example.org")
        with self.assertRaises(ValueError):
            setup.public_ip("192.168.1.10", False)

    def test_unsupported_host_is_refused_before_setup(self):
        with mock.patch.object(setup.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(RuntimeError, "Linux"):
                setup.preflight()

    def test_environment_update_stays_private_and_preserves_advanced_values(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = setup.ENV
            setup.ENV = Path(directory) / ".env"
            try:
                setup.write_env({"PUBLIC_HOST": "relay.example.org", "OWNER_KEYS": "ab" * 32, "MAX_ALLOCATIONS": "12"})
                self.assertEqual(setup.ENV.stat().st_mode & 0o777, 0o600)
                values = setup.read_env()
                self.assertEqual(values["PUBLIC_HOST"], "relay.example.org")
                self.assertEqual(values["MAX_ALLOCATIONS"], "12")
                self.assertNotIn("TURN_SECRET", values)
            finally:
                setup.ENV = previous

    def test_container_defaults_use_the_same_immutable_public_images(self):
        compose = (ROOT / "compose.yaml").read_text()
        environment = (ROOT / ".env.example").read_text()
        nix = (ROOT / "nix" / "forgesworn-node.nix").read_text()
        images = dict(re.findall(r"\$\{(SPRY_IMAGE|WOK_IMAGE|WILDBLOOM_IMAGE):-([^}]+)\}", compose))
        self.assertEqual(set(images), {"SPRY_IMAGE", "WOK_IMAGE", "WILDBLOOM_IMAGE"})
        for name, reference in images.items():
            self.assertRegex(reference, r"^ghcr\.io/forgesworn/(?:spry-standalone|wok|wildbloom-node)@sha256:[0-9a-f]{64}$")
            self.assertIn(f"{name}={reference}", environment)
            self.assertIn(f'default = "{reference}";', nix)
        self.assertNotIn("build:", compose)
        for obsolete in ("SPRY_SOURCE", "WOK_SOURCE", "sprySource", "wokSource"):
            self.assertNotIn(obsolete, compose + environment + nix)

    def test_nix_bundle_never_copies_the_whole_operator_checkout(self):
        text = (ROOT / "nix" / "forgesworn-node.nix").read_text()
        self.assertNotIn("cp -r ${../.}/.", text)
        self.assertNotIn("environment.etc", text)
        for name in (".env.example", ".gitignore", "LICENSE", "README.md", "compose.yaml"):
            self.assertIn(f"cp ${{../{name}}} $out/{name}", text)
        for name in ("compose.yaml", "bin", "certbot", "gateway", "nix", "tests"):
            self.assertTrue((ROOT / name).exists(), name)

    def test_nix_selects_a_maintained_docker_package(self):
        text = (ROOT / "nix" / "forgesworn-node.nix").read_text()
        self.assertIn("package = pkgs.docker_29;", text)

    def test_shared_proxy_profile_uses_non_conflicting_defaults(self):
        values = {}
        setup.configure_proxy(values, True)
        self.assertEqual(values["SHARED_PROXY"], "true")
        self.assertEqual(values["NGINX_CONFIG"], "nginx.shared.conf")
        self.assertEqual(values["HTTP_TEMPLATE"], "http.shared.conf.template")
        self.assertEqual(values["SPRY_TURN_PORT"], "3479")
        self.assertEqual(values["SPRY_TLS_PORT"], "5350")
        self.assertEqual(values["SPRY_RELAY_PORTS"], "49500:49531")
        self.assertEqual(values["SPRY_TLS_ADVERTISE_DIRECT"], "false")
        self.assertEqual(values["WILDBLOOM_BIND"], "127.0.0.1:3743")
        values["SPRY_TURN_PORT"] = "3480"
        setup.configure_proxy(values, True)
        self.assertEqual(values["SPRY_TURN_PORT"], "3480")
        setup.configure_proxy(values, False)
        self.assertEqual(values["SHARED_PROXY"], "false")
        self.assertEqual(values["NGINX_CONFIG"], "nginx.conf")
        self.assertEqual(values["SPRY_TLS_ADVERTISE_DIRECT"], "true")

    def test_shared_proxy_has_only_loopback_http_and_private_admin_listeners(self):
        main = (ROOT / "gateway" / "nginx.shared.conf").read_text()
        http = (ROOT / "gateway" / "http.shared.conf.template").read_text()
        self.assertNotIn("stream {", main)
        self.assertIn("listen 127.0.0.1:9080;", http)
        self.assertIn("listen ${ADMIN_BIND}:8443 ssl;", http)
        for occupied in ("listen 80;", "listen 443;", "listen 9443", "listen 127.0.0.1:9443"):
            self.assertNotIn(occupied, http)
        self.assertIn("include /etc/nginx/conf.d/public_routes.conf;", http)
        proxy = (ROOT / "gateway" / "proxy_params").read_text()
        self.assertIn("X-Forwarded-For $forgesworn_forwarded_for", proxy)
        for name in ("nginx.conf", "nginx.shared.conf"):
            config = (ROOT / "gateway" / name).read_text()
            self.assertIn("default $proxy_add_x_forwarded_for;", config)
            self.assertIn("127.0.0.1 $http_x_forwarded_for;", config)

    def test_dedicated_and_shared_gateways_use_the_same_public_allowlist(self):
        dedicated = (ROOT / "gateway" / "http.conf.template").read_text()
        shared = (ROOT / "gateway" / "http.shared.conf.template").read_text()
        routes = (ROOT / "gateway" / "public_routes.conf.template").read_text()
        for template in (dedicated, shared):
            self.assertIn("include /etc/nginx/conf.d/public_routes.conf;", template)
            self.assertNotIn("location = /v1/credentials", template)
        for path in ("/events", "/upload", "/mirror", "/v1/pairings/claim", "/v1/credentials", "/v1/peers"):
            self.assertIn(f"location = {path}", routes)
        self.assertIn('return 404;', routes)
        self.assertNotIn("/v1/public/credentials", routes)
        self.assertNotIn("/v1/owner/stats", routes)

    def test_shared_caddy_keeps_turn_tls_on_public_443(self):
        site = (ROOT / "caddy" / "forgesworn-node.Caddyfile.template").read_text()
        route = (ROOT / "caddy" / "layer4-turn.route.template").read_text()
        sync = (ROOT / "caddy" / "sync-certs.sh").read_text()
        self.assertIn("reverse_proxy 127.0.0.1:9080", site)
        self.assertIn("turn.${PUBLIC_HOST}", site)
        self.assertIn("disable_tlsalpn_challenge", site)
        self.assertIn("tls sni turn.${PUBLIC_HOST}", route)
        self.assertIn("proxy ${PUBLIC_IP}:${SPRY_TLS_PORT}", route)
        self.assertIn('name "$PUBLIC_HOST.crt"', sync)
        self.assertIn('name "turn.$PUBLIC_HOST.crt"', sync)
        self.assertIn("restart spry gateway", sync)

    def test_loopback_owner_ui_can_load_its_module_script(self):
        for path in (".env.example", "compose.yaml", "nix/forgesworn-node.nix"):
            text = (ROOT / path).read_text()
            self.assertIn("https://localhost:8443", text)

    def test_unprivileged_containers_can_read_secrets_inside_private_state(self):
        initialise = (ROOT / "bin" / "forgesworn-node").read_text()
        certbot = (ROOT / "certbot" / "deploy-hook.sh").read_text()
        caddy = (ROOT / "caddy" / "sync-certs.sh").read_text()
        self.assertIn("chmod 644 state/spry-turn-secret", initialise)
        self.assertIn("chmod 644 state/tls/privkey.pem state/tls/turn-privkey.pem", initialise)
        for script in (certbot, caddy):
            self.assertNotRegex(script, r"(?:privkey\.pem|spry-turn-secret).*0600")
            self.assertNotRegex(script, r"0600.*(?:privkey\.pem|spry-turn-secret)")

    def test_certificate_renewal_updates_public_and_turn_pairs(self):
        hook = (ROOT / "certbot" / "deploy-hook.sh").read_text()
        compose = (ROOT / "compose.yaml").read_text()
        for name in ("fullchain.pem", "privkey.pem", "turn-fullchain.pem", "turn-privkey.pem"):
            self.assertIn(name, hook)
            self.assertIn(name, compose)


if __name__ == "__main__":
    unittest.main()
