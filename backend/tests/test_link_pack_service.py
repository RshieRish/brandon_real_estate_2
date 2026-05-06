import unittest
from datetime import datetime, timezone

from models.link_pack import LinkPack, LinkPackItem
from services.link_pack_service import build_snapshot, mint_gate_token, verify_gate_token


def _make_pack() -> tuple[LinkPack, list[LinkPackItem]]:
    pack = LinkPack(
        id=1,
        profile_name="Brandon",
        profile_bio="bio",
        is_verified=True,
        social_phone="+1",
        theme={"background": {"type": "solid", "color": "#000000"}},
        profile_photo_mime="image/png",
        background_image_mime=None,
    )
    parent = LinkPackItem(id=10, kind="group", title="Available Homes", position=0, is_active=True, animation="none")
    parent.parent_id = None
    child = LinkPackItem(id=11, kind="thumbnail", title="123 Main St", url="https://x", position=0, is_active=True, animation="none", thumbnail_mime="image/jpeg")
    child.parent_id = 10
    classic = LinkPackItem(id=12, kind="classic", title="Home Worth?", url="https://y", position=1, is_active=True, animation="pulse")
    classic.parent_id = None
    inactive = LinkPackItem(id=13, kind="classic", title="hidden", url="https://z", position=2, is_active=False, animation="none")
    inactive.parent_id = None
    return pack, [parent, child, classic, inactive]


class BuildSnapshotTests(unittest.TestCase):
    def test_snapshot_includes_active_items_only_and_nests_children(self):
        pack, items = _make_pack()
        snap = build_snapshot(pack, items)
        self.assertEqual(snap["profile"]["name"], "Brandon")
        self.assertTrue(snap["profile"]["is_verified"])
        self.assertEqual(snap["profile"]["photo_url"], "/api/v1/link-pack/images/profile")
        top_titles = [it["title"] for it in snap["items"]]
        self.assertEqual(top_titles, ["Available Homes", "Home Worth?"])
        group = snap["items"][0]
        self.assertEqual(len(group["children"]), 1)
        self.assertEqual(group["children"][0]["thumbnail_url"], "/api/v1/link-pack/images/items/11/thumbnail")

    def test_snapshot_omits_image_url_when_no_data(self):
        pack, _ = _make_pack()
        pack.profile_photo_mime = None
        snap = build_snapshot(pack, [])
        self.assertIsNone(snap["profile"]["photo_url"])


class GateTokenTests(unittest.TestCase):
    def test_mint_and_verify_round_trips(self):
        token = mint_gate_token(item_id=42)
        self.assertEqual(verify_gate_token(token), 42)

    def test_verify_rejects_wrong_signature(self):
        with self.assertRaises(ValueError):
            verify_gate_token("not-a-jwt")
