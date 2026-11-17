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


if __name__ == "__main__":
    unittest.main()
