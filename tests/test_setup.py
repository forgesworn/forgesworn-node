import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("standalone_setup", ROOT / "bin" / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class ValidationTest(unittest.TestCase):
    def test_owner_accepts_hex_and_rejects_unknown_keys(self):
        key = "ab" * 32
        self.assertEqual(setup.owner_keys(key), key)
        with self.assertRaises(ValueError):
            setup.owner_keys("not-a-key")
        with self.assertRaises(ValueError):
            setup.owner_keys(f"{key},{key}")

    def test_owner_accepts_an_npub_and_checks_its_checksum(self):
        self.assertEqual(setup.owner_keys("npub1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs8j9gdm"), "01" * 32)
        with self.assertRaises(ValueError):
            setup.owner_keys("npub1qyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqs8j9gdx")

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


if __name__ == "__main__":
    unittest.main()
