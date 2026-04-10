"""add_location_to_bookings

Revision ID: 0d8d9bce6f44
Revises: 9c1fb48ea689
Create Date: 2026-04-10 14:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0d8d9bce6f44"
down_revision: Union[str, None] = "9c1fb48ea689"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("location", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "location")
