from __future__ import annotations

import importlib.util
import json
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "scripts" / "migrate_exp_branding.py"


def _load_migration():
    assert MIGRATION_PATH.exists(), "the eXp branding migration must exist"
    spec = importlib.util.spec_from_file_location("migrate_exp_branding", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_aware_text_replacement_and_slug_are_idempotent():
    migration = _load_migration()
    text = (
        "Sold With Sweeney & Co. is powered by Keller Williams Realty Success. "
        "The KW Realty Success team shares market knowledge without awkward claims."
    )

    updated = migration.replace_brokerage_text(text)

    assert updated == (
        "Sold With Sweeney & Co. is brokered by eXp Realty. "
        "The eXp Realty team shares market knowledge without awkward claims."
    )
    assert migration.replace_brokerage_text(updated) == updated
    assert (
        migration.replace_blog_slug(
            "why-brandon-sweeney-chose-keller-williams-for-his-business"
        )
        == "why-brandon-sweeney-chose-exp-realty-for-his-business"
    )
    assert (
        migration.replace_blog_slug("keller-williams-realty-success-market-update")
        == "exp-realty-market-update"
    )
    assert migration.replace_blog_slug("awkward-market-knowledge") == "awkward-market-knowledge"


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("Keller Williams Realty", "eXp Realty"),
        ("Keller Williams Realty Success", "eXp Realty"),
        ("KW Realty", "eXp Realty"),
        ("KW Realty Success", "eXp Realty"),
        ("Serving with KW", "Serving with eXp Realty"),
        ("A 10 kW solar system", "A 10 kW solar system"),
        ("A 10 kw solar system", "A 10 kw solar system"),
    ),
)
def test_brokerage_replacement_preserves_solar_power_units(source: str, expected: str):
    migration = _load_migration()

    assert migration.replace_brokerage_text(source) == expected


@pytest.mark.parametrize(
    "slug",
    (
        "market-update-",
        "awkward--market-knowledge",
        "-northern-ma-market-update",
        "10-kw-solar-system",
    ),
)
def test_unrelated_blog_slugs_are_byte_for_byte_unchanged(slug: str):
    migration = _load_migration()

    assert migration.replace_blog_slug(slug) == slug


def test_nested_json_replacement_preserves_non_brand_data():
    migration = _load_migration()
    payload = {
        "hero_subtext": "Keller Williams Realty Success",
        "value_props": ["Local knowledge", {"brokerage": "KW Realty Success"}],
        "count": 16,
    }

    updated = migration.replace_nested_branding(payload)

    assert updated == {
        "hero_subtext": "eXp Realty",
        "value_props": ["Local knowledge", {"brokerage": "eXp Realty"}],
        "count": 16,
    }
    assert migration.replace_nested_branding(updated) == updated


def test_binary_database_values_are_normalized_for_transform_and_backup():
    migration = _load_migration()
    binary = memoryview(b"original-background")
    rows = {
        "link_pack": [
            {
                "id": 1,
                "profile_name": "Brandon",
                "profile_bio": "at eXp Realty",
                "social_website": "https://www.soldwithsweeney.com/",
                "published_snapshot": None,
                "background_image_data": binary,
                "background_image_mime": "image/png",
            }
        ]
    }

    transformed = migration.transform_tables(rows)
    serialized = migration._json_safe(rows)

    assert transformed["link_pack"][0]["background_image_data"] == b"original-background"
    assert serialized["link_pack"][0]["background_image_data"] == {
        "encoding": "base64",
        "data": "b3JpZ2luYWwtYmFja2dyb3VuZA==",
    }


def test_equivalent_bytea_memoryview_is_not_reported_as_a_change():
    migration = _load_migration()
    before = {
        "link_pack": [
            {
                "id": 1,
                "profile_name": "Brandon",
                "profile_bio": "at eXp Realty",
                "social_website": "https://www.soldwithsweeney.com/",
                "published_snapshot": None,
                "background_image_data": memoryview(b"black-gold-background").cast("c"),
                "background_image_mime": "image/png",
            }
        ]
    }
    after = migration.transform_tables(before)

    summary = migration.summarize_changes(before, after)

    assert summary["link_pack"]["rows_changed"] == 0
    assert summary["link_pack"]["fields_changed"] == []


