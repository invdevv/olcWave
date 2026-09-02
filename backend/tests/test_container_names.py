import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from olcrtc.sdk import OlcRTC


class ParseNameTest(unittest.TestCase):
    """OlcRTC.parse_name decodes "olcwave-<config_tag>-<owner>"."""

    def test_owner_may_contain_hyphens(self):
        # a Remnawave shortUuid is not hyphen-free
        self.assertEqual(
            OlcRTC.parse_name("olcwave-wbvp8-X6kHaphfAzZJ-E-n"),
            ("wbvp8", "X6kHaphfAzZJ-E-n"),
        )

    def test_plain_owner(self):
        self.assertEqual(
            OlcRTC.parse_name("olcwave-wbvp8-plainuuid"),
            ("wbvp8", "plainuuid"),
        )

    def test_service_container_is_not_a_user_container(self):
        self.assertIsNone(OlcRTC.parse_name("olcwave-xraycore"))

    def test_foreign_container(self):
        self.assertIsNone(OlcRTC.parse_name("some-other-container"))

    def test_prefix_only(self):
        self.assertIsNone(OlcRTC.parse_name("olcwave"))


if __name__ == "__main__":
    unittest.main()
