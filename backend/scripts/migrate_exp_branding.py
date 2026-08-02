"""Safely migrate active database content to eXp Realty branding.

The command is a dry run unless ``--apply`` is passed. Apply mode uses one
transaction, a PostgreSQL advisory lock, row locks, a private JSON backup, and
a post-update remnant check before commit.

Examples (run from ``backend/`` with the production ``DATABASE_URL`` set):

    python -m scripts.migrate_exp_branding --use-packaged-background
    python -m scripts.migrate_exp_branding --apply --use-packaged-background

The backup directory defaults to ``~/.sws-backups/exp-branding`` and can be
overridden with ``SWS_BRANDING_BACKUP_DIR`` or ``--backup-dir``. A backup path
inside this repository is rejected.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
PACKAGED_BACKGROUND = BACKEND_ROOT / "assets" / "link-pack-black-gold-clean.png"
ADVISORY_LOCK_ID = 842913571
EXPECTED_FUNNEL_COUNT = 16

# These are the only database text/JSON fields this migration may inspect or
# update. Keep the tuple values explicit so a schema change cannot silently
# broaden the migration.
ALLOWED_TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "blogs": (
        "title",
        "slug",
        "content",
        "excerpt",
        "author_role",
        "author_bio",
    ),
    "funnels": ("title", "slug", "description", "cta_text", "generated_content"),
    "content_blocks": ("content",),
    "link_pack": ("profile_name", "profile_bio", "social_website", "published_snapshot"),
    "link_pack_items": ("title", "url", "gate_modal_headline", "gate_modal_subtext"),
}

ALLOWED_BINARY_FIELDS: dict[str, tuple[str, ...]] = {
    "link_pack": ("background_image_data", "background_image_mime"),
}

ALLOWED_CONTROL_FIELDS: dict[str, tuple[str, ...]] = {
    "link_pack_items": ("is_active",),
}

READ_FIELDS: dict[str, tuple[str, ...]] = {
    "blogs": ("id", *ALLOWED_TEXT_FIELDS["blogs"]),
    "funnels": ("id", *ALLOWED_TEXT_FIELDS["funnels"]),
    "content_blocks": ("id", *ALLOWED_TEXT_FIELDS["content_blocks"]),
    "link_pack": (
        "id",
        *ALLOWED_TEXT_FIELDS["link_pack"],
        "background_image_data",
        "background_image_mime",
    ),
    "link_pack_items": (
        "id",
        *ALLOWED_TEXT_FIELDS["link_pack_items"],
        "is_active",
    ),
}

UPDATED_AT_TABLES = frozenset(READ_FIELDS)

SWS_WEBSITE = "https://www.soldwithsweeney.com/"
SWS_BUY_URL = "https://www.soldwithsweeney.com/buy"
SWS_SELL_URL = "https://www.soldwithsweeney.com/sell"
EXP_WEBSITE = "https://www.exprealty.com/"

_OLD_URL = re.compile(
    r"(?<![\w.])(?:https?://)?(?:www\.)?(?:soldwithsweeney\.kw\.com|kw\.com)"
    r"(?:/[^\s<>\"'\)\]}]*)?",
    re.IGNORECASE,
)
_KELLER_WILLIAMS = re.compile(
    r"\bkeller[\s-]+williams(?:[\s-]+realty(?:[\s-]+success)?)?\b",
    re.IGNORECASE,
)
_KW_REALTY = re.compile(r"\bkw[\s-]+realty(?:[\s-]+success)?\b", re.IGNORECASE)
_KW_COMMAND = re.compile(r"\bkw[\s-]+command\b", re.IGNORECASE)
_KWRS = re.compile(r"\bkwrs\b", re.IGNORECASE)
# Preserve the mixed-case SI unit ``kW`` while still handling common written
# brokerage abbreviations in either all-upper or all-lower case.
_BARE_KW_BROKERAGE = re.compile(r"(?<!\d )\b(?:KW|kw)\b")
_UNRESOLVED_KELLER = re.compile(r"\bkeller\b", re.IGNORECASE)
_EXP_CASING = re.compile(r"\bexp\s+realty\b", re.IGNORECASE)

AUDITED_LINK_ITEM_STATES: dict[int, tuple[dict[str, Any], ...]] = {
    19: (
        {
            "title": "WHAT'S MY HOME WORTH? \U0001f4b8",
            "url": "https://soldwithsweeney.kw.com/YourHomeValuation",
            "is_active": True,
        },
        {
            "title": "WHAT'S MY HOME WORTH? \U0001f4b8",
            "url": SWS_SELL_URL,
            "is_active": True,
        },
    ),
    21: (
        {
            "title": "DOWNLOAD MY APP \U0001f3e1",
            "url": "https://kw.com/download/KW4ABYJHJ",
            "is_active": False,
        },
        {
            "title": "DOWNLOAD MY APP \U0001f3e1",
            "url": None,
            "is_active": False,
        },
    ),
}


def _replacement_for_old_url(url: str) -> str:
    """Return a safe destination without inventing brokerage property paths."""
    trailing = ""
    while url and url[-1] in ".,;:":
        trailing = url[-1] + trailing
        url = url[:-1]

    lowered = url.lower()
    if "yourhomevaluation" in lowered:
        destination = SWS_SELL_URL
    elif "/property/" in lowered:
        destination = SWS_BUY_URL
    elif "kw.com/download/" in lowered:
        destination = EXP_WEBSITE
    elif "soldwithsweeney.kw.com" in lowered:
        destination = SWS_WEBSITE
    else:
        destination = EXP_WEBSITE
    return destination + trailing


def replace_brokerage_text(value: str) -> str:
    """Replace old brokerage names/URLs while preserving unrelated ``kw`` text."""
    if not value:
        return value

    updated = _OLD_URL.sub(lambda match: _replacement_for_old_url(match.group(0)), value)
    updated = _KW_COMMAND.sub("legacy CRM", updated)
    updated = _KELLER_WILLIAMS.sub("eXp Realty", updated)
    updated = _KW_REALTY.sub("eXp Realty", updated)
    updated = _KWRS.sub("eXp Realty", updated)
    updated = _BARE_KW_BROKERAGE.sub("eXp Realty", updated)
    updated = _EXP_CASING.sub("eXp Realty", updated)
    updated = re.sub(
        r"\bpowered\s+by\s+eXp\s+Realty\b",
        "brokered by eXp Realty",
        updated,
        flags=re.IGNORECASE,
    )
    return updated


def replace_blog_slug(value: str) -> str:
    """Replace only brokerage slug segments, leaving unrelated words intact."""
    if not value:
        return value
    updated = re.sub(
        r"(?<![a-z0-9])(?:keller-williams-realty-success|keller-williams-realty|"
        r"keller-williams|kw-realty-success|kw-realty|kwrs)(?![a-z0-9])",
        "exp-realty",
        value,
        flags=re.IGNORECASE,
    )
    return updated


def replace_nested_branding(value: Any) -> Any:
    """Recursively transform strings inside JSON-compatible structures."""
    if isinstance(value, str):
        return replace_brokerage_text(value)
    if isinstance(value, list):
        return [replace_nested_branding(item) for item in value]
    if isinstance(value, tuple):
        return tuple(replace_nested_branding(item) for item in value)
    if isinstance(value, dict):
        return {key: replace_nested_branding(item) for key, item in value.items()}
    return value


def _transform_json_text(value: str) -> str:
    """Transform JSON text structurally when valid, with a text fallback."""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return replace_brokerage_text(value)
    return json.dumps(replace_nested_branding(parsed), ensure_ascii=False)


def _copy_database_value(value: Any) -> Any:
    """Deep-copy driver values, normalizing PostgreSQL BYTEA memoryviews."""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, list):
        return [_copy_database_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_database_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _copy_database_value(item) for key, item in value.items()}
    return copy.deepcopy(value)


def transform_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Return an idempotently transformed copy of one allowlisted row."""
    if table not in ALLOWED_TEXT_FIELDS:
        raise ValueError(f"table is not allowlisted: {table}")

    updated = {key: _copy_database_value(value) for key, value in row.items()}
    for field in ALLOWED_TEXT_FIELDS[table]:
        value = updated.get(field)
        if value is None:
            continue
        if field == "slug" and isinstance(value, str):
            updated[field] = replace_blog_slug(value)
        elif field == "generated_content" and isinstance(value, str):
            updated[field] = _transform_json_text(value)
        elif field == "published_snapshot":
            updated[field] = replace_nested_branding(value)
        elif isinstance(value, str):
            updated[field] = replace_brokerage_text(value)

    if table == "link_pack":
        website = str(updated.get("social_website") or "")
        if "soldwithsweeney.kw.com" in website.lower():
            updated["social_website"] = SWS_WEBSITE

    if table == "link_pack_items":
        item_id = updated.get("id")
        original_url = str(row.get("url") or "")
        lowered_url = original_url.lower()
        if "yourhomevaluation" in lowered_url:
            updated["url"] = SWS_SELL_URL
        elif "kw.com/download/" in lowered_url:
            updated["url"] = None
            if item_id == 21:
                updated["is_active"] = False
        elif "soldwithsweeney.kw.com/property/" in lowered_url:
            updated["url"] = SWS_BUY_URL

    return updated


