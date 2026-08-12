from dataclasses import FrozenInstanceError, replace
import hashlib
from types import MappingProxyType

import pytest

from models.command_provenance import EvidenceLevel
import services.command_parsers as command_parsers
from services.command_parsers import (
    ArchiveIntegrityParser,
    CommandArchiveParser,
    DuplicateParserError,
    ModuleMetrics,
    ModuleParseResult,
    ParserRegistry,
    ParserRegistryError,
    ParserResultValidationError,
    UnknownParserModuleError,
    default_parser_registry,
)
from services.command_provenance import (
    ArchiveArtifactInput,
    ArchiveIntegrityError,
    SourceRecordDraft,
)


def artifact_for(content: bytes = b"private archive bytes", **overrides):
    values = {
        "id": 1,
        "source_path": "kw_command_repaired/contacts/contact.json",
        "domain": "kw_command",
        "artifact_type": "json",
        "filename": "contact.json",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "content_bytes": content,
    }
    values.update(overrides)
    return ArchiveArtifactInput(**values)


def source_draft(**overrides):
    values = {
        "source_system": "kw_command",
        "module": "contacts",
        "record_kind": "contact",
        "source_key": "63ac84e09655a08ec4d5d3ef",
        "evidence_level": EvidenceLevel.OBSERVED_RECORD,
        "display_label": "José Rivera",
        "payload": {"name": "José Rivera"},
        "artifact_paths": ("kw_command_repaired/contacts/contact.json",),
        "parser_version": "command-v1",
    }
    values.update(overrides)
    return SourceRecordDraft(**values)


def metrics_for(**overrides):
    values = {
        "source_system": "kw_command",
        "module": "contacts",
        "expected_count": 1,
        "observed_count": 1,
    }
    values.update(overrides)
    return ModuleMetrics(**values)


class FakeParser:
    def __init__(self, module: str):
        self.module = module
        self.parse_calls = 0

    def parse(self, artifacts, parser_version):
        self.parse_calls += 1
        return ModuleParseResult(
            records=(),
            metrics=ModuleMetrics(
                source_system="fake",
                module=self.module,
                expected_count=len(artifacts),
                observed_count=len(artifacts),
            ),
        )


def test_command_archive_parser_is_runtime_checkable():
    assert isinstance(FakeParser("contacts"), CommandArchiveParser)


def test_registry_orders_all_parsers_and_filters_selected_modules():
    registry = ParserRegistry()
    tasks = FakeParser("tasks")
    contacts = FakeParser("contacts")
    opportunities = FakeParser("opportunities")
    registry.register(tasks)
    registry.register(contacts)
    registry.register(opportunities)

    assert tuple(parser.module for parser in registry.select(None)) == (
        "contacts",
        "opportunities",
        "tasks",
    )
    assert tuple(
        parser.module
        for parser in registry.select(frozenset({"tasks", "contacts"}))
    ) == ("contacts", "tasks")
    assert registry.select(set()) == ()


def test_registry_registration_does_not_invoke_parser():
    parser = FakeParser("contacts")

    ParserRegistry().register(parser)

    assert parser.parse_calls == 0


def test_registry_exposes_stable_registered_module_snapshot():
    registry = ParserRegistry()
    contacts = FakeParser("contacts")
    tasks = FakeParser("tasks")
    registry.register(tasks)
    registry.register(contacts)
    tasks.module = "changed"

    assert registry.registered_modules() == frozenset({"contacts", "tasks"})


@pytest.mark.parametrize(
    "selected_modules",
    [None, {"tasks"}],
    ids=["all-modules", "registered-key"],
)
def test_registry_rejects_parser_whose_module_changed_after_registration(
    selected_modules,
):
    parser = FakeParser("tasks")
    registry = ParserRegistry()
    registry.register(parser)
    parser.module = "contacts"

    with pytest.raises(ParserRegistryError) as exc_info:
        registry.select(selected_modules)

    assert str(exc_info.value) == (
        "parser registered under 'tasks' now reports module 'contacts'"
    )


@pytest.mark.parametrize(
    ("current_module", "display"),
    [("", "''"), (" \t", "' \\t'"), (17, "17")],
    ids=["empty", "whitespace", "non-string"],
)
def test_registry_rejects_invalid_module_value_after_registration(
    current_module, display
):
    parser = FakeParser("tasks")
    registry = ParserRegistry()
    registry.register(parser)
    parser.module = current_module

    with pytest.raises(ParserRegistryError) as exc_info:
        registry.select(None)

    assert str(exc_info.value) == (
        f"parser registered under 'tasks' now reports module {display}"
    )


def test_public_parser_module_validator_rejects_mutated_parser():
    parser = FakeParser("tasks")
    parser.module = "contacts"

    with pytest.raises(ParserRegistryError) as exc_info:
        command_parsers.validate_parser_module(parser, "tasks")

    assert str(exc_info.value) == (
        "parser registered under 'tasks' now reports module 'contacts'"
    )


def test_registry_rejects_duplicate_module():
    registry = ParserRegistry()
    registry.register(FakeParser("contacts"))

    with pytest.raises(DuplicateParserError, match="contacts"):
        registry.register(FakeParser("contacts"))


