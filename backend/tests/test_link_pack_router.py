import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from routers import link_pack as lp_router


class _FakeDB:
    def __init__(self):
        self.added: list = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.delete = AsyncMock()
        self._packs: list = []
        self._items: list = []

    def add(self, item):
        self.added.append(item)
        if item.__class__.__name__ == "LinkPack":
            self._packs.append(item)
        else:
            self._items.append(item)

    async def execute(self, stmt):  # extremely loose stub — overridden per test
        raise NotImplementedError


class PublicGetTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_public_returns_404_when_not_published(self):
        db = _FakeDB()

        class _Result:
            def scalar_one_or_none(self):
                return None

        db.execute = AsyncMock(return_value=_Result())
        with self.assertRaises(HTTPException) as ctx:
            await lp_router.get_public(db=db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_public_returns_snapshot(self):
        db = _FakeDB()
        from models.link_pack import LinkPack

        class _Result:
            def __init__(self, pack):
                self.pack = pack
            def scalar_one_or_none(self):
                return self.pack

        pack = LinkPack(id=1, published_snapshot={"profile": {"name": "B"}}, profile_name="B")
        db.execute = AsyncMock(return_value=_Result(pack))
        result = await lp_router.get_public(db=db)
        self.assertEqual(result["profile"]["name"], "B")


class ItemValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_with_parent_rejected(self):
        from schemas.link_pack import ItemIn
        from routers.link_pack import _validate_item_invariants
        with self.assertRaises(Exception):
            _validate_item_invariants(ItemIn(kind="group", title="x", parent_id=5))

    async def test_classic_with_parent_to_non_group_rejected(self):
        from routers.link_pack import _validate_item_invariants
        from schemas.link_pack import ItemIn
        from models.link_pack import LinkPackItem
        fake_parent = LinkPackItem(id=5, kind="classic", title="not a group", position=0, animation="none", is_active=True)
        with self.assertRaises(Exception):
            _validate_item_invariants(ItemIn(kind="classic", title="x", parent_id=5), parent=fake_parent)


class ReorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_reorder_assigns_sequential_positions(self):
        from routers.link_pack import _apply_reorder
        from models.link_pack import LinkPackItem

        items = [
            LinkPackItem(id=1, parent_id=None, position=0, kind="classic", title="a", animation="none", is_active=True),
            LinkPackItem(id=2, parent_id=None, position=1, kind="classic", title="b", animation="none", is_active=True),
            LinkPackItem(id=3, parent_id=None, position=2, kind="classic", title="c", animation="none", is_active=True),
        ]
        _apply_reorder(items, ordered_ids=[3, 1, 2])
        positions = {it.id: it.position for it in items}
        self.assertEqual(positions, {3: 0, 1: 1, 2: 2})
