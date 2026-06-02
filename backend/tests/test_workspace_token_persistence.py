import unittest
from unittest.mock import AsyncMock

from config import settings
from models.setting import Setting
from routers.workspace import (
    WORKSPACE_REFRESH_TOKEN_KEY,
    load_workspace_refresh_token_from_db,
    persist_workspace_refresh_token_to_db,
)


class _FakeResult:
    def __init__(self, setting):
        self._setting = setting

    def scalar_one_or_none(self):
        return self._setting


class _FakeDB:
    def __init__(self, existing_setting=None):
        self.added = []
        self.execute = AsyncMock(return_value=_FakeResult(existing_setting))

    def add(self, item):
        self.added.append(item)


class WorkspaceTokenPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_workspace_refresh_token_from_db_sets_runtime_value(self):
        original = settings.GOOGLE_WORKSPACE_REFRESH_TOKEN
        db = _FakeDB(existing_setting=Setting(key=WORKSPACE_REFRESH_TOKEN_KEY, value="db-workspace-token"))

        try:
            settings.GOOGLE_WORKSPACE_REFRESH_TOKEN = ""
            token = await load_workspace_refresh_token_from_db(db)
            self.assertEqual(settings.GOOGLE_WORKSPACE_REFRESH_TOKEN, "db-workspace-token")
        finally:
            settings.GOOGLE_WORKSPACE_REFRESH_TOKEN = original

        self.assertEqual(token, "db-workspace-token")

    async def test_persist_workspace_refresh_token_to_db_creates_setting_when_missing(self):
        db = _FakeDB(existing_setting=None)

        await persist_workspace_refresh_token_to_db(db, "fresh-token")

        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].key, WORKSPACE_REFRESH_TOKEN_KEY)
        self.assertEqual(db.added[0].value, "fresh-token")

    async def test_persist_workspace_refresh_token_to_db_updates_existing_setting(self):
        existing = Setting(key=WORKSPACE_REFRESH_TOKEN_KEY, value="old-token")
        db = _FakeDB(existing_setting=existing)

        await persist_workspace_refresh_token_to_db(db, "fresh-token")

        self.assertEqual(existing.value, "fresh-token")
        self.assertEqual(db.added, [])


if __name__ == "__main__":
    unittest.main()