@pytest.mark.parametrize("module", ["", " \t\n"])
def test_registry_rejects_blank_module(module):
    with pytest.raises(ParserRegistryError, match="module"):
        ParserRegistry().register(FakeParser(module))


@pytest.mark.parametrize(
    "invalid_parser",
    [
        object(),
        type("MissingParse", (), {"module": "contacts"})(),
        type("NonCallableParse", (), {"module": "contacts", "parse": None})(),
        type("NonStringModule", (), {"module": 1, "parse": lambda self: None})(),
    ],
    ids=["plain-object", "missing-parse", "noncallable-parse", "nonstring-module"],
)
def test_registry_rejects_invalid_parser_contract(invalid_parser):
    with pytest.raises(ParserRegistryError):
        ParserRegistry().register(invalid_parser)


def test_registry_reports_every_unknown_selected_module_alphabetically():
    registry = ParserRegistry()
    registry.register(FakeParser("contacts"))

    with pytest.raises(UnknownParserModuleError) as exc_info:
        registry.select({"zeta", "contacts", "alpha"})

    message = str(exc_info.value)
    assert "alpha" in message
    assert "zeta" in message
    assert message.index("alpha") < message.index("zeta")


@pytest.mark.parametrize("field", ["source_system", "module"])
@pytest.mark.parametrize("blank", ["", " \t\n"])
def test_module_metrics_rejects_blank_identity_fields(field, blank):
    with pytest.raises(ParserResultValidationError, match=field):
        metrics_for(**{field: blank})


@pytest.mark.parametrize(
    "field",
    [
        "expected_count",
        "observed_count",
        "rendered_count",
        "normalized_count",
        "evidence_only_count",
        "unmatched_count",
        "duplicate_content_count",
        "error_count",
    ],
)
def test_module_metrics_rejects_negative_counts(field):
    with pytest.raises(ParserResultValidationError, match=field):
        metrics_for(**{field: -1})


@pytest.mark.parametrize("invalid_count", [1.5, True, "1"])
def test_module_metrics_rejects_non_integer_counts(invalid_count):
    with pytest.raises(ParserResultValidationError, match="observed_count"):
        metrics_for(observed_count=invalid_count)


def test_module_metrics_allows_unknown_expected_count():
    assert metrics_for(expected_count=None).expected_count is None


def test_module_metrics_are_frozen_slotted_values_with_immutable_default_details():
    metrics = metrics_for()

    with pytest.raises(FrozenInstanceError):
        metrics.module = "tasks"
    with pytest.raises(TypeError):
        metrics.details["later"] = True

    assert not hasattr(metrics, "__dict__")
    assert isinstance(metrics.details, MappingProxyType)
    assert metrics.details == {}


def test_module_metrics_deep_snapshots_details_immutably():
    original_details = {
        "domains": {"kw_command": 1},
        "warnings": ["partial"],
    }
    metrics = metrics_for(details=original_details)

    original_details["domains"]["docusign"] = 2
    original_details["warnings"].append("late mutation")
    original_details["added_later"] = True

    assert metrics.details == {
        "domains": {"kw_command": 1},
        "warnings": ("partial",),
    }
    assert isinstance(metrics.details, MappingProxyType)
    assert isinstance(metrics.details["domains"], MappingProxyType)
    with pytest.raises(TypeError):
        metrics.details["domains"]["kw_command"] = 9
    with pytest.raises(TypeError):
        metrics.details["warnings"][0] = "changed"


def test_module_parse_result_requires_records_tuple():
    with pytest.raises(ParserResultValidationError, match="tuple"):
        ModuleParseResult(records=[], metrics=metrics_for())


def test_module_parse_result_rejects_duplicate_draft_identity():
    first = source_draft()
    duplicate = source_draft(display_label="Different label")

    with pytest.raises(ParserResultValidationError, match="duplicate"):
        ModuleParseResult(records=(first, duplicate), metrics=metrics_for())


@pytest.mark.parametrize(
    ("draft_overrides", "match"),
    [
        ({"source_system": "docusign"}, "source_system"),
        ({"module": "tasks"}, "module"),
    ],
)
def test_module_parse_result_requires_drafts_to_match_metrics(
    draft_overrides, match
):
    with pytest.raises(ParserResultValidationError, match=match):
        ModuleParseResult(
            records=(source_draft(**draft_overrides),),
            metrics=metrics_for(),
        )


def test_module_parse_result_rejects_non_draft_records():
    with pytest.raises(ParserResultValidationError, match="SourceRecordDraft"):
        ModuleParseResult(records=(object(),), metrics=metrics_for())


def test_module_parse_result_is_a_frozen_slotted_value():
    result = ModuleParseResult(records=(source_draft(),), metrics=metrics_for())

    with pytest.raises(FrozenInstanceError):
        result.records = ()

    assert not hasattr(result, "__dict__")