def transform_tables(
    rows: dict[str, list[dict[str, Any]]],
    *,
    background_image_data: bytes | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Transform an allowlisted database snapshot without mutating the input."""
    transformed = {
        table: [transform_row(table, row) for row in table_rows]
        for table, table_rows in rows.items()
    }

    for pack in transformed.get("link_pack", []):
        if background_image_data is not None:
            pack["background_image_data"] = background_image_data
            pack["background_image_mime"] = "image/png"

        snapshot = pack.get("published_snapshot")
        background_bytes = pack.get("background_image_data")
        if isinstance(snapshot, dict) and background_bytes:
            version = hashlib.sha256(background_bytes).hexdigest()[:12]
            snapshot["background_image_url"] = (
                f"/api/v1/link-pack/images/background?v={version}"
            )

    return transformed


def _value_contains_old_branding(value: Any) -> bool:
    if isinstance(value, str):
        return bool(
            _OLD_URL.search(value)
            or _KELLER_WILLIAMS.search(value)
            or _KW_REALTY.search(value)
            or _KW_COMMAND.search(value)
            or _KWRS.search(value)
            or _BARE_KW_BROKERAGE.search(value)
            or _UNRESOLVED_KELLER.search(value)
        )
    if isinstance(value, (list, tuple)):
        return any(_value_contains_old_branding(item) for item in value)
    if isinstance(value, dict):
        return any(_value_contains_old_branding(item) for item in value.values())
    return False


def find_old_brand_remnants(rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Return table/id/field locations containing old branding."""
    remnants: list[str] = []
    for table, table_rows in rows.items():
        fields = ALLOWED_TEXT_FIELDS.get(table)
        if fields is None:
            continue
        for row in table_rows:
            row_id = row.get("id", "?")
            for field in fields:
                if _value_contains_old_branding(row.get(field)):
                    remnants.append(f"{table}[{row_id}].{field}")
    return remnants


def validate_audited_link_items(items: list[dict[str, Any]]) -> None:
    """Abort if audited singleton link IDs no longer identify known records."""
    by_id = {item.get("id"): item for item in items}
    mismatches: list[str] = []
    for item_id, accepted_states in AUDITED_LINK_ITEM_STATES.items():
        item = by_id.get(item_id)
        if item is None:
            mismatches.append(f"item {item_id} is missing")
            continue
        observed = {
            "title": item.get("title"),
            "url": item.get("url"),
            "is_active": item.get("is_active"),
        }
        if observed not in accepted_states:
            mismatches.append(f"item {item_id} does not match its audited identity")
    if mismatches:
        raise RuntimeError("audited link item validation failed: " + "; ".join(mismatches))


def select_sql(table: str, *, for_update: bool) -> str:
    """Build a SELECT from fixed identifiers only."""
    fields = READ_FIELDS.get(table)
    if fields is None:
        raise ValueError(f"table is not allowlisted: {table}")
    columns = ", ".join(f'"{field}"' for field in fields)
    lock = " FOR UPDATE" if for_update else ""
    return f'SELECT {columns} FROM "{table}" ORDER BY "id"{lock}'


def _updateable_fields(table: str) -> frozenset[str]:
    return frozenset(
        (
            *ALLOWED_TEXT_FIELDS.get(table, ()),
            *ALLOWED_BINARY_FIELDS.get(table, ()),
            *ALLOWED_CONTROL_FIELDS.get(table, ()),
        )
    )


def update_sql(table: str, fields: Iterable[str]) -> str:
    """Build a parameterized UPDATE from fixed, validated identifiers."""
    if table not in READ_FIELDS:
        raise ValueError(f"table is not allowlisted: {table}")
    field_list = list(fields)
    invalid = set(field_list) - _updateable_fields(table)
    if invalid:
        raise ValueError(f"fields are not allowlisted for {table}: {sorted(invalid)}")
    if not field_list:
        raise ValueError("at least one update field is required")

    assignments = []
    for field in field_list:
        placeholder = "%s::jsonb" if field == "published_snapshot" else "%s"
        assignments.append(f'"{field}" = {placeholder}')
    if table in UPDATED_AT_TABLES:
        assignments.append('"updated_at" = NOW()')
    return f'UPDATE "{table}" SET {", ".join(assignments)} WHERE "id" = %s'


def _json_safe(value: Any) -> Any:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def default_backup_dir() -> Path:
    configured = os.getenv("SWS_BRANDING_BACKUP_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sws-backups" / "exp-branding"


def write_backup(
    rows: dict[str, list[dict[str, Any]]],
    *,
    backup_dir: Path | str | None = None,
    now: datetime | None = None,
) -> Path:
    """Write a recovery snapshot outside the repo with mode ``0600``."""
    destination = Path(backup_dir or default_backup_dir()).expanduser().resolve()
    if _is_within(destination, REPOSITORY_ROOT.resolve()):
        raise ValueError("backup directory must be outside the repository")

    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stem = f"exp-branding-backup-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    path = destination / f"{stem}.json"
    suffix = 1
    while path.exists():
        path = destination / f"{stem}-{suffix}.json"
        suffix += 1

    payload = {
        "created_at": timestamp.isoformat(),
        "migration": "exp-branding",
        "tables": _json_safe(rows),
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(path, 0o600)
    return path


def _fetch_rows(cursor: Any, *, for_update: bool) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for table, fields in READ_FIELDS.items():
        cursor.execute(select_sql(table, for_update=for_update))
        rows[table] = [dict(zip(fields, values)) for values in cursor.fetchall()]
    return rows


def _changed_fields(
    table: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[str]:
    return [
        field
        for field in _updateable_fields(table)
        if _copy_database_value(before.get(field))
        != _copy_database_value(after.get(field))
    ]


def summarize_changes(
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for table, before_rows in before.items():
        after_by_id = {row["id"]: row for row in after.get(table, [])}
        changed_rows = 0
        changed_fields: set[str] = set()
        for row in before_rows:
            fields = _changed_fields(table, row, after_by_id[row["id"]])
            if fields:
                changed_rows += 1
                changed_fields.update(fields)
        summary[table] = {
            "rows_scanned": len(before_rows),
            "rows_changed": changed_rows,
            "fields_changed": sorted(changed_fields),
        }
    return summary


def _apply_updates(
    cursor: Any,
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
) -> int:
    updates = 0
    for table, before_rows in before.items():
        after_by_id = {row["id"]: row for row in after[table]}
        for original in before_rows:
            transformed = after_by_id[original["id"]]
            fields = _changed_fields(table, original, transformed)
            if not fields:
                continue
            values: list[Any] = []
            for field in fields:
                value = transformed.get(field)
                if field == "published_snapshot":
                    value = json.dumps(value, ensure_ascii=False)
                values.append(value)
            values.append(original["id"])
            cursor.execute(update_sql(table, fields), values)
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"expected one {table} row for id {original['id']}, updated {cursor.rowcount}"
                )
            updates += 1
    return updates


def _validate_funnel_count(
    rows: dict[str, list[dict[str, Any]]], expected_funnels: int | None
) -> None:
    if expected_funnels is None:
        return
    actual = len(rows.get("funnels", []))
    if actual != expected_funnels:
        raise RuntimeError(
            f"expected {expected_funnels} funnel rows from the audited dataset, found {actual}; "
            "rerun the read-only audit and pass the verified count explicitly"
        )


def run_migration(
    connection: Any,
    *,
    apply: bool = False,
    backup_dir: Path | str | None = None,
    background_image_path: Path | str | None = None,
    expected_funnels: int | None = EXPECTED_FUNNEL_COUNT,
) -> dict[str, Any]:
    """Preview or transactionally apply the migration to ``connection``."""
    background_data: bytes | None = None
    if background_image_path is not None:
        background_path = Path(background_image_path).expanduser().resolve()
        if not background_path.is_file():
            raise FileNotFoundError(f"background image not found: {background_path}")
        background_data = background_path.read_bytes()

    cursor = connection.cursor()
    backup_path: Path | None = None
    try:
        if apply:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))

        before = _fetch_rows(cursor, for_update=apply)
        _validate_funnel_count(before, expected_funnels)
        if "link_pack_items" in before:
            validate_audited_link_items(before["link_pack_items"])
        after = transform_tables(before, background_image_data=background_data)
        predicted_remnants = find_old_brand_remnants(after)
        if predicted_remnants:
            raise RuntimeError(
                "post-transform old-brand remnants would remain: "
                + ", ".join(predicted_remnants)
            )

        summary = summarize_changes(before, after)
        planned_updates = sum(item["rows_changed"] for item in summary.values())
        if not apply:
            connection.rollback()
            return {
                "mode": "dry-run",
                "planned_updates": planned_updates,
                "summary": summary,
                "backup_path": None,
                "old_brand_remnants": [],
            }

        if planned_updates:
            backup_path = write_backup(before, backup_dir=backup_dir)
            applied_updates = _apply_updates(cursor, before, after)
        else:
            applied_updates = 0

        verified = _fetch_rows(cursor, for_update=True)
        remnants = find_old_brand_remnants(verified)
        if remnants:
            raise RuntimeError(
                "post-update old-brand remnants detected; rolling back: "
                + ", ".join(remnants)
            )
        connection.commit()
        return {
            "mode": "apply",
            "planned_updates": planned_updates,
            "applied_updates": applied_updates,
            "summary": summary,
            "backup_path": str(backup_path) if backup_path else None,
            "old_brand_remnants": [],
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply transactionally. Without this flag the command rolls back after previewing.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Private backup directory outside the repository.",
    )
    background = parser.add_mutually_exclusive_group()
    background.add_argument(
        "--background-image",
        type=Path,
        default=None,
        help="Optional replacement link-page background image.",
    )
    background.add_argument(
        "--use-packaged-background",
        action="store_true",
        help=f"Use the vetted packaged background at {PACKAGED_BACKGROUND}.",
    )
    parser.add_argument(
        "--expected-funnels",
        type=int,
        default=EXPECTED_FUNNEL_COUNT,
        help="Abort if the audited funnel row count has drifted (default: 16).",
    )
    return parser.parse_args(argv)


def _database_url() -> str:
    sys.path.insert(0, str(BACKEND_ROOT))
    from config import settings

    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    background_path = (
        PACKAGED_BACKGROUND if args.use_packaged_background else args.background_image
    )

    import psycopg2

    connection = psycopg2.connect(_database_url())
    try:
        report = run_migration(
            connection,
            apply=args.apply,
            backup_dir=args.backup_dir,
            background_image_path=background_path,
            expected_funnels=args.expected_funnels,
        )
    finally:
        connection.close()

    print(json.dumps(report, indent=2, sort_keys=True))
    if not args.apply:
        print("Dry run only. Re-run with --apply after reviewing this report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