def test_link_item_destinations_are_context_aware():
    migration = _load_migration()

    valuation = migration.transform_row(
        "link_pack_items",
        {
            "id": 19,
            "title": "WHAT'S MY HOME WORTH?",
            "url": "https://soldwithsweeney.kw.com/YourHomeValuation",
            "is_active": True,
        },
    )
    app = migration.transform_row(
        "link_pack_items",
        {
            "id": 21,
            "title": "DOWNLOAD MY APP",
            "url": "https://kw.com/download/example",
            "is_active": False,
        },
    )
    listing = migration.transform_row(
        "link_pack_items",
        {
            "id": 7,
            "title": "50 Frank St | Keller Williams",
            "url": "https://soldwithsweeney.kw.com/property/50-Frank-St/123",
            "is_active": True,
        },
    )

    assert valuation["url"] == "https://www.soldwithsweeney.com/sell"
    assert app["url"] is None
    assert listing["title"] == "50 Frank St | eXp Realty"
    assert listing["url"] == "https://www.soldwithsweeney.com/buy"


_UNSET = object()


def _audited_link_items(*, valuation_title=None, valuation_url=None, app_url=_UNSET):
    return [
        {
            "id": 19,
            "title": valuation_title or "WHAT'S MY HOME WORTH? \U0001f4b8",
            "url": valuation_url or "https://soldwithsweeney.kw.com/YourHomeValuation",
            "is_active": True,
        },
        {
            "id": 21,
            "title": "DOWNLOAD MY APP \U0001f3e1",
            "url": (
                "https://kw.com/download/KW4ABYJHJ" if app_url is _UNSET else app_url
            ),
            "is_active": False,
        },
    ]


def test_audited_link_item_validation_accepts_only_old_or_migrated_state():
    migration = _load_migration()

    migration.validate_audited_link_items(_audited_link_items())
    migration.validate_audited_link_items(
        _audited_link_items(
            valuation_url="https://www.soldwithsweeney.com/sell",
            app_url=None,
        )
    )

    with pytest.raises(RuntimeError, match="item 19"):
        migration.validate_audited_link_items(
            _audited_link_items(valuation_title="UNRELATED LINK")
        )
    with pytest.raises(RuntimeError, match="item 21"):
        migration.validate_audited_link_items(
            _audited_link_items(app_url="https://example.com/unrelated")
        )