def test_archive_integrity_parser_reports_bytes_domains_and_duplicate_content():
    alpha = artifact_for(
        b"alpha",
        id=1,
        source_path="z/alpha.json",
        domain="kw_command",
    )
    beta = artifact_for(
        b"beta",
        id=2,
        source_path="a/beta.json",
        domain="docusign",
    )
    repeated_alpha = artifact_for(
        b"alpha",
        id=3,
        source_path="m/alpha-copy.json",
        domain="kw_command",
    )

    result = ArchiveIntegrityParser().parse(
        [alpha, beta, repeated_alpha], parser_version="command-v1"
    )

    assert result.records == ()
    assert result.metrics.source_system == "all"
    assert result.metrics.module == "archive_integrity"
    assert result.metrics.expected_count == 3
    assert result.metrics.observed_count == 3
    assert result.metrics.rendered_count == 0
    assert result.metrics.normalized_count == 0
    assert result.metrics.evidence_only_count == 0
    assert result.metrics.unmatched_count == 0
    assert result.metrics.duplicate_content_count == 1
    assert result.metrics.error_count == 0
    assert result.metrics.details == {
        "artifacts": 3,
        "bytes": len(b"alpha") * 2 + len(b"beta"),
        "domains": {"docusign": 1, "kw_command": 2},
        "duplicate_content": 1,
    }
    assert tuple(result.metrics.details["domains"]) == (
        "docusign",
        "kw_command",
    )


def test_archive_integrity_parser_handles_empty_input():
    result = ArchiveIntegrityParser().parse([], parser_version="command-v1")

    assert result.records == ()
    assert result.metrics.expected_count == 0
    assert result.metrics.observed_count == 0
    assert result.metrics.duplicate_content_count == 0
    assert result.metrics.details == {
        "artifacts": 0,
        "bytes": 0,
        "domains": {},
        "duplicate_content": 0,
    }


@pytest.mark.parametrize(
    "invalid_domain",
    ["", " \t\n", [], object()],
    ids=["empty", "whitespace", "list", "object"],
)
def test_archive_integrity_parser_rejects_invalid_domain_with_path_context(
    invalid_domain,
):
    artifact = artifact_for(domain=invalid_domain)

    with pytest.raises(ArchiveIntegrityError) as exc_info:
        ArchiveIntegrityParser().parse(
            [artifact], parser_version="command-v1"
        )

    assert str(exc_info.value) == (
        "artifact 'kw_command_repaired/contacts/contact.json' domain must be "
        "a nonblank string"
    )


def test_archive_integrity_parser_verifies_bytes_before_domain():
    artifact = replace(
        artifact_for(domain=[]),
        sha256="0" * 64,
    )

    with pytest.raises(ArchiveIntegrityError, match="checksum"):
        ArchiveIntegrityParser().parse(
            [artifact], parser_version="command-v1"
        )


def test_archive_integrity_parser_preserves_arbitrary_nonblank_domains_sorted():
    zeta = artifact_for(
        b"zeta",
        id=1,
        source_path="z/zeta.json",
        domain="z.custom/v2",
    )
    alpha = artifact_for(
        b"alpha",
        id=2,
        source_path="a/alpha.json",
        domain="A custom domain",
    )

    result = ArchiveIntegrityParser().parse(
        [zeta, alpha], parser_version="command-v1"
    )

    assert result.metrics.details["domains"] == {
        "A custom domain": 1,
        "z.custom/v2": 1,
    }
    assert tuple(result.metrics.details["domains"]) == (
        "A custom domain",
        "z.custom/v2",
    )


@pytest.mark.parametrize(
    "invalid_artifact",
    [
        object(),
        replace(artifact_for(), sha256="0" * 64),
    ],
    ids=["wrong-type", "checksum-mismatch"],
)
def test_archive_integrity_parser_rejects_invalid_artifact(invalid_artifact):
    with pytest.raises(ArchiveIntegrityError):
        ArchiveIntegrityParser().parse(
            [invalid_artifact], parser_version="command-v1"
        )


def test_archive_integrity_parser_rejects_duplicate_source_path():
    first = artifact_for(b"alpha")
    duplicate_path = artifact_for(b"beta", id=2, source_path=first.source_path)

    with pytest.raises(ArchiveIntegrityError, match="duplicate source_path"):
        ArchiveIntegrityParser().parse(
            [first, duplicate_path], parser_version="command-v1"
        )


@pytest.mark.parametrize("parser_version", ["", " \t\n", None])
def test_archive_integrity_parser_rejects_blank_parser_version(parser_version):
    with pytest.raises(ArchiveIntegrityError, match="parser_version"):
        ArchiveIntegrityParser().parse([], parser_version=parser_version)


def test_default_registry_returns_fresh_independent_registry_instances():
    first = default_parser_registry()
    second = default_parser_registry()

    assert first is not second
    assert tuple(parser.module for parser in first.select(None)) == (
        "archive_integrity",
    )
    assert tuple(parser.module for parser in second.select(None)) == (
        "archive_integrity",
    )
    assert first.select(None)[0] is not second.select(None)[0]

    first.register(FakeParser("contacts"))

    assert tuple(parser.module for parser in first.select(None)) == (
        "archive_integrity",
        "contacts",
    )
    assert tuple(parser.module for parser in second.select(None)) == (
        "archive_integrity",
    )
