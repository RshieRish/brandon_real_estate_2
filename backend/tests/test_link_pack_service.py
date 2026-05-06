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


from unittest.mock import AsyncMock


class _FakeDB:
    """Async DB stub matching the pattern from test_evaluator_router."""

    def __init__(self):
        self.added: list = []
        self.flush = AsyncMock()
        self.refresh = AsyncMock()
        self._pack_in_db = None  # set by tests

    def add(self, item):
        self.added.append(item)
        # Auto-track: if test pre-set None and add() is called with a LinkPack, treat as inserted
        if item.__class__.__name__ == "LinkPack":
            self._pack_in_db = item

    async def execute(self, _stmt):
        return _Result(self._pack_in_db)


class _Result:
    def __init__(self, pack):
        self._pack = pack

    def scalar_one_or_none(self):
        return self._pack


class GetOrCreatePackTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_existing_pack_when_present(self):
        from services.link_pack_service import get_or_create_pack
        db = _FakeDB()
        existing = LinkPack(id=1, profile_name="Existing", theme={"k": "v"})
        db._pack_in_db = existing

        result = await get_or_create_pack(db)
        self.assertIs(result, existing)
        self.assertEqual(db.added, [])  # did NOT create a new row
        db.flush.assert_not_awaited()

    async def test_creates_pack_with_default_theme_when_missing(self):
        from services.link_pack_service import get_or_create_pack
        from schemas.link_pack import DEFAULT_THEME
        db = _FakeDB()
        db._pack_in_db = None  # no existing row

        result = await get_or_create_pack(db)
        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], LinkPack)
        self.assertEqual(result.id, 1)
        self.assertEqual(result.theme, DEFAULT_THEME)
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(result)


class MarkDirtyTests(unittest.IsolatedAsyncioTestCase):
    async def test_sets_has_unpublished_changes_on_existing(self):
        from services.link_pack_service import mark_dirty
        db = _FakeDB()
        existing = LinkPack(id=1, has_unpublished_changes=False)
        db._pack_in_db = existing

        await mark_dirty(db)
        self.assertTrue(existing.has_unpublished_changes)

    async def test_creates_pack_then_marks_dirty_when_missing(self):
        from services.link_pack_service import mark_dirty
        db = _FakeDB()
        db._pack_in_db = None

        await mark_dirty(db)
        self.assertEqual(len(db.added), 1)
        created = db.added[0]
        self.assertTrue(created.has_unpublished_changes)
