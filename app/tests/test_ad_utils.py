"""ad_utils 純函式單元測試 (stdlib unittest，可離線執行)。

    cd app && python -m unittest discover -s tests
"""
import base64
import struct
import unittest

from argus_api.ad_utils import derive_base_dn, parse_ntlm_username


class DeriveBaseDnTest(unittest.TestCase):
    def test_typical_domain(self):
        self.assertEqual(derive_base_dn("kh.asegroup.com"),
                         "DC=kh,DC=asegroup,DC=com")

    def test_single_label(self):
        self.assertEqual(derive_base_dn("corp"), "DC=corp")

    def test_empty(self):
        self.assertEqual(derive_base_dn(""), "")

    def test_strips_blank_segments(self):
        self.assertEqual(derive_base_dn("a..b"), "DC=a,DC=b")


class ParseNtlmUsernameTest(unittest.TestCase):
    @staticmethod
    def _make_type3(username: str) -> str:
        un = username.encode("utf-16-le")
        offset = 64
        buf = bytearray(offset + len(un))
        buf[0:8] = b"NTLMSSP\x00"
        struct.pack_into("<I", buf, 8, 3)            # Type-3
        struct.pack_into("<H", buf, 36, len(un))     # User name length
        struct.pack_into("<I", buf, 40, offset)      # User name offset
        buf[offset:offset + len(un)] = un
        return "NTLM " + base64.b64encode(bytes(buf)).decode()

    def test_roundtrip(self):
        self.assertEqual(parse_ntlm_username(self._make_type3("K11879")), "K11879")

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_ntlm_username("NTLM not-base64!!"), "")

    def test_non_type3_returns_empty(self):
        self.assertEqual(parse_ntlm_username("NTLM " + base64.b64encode(b"short").decode()), "")


if __name__ == "__main__":
    unittest.main()
