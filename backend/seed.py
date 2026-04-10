import asyncio

from passlib.context import CryptContext
from sqlalchemy import select

import models.admin_user
import models.analytics_event
import models.booking
import models.content_block
import models.funnel
import models.lead
import models.setting
from database import AsyncSessionLocal
from models.admin_user import AdminUser
from models.content_block import ContentBlock

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
DEFAULT_ADMIN_EMAIL = "brandon@soldwithsweeney.com"
DEFAULT_ADMIN_PASSWORD = "changeme123!"

DEFAULT_CONTENT = [
    {
        "block_id": "home_hero_headline",
        "content": "NOT your AVERAGE, award winning, philanthropic REALTOR\u00ae OF THE YEAR \u201925",
        "page": "home",
    },
    {
        "block_id": "home_hero_subtext",
        "content": "Serving MA & NH | Keller Williams Realty Success",
        "page": "home",
    },
    {"block_id": "home_cta_buy", "content": "Find Your Home", "page": "home"},
    {"block_id": "home_cta_sell", "content": "Sell With Confidence", "page": "home"},
    {"block_id": "home_cta_invest", "content": "Analyze a Deal", "page": "home"},
    {
        "block_id": "market_update",
        "content": (
            "Current market conditions in the Merrimack Valley remain competitive. "
            "Inventory is limited and well-priced homes move quickly. "
            "Contact Brandon for a personalized market analysis."
        ),
        "page": "buyer",
    },
    {
        "block_id": "trust_volume_done",
        "content": "100",
        "page": "home",
    },
    {
        "block_id": "trust_families_served",
        "content": "250",
        "page": "home",
    },
    {
        "block_id": "trust_years_in_business",
        "content": "10",
        "page": "home",
    },
    {
        "block_id": "giving_back_donated",
        "content": "300000",
        "page": "home",
    },
]


async def seed():
    async with AsyncSessionLocal() as db:
        # Admin user
        await ensure_admin_user(db)

        # Content blocks
        for item in DEFAULT_CONTENT:
            result = await db.execute(
                select(ContentBlock).where(ContentBlock.block_id == item["block_id"])
            )
            if not result.scalar_one_or_none():
                db.add(ContentBlock(**item, content_type="text"))

        await db.commit()

    print("Seed complete. Admin account created: brandon@soldwithsweeney.com — change the password immediately.")


async def ensure_admin_user(
    db,
    email: str = DEFAULT_ADMIN_EMAIL,
    password: str = DEFAULT_ADMIN_PASSWORD,
):
    result = await db.execute(select(AdminUser).where(AdminUser.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = AdminUser(
            email=email,
            hashed_password=pwd_context.hash(password),
        )
        db.add(user)
        return user

    if not pwd_context.verify(password, user.hashed_password):
        user.hashed_password = pwd_context.hash(password)

    return user


if __name__ == "__main__":
    asyncio.run(seed())