def test_allowlist_and_safety_constants_are_explicit():
    migration = _load_migration()

    assert migration.ADVISORY_LOCK_ID == 842913571
    assert migration.ALLOWED_TEXT_FIELDS == {
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
    assert migration.EXPECTED_FUNNEL_COUNT == 16
    assert "FOR UPDATE" in migration.select_sql("funnels", for_update=True)
    assert "FOR UPDATE" not in migration.select_sql("funnels", for_update=False)
    with pytest.raises(ValueError):
        migration.select_sql("leads", for_update=True)


def test_backup_is_timestamped_private_and_rejects_repo_destination(tmp_path: Path):
    migration = _load_migration()
    now = datetime(2026, 8, 1, 14, 30, 45, tzinfo=timezone.utc)

    backup = migration.write_backup(
        {"blogs": [{"id": "abc", "title": "before"}]},
        backup_dir=tmp_path,
        now=now,
    )

    assert backup.name == "exp-branding-backup-20260801T143045Z.json"
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert json.loads(backup.read_text())["tables"]["blogs"][0]["title"] == "before"

    with pytest.raises(ValueError, match="outside the repository"):
        migration.write_backup({}, backup_dir=BACKEND_ROOT / "backups", now=now)


def test_old_brand_remnant_detection_scans_only_allowlisted_values():
    migration = _load_migration()
    rows = {
        "blogs": [
            {
                "id": "1",
                "title": "Clean eXp Realty title",
                "content": "Body still says Keller Williams.",
                "unrelated": "KW should not be inspected here",
            }
        ]
    }

    remnants = migration.find_old_brand_remnants(rows)

    assert remnants == ["blogs[1].content"]


def test_cli_defaults_to_dry_run_and_requires_flag_to_apply():
    migration = _load_migration()

    assert migration.parse_args([]).apply is False
    assert migration.parse_args(["--apply"]).apply is True


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self.rowcount = 1
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_dry_run_rolls_back_without_lock_backup_or_updates(monkeypatch):
    migration = _load_migration()
    connection = _FakeConnection()
    rows = {
        "blogs": [
            {
                "id": "1",
                "title": "Keller Williams market update",
                "slug": "keller-williams-market-update",
                "content": "Keller Williams",
                "excerpt": None,
                "author_role": None,
                "author_bio": None,
            }
        ]
    }
    monkeypatch.setattr(migration, "_fetch_rows", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(
        migration,
        "write_backup",
        lambda *_args, **_kwargs: pytest.fail("dry run must not write a backup"),
    )
    monkeypatch.setattr(
        migration,
        "_apply_updates",
        lambda *_args, **_kwargs: pytest.fail("dry run must not update rows"),
    )

    report = migration.run_migration(
        connection,
        apply=False,
        expected_funnels=None,
    )

    assert report["mode"] == "dry-run"
    assert report["planned_updates"] == 1
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.cursor_instance.executed == []
    assert connection.cursor_instance.closed is True


def test_apply_takes_lock_and_rolls_back_on_post_update_remnant(monkeypatch, tmp_path: Path):
    migration = _load_migration()
    connection = _FakeConnection()
    old_rows = {
        "blogs": [
            {
                "id": "1",
                "title": "Keller Williams market update",
                "slug": "keller-williams-market-update",
                "content": "Keller Williams",
                "excerpt": None,
                "author_role": None,
                "author_bio": None,
            }
        ]
    }
    fetches = iter((old_rows, old_rows))
    monkeypatch.setattr(migration, "_fetch_rows", lambda *_args, **_kwargs: next(fetches))
    monkeypatch.setattr(migration, "_apply_updates", lambda *_args, **_kwargs: 1)

    with pytest.raises(RuntimeError, match="rolling back"):
        migration.run_migration(
            connection,
            apply=True,
            backup_dir=tmp_path,
            expected_funnels=None,
        )

    assert connection.cursor_instance.executed[0] == (
        "SELECT pg_advisory_xact_lock(%s)",
        (842913571,),
    )
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.cursor_instance.closed is True
    assert len(list(tmp_path.glob("exp-branding-backup-*.json"))) == 1


def test_apply_aborts_before_backup_when_audited_link_id_has_drifted(
    monkeypatch, tmp_path: Path
):
    migration = _load_migration()
    connection = _FakeConnection()
    rows = {"link_pack_items": _audited_link_items(valuation_title="UNRELATED LINK")}
    monkeypatch.setattr(migration, "_fetch_rows", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(
        migration,
        "write_backup",
        lambda *_args, **_kwargs: pytest.fail("identity mismatch must precede backup"),
    )
    monkeypatch.setattr(
        migration,
        "_apply_updates",
        lambda *_args, **_kwargs: pytest.fail("identity mismatch must precede updates"),
    )

    with pytest.raises(RuntimeError, match="item 19"):
        migration.run_migration(
            connection,
            apply=True,
            backup_dir=tmp_path,
            expected_funnels=None,
        )

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert list(tmp_path.iterdir()) == []


def test_backend_asset_and_provenance_are_packaged():
    image = BACKEND_ROOT / "assets" / "link-pack-black-gold-clean.png"
    provenance = BACKEND_ROOT / "assets" / "link-pack-black-gold-clean.source.json"

    assert image.exists()
    assert provenance.exists()
    metadata = json.loads(provenance.read_text())
    assert metadata["output"]["sha256"] == (
        "23791c5985bf0d559536f2382f8577379bca913bd31e88fe652ac7dacb7ac345"
    )
    assert metadata["source"]["sha256"] == (
        "2aec36432fb193a85d5e189414acd3ffc27f18fea9436ee71fe3619b86395a21"
    )


def test_active_sources_and_current_contract_do_not_reintroduce_old_brokerage():
    repository = BACKEND_ROOT.parent
    exact_files = (
        repository / ".env.example",
        repository / "AGENTS.md",
        repository / "claude.md",
        repository / "BRANDON_RE_SPEC.md",
    )
    source_roots = (repository / "backend", repository / "frontend" / "src")
    source_suffixes = {".py", ".ts", ".tsx", ".js", ".jsx", ".example"}
    fully_allowlisted = {
        repository / "backend" / "scripts" / "migrate_exp_branding.py",
        repository / "backend" / "assets" / "link-pack-black-gold-clean.source.json",
    }
    redirect_file = repository / "frontend" / "src" / "app" / "(main)" / "blog" / "[slug]" / "page.tsx"
    redirect_line = re.compile(
        r"^const LEGACY_BROKERAGE_SLUG = "
        r"'the-strategic-edge-why-brandon-sweeney-partnered-with-keller-williams';$",
        re.IGNORECASE,
    )
    old_marker = re.compile(
        r"(?i:\bkeller\b|\bkwrs\b|\bkw_crm\b|\bkw\s+(?:realty|command)\b|"
        r"(?:soldwithsweeney\.)?kw\.com)|\b(?:KW|kw)\b"
    )

    active_files = set(exact_files)
    for root in source_roots:
        active_files.update(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in source_suffixes
            and "tests" not in path.parts
            and ".venv" not in path.parts
        )

    matches = []
    for path in sorted(active_files):
        if path in fully_allowlisted:
            continue
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if path == redirect_file and redirect_line.fullmatch(line.strip()):
                continue
            if old_marker.search(line):
                matches.append(f"{path.relative_to(repository)}:{line_number}: {line.strip()}")

    old_asset_names = [
        str(path.relative_to(repository))
        for path in (repository / "frontend" / "public").rglob("*")
        if path.is_file() and old_marker.search(path.name)
    ]

    assert matches == []
    assert old_asset_names == []
