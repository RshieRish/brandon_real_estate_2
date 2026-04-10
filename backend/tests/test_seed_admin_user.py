import unittest
from unittest.mock import AsyncMock

from passlib.context import CryptContext

from models.admin_user import AdminUser
from seed import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, ensure_admin_user


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class _FakeResult:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class _FakeDB:
    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.execute = AsyncMock(return_value=_FakeResult(existing_user))

    def add(self, item):
        self.added.append(item)


class SeedAdminUserTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_admin_user_creates_missing_admin(self):
        db = _FakeDB(existing_user=None)

        user = await ensure_admin_user(db)

        self.assertEqual(user.email, DEFAULT_ADMIN_EMAIL)
        self.assertEqual(len(db.added), 1)
        self.assertTrue(pwd_context.verify(DEFAULT_ADMIN_PASSWORD, user.hashed_password))

    async def test_ensure_admin_user_updates_existing_hash_when_password_mismatch(self):
        existing_user = AdminUser(
            email=DEFAULT_ADMIN_EMAIL,
            hashed_password=pwd_context.hash("wrong-password"),
        )
        db = _FakeDB(existing_user=existing_user)

        user = await ensure_admin_user(db)

        self.assertIs(user, existing_user)
        self.assertTrue(pwd_context.verify(DEFAULT_ADMIN_PASSWORD, user.hashed_password))


if __name__ == "__main__":
    unittest.main()
