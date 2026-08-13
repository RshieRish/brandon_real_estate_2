"""add exact contact timeline query support"""

from __future__ import annotations

import unicodedata

import sqlalchemy as sa

from alembic import op

revision = "6c0e2f4a5b7d"
down_revision = "5b9d1e2f3a4c"
branch_labels = None
depends_on = None

_PLACEHOLDERS = frozenset({"", "--", "—", "n/a", "none", "null"})
_BACKFILL_BATCH_SIZE = 1_000


def _canonical_email(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("normalized-email backfill encountered invalid data")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if (
        normalized in _PLACEHOLDERS
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        return None
    local, domain = normalized.split("@", 1)
    if not local or not domain or domain.startswith(".") or domain.endswith("."):
        return None
    return normalized


def _backfill(table_name: str) -> None:
    connection = op.get_bind()
    update_statement = sa.text(
        f"UPDATE {table_name} SET normalized_email = :normalized WHERE id = :id"
    )
    last_id = 0
    while True:
        rows = connection.execute(
            sa.text(
                f"SELECT id, email FROM {table_name} "
                "WHERE id > :last_id ORDER BY id LIMIT :batch_size"
            ),
            {"last_id": last_id, "batch_size": _BACKFILL_BATCH_SIZE},
        ).all()
        if not rows:
            return
        connection.execute(
            update_statement,
            [
                {"id": row.id, "normalized": _canonical_email(row.email)}
                for row in rows
            ],
        )
        last_id = rows[-1].id
        if len(rows) < _BACKFILL_BATCH_SIZE:
            return


def _verify_backfill(table_name: str) -> None:
    connection = op.get_bind()
    last_id = 0
    while True:
        rows = connection.execute(
            sa.text(
                f"SELECT id, email, normalized_email FROM {table_name} "
                "WHERE id > :last_id ORDER BY id LIMIT :batch_size"
            ),
            {"last_id": last_id, "batch_size": _BACKFILL_BATCH_SIZE},
        ).all()
        if not rows:
            return
        if any(
            row.normalized_email != _canonical_email(row.email) for row in rows
        ):
            raise RuntimeError("canonical-email backfill verification failed")
        last_id = rows[-1].id
        if len(rows) < _BACKFILL_BATCH_SIZE:
            return


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "contact timeline query support requires an online "
            "canonical-email backfill"
        )

    with op.batch_alter_table("crm_contacts") as batch_op:
        batch_op.add_column(
            sa.Column("normalized_email", sa.String(length=255), nullable=True)
        )
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(
            sa.Column("normalized_email", sa.String(length=255), nullable=True)
        )

    _backfill("crm_contacts")
    _backfill("bookings")
    _verify_backfill("crm_contacts")
    _verify_backfill("bookings")

    op.create_index(
        "ix_crm_contacts_normalized_email_id",
        "crm_contacts",
        ["normalized_email", "id"],
    )
    op.create_index(
        "ix_crm_activities_timeline_order",
        "crm_activities",
        ["contact_id", "created_at", "id"],
    )
    op.create_index(
        "ix_bookings_timeline_lead_order",
        "bookings",
        ["lead_id", "scheduled_at", "id"],
    )
    op.create_index(
        "ix_bookings_timeline_email_order",
        "bookings",
        ["normalized_email", "lead_id", "scheduled_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_bookings_timeline_email_order", table_name="bookings")
    op.drop_index("ix_bookings_timeline_lead_order", table_name="bookings")
    op.drop_index("ix_crm_activities_timeline_order", table_name="crm_activities")
    op.drop_index("ix_crm_contacts_normalized_email_id", table_name="crm_contacts")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("normalized_email")
    with op.batch_alter_table("crm_contacts") as batch_op:
        batch_op.drop_column("normalized_email")
