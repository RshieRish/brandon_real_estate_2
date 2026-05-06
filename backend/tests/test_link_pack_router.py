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
