import importlib.util
import base64
import json
from pathlib import Path
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

spec = importlib.util.spec_from_file_location("archive", Path(__file__).with_name("archive-legacy-homelab-state.py"))
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class DecodeSafety(unittest.TestCase):
    def setUp(self):
        self.key = AESGCM.generate_key(bit_length=256)
        self.plaintext = json.dumps({"version": 4, "serial": 3, "lineage": "fixture", "resources": []}).encode()
        nonce = b"fixture12345"
        encrypted = nonce + AESGCM(self.key).encrypt(nonce, self.plaintext, None)
        self.envelope = {"serial": 3, "lineage": "fixture", "encrypted_data": base64.b64encode(encrypted).decode()}

    def test_exact_roundtrip(self):
        self.assertEqual(archive.decode_state(self.envelope, self.key), self.plaintext)

    def test_wrong_key_fails_authentication(self):
        with self.assertRaises(InvalidTag):
            archive.decode_state(self.envelope, AESGCM.generate_key(bit_length=256))

    def test_wrong_state_identity_is_rejected(self):
        self.envelope["lineage"] = "different"
        with self.assertRaises(AssertionError):
            archive.decode_state(self.envelope, self.key)


if __name__ == "__main__":
    unittest.main()
