"""Shared contracts and deterministic registry for Command archive parsers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from services.command_provenance import ArchiveArtifactInput, SourceRecordDraft


class ParserResultValidationError(ValueError):
    """Raised when parser metrics or semantic records are internally inconsistent."""


class ParserRegistryError(ValueError):
    """Raised when a parser cannot be registered or selected safely."""


class DuplicateParserError(ParserRegistryError):
    """Raised when more than one parser claims the same module."""


class UnknownParserModuleError(ParserRegistryError):
    """Raised when requested parser modules have not been registered."""


def validate_parser_module(
    parser: CommandArchiveParser,
    expected_module: str,
) -> None:
    """Require a parser to retain the module identity it was registered under."""
    current_module = getattr(parser, "module", None)
    if (
        not isinstance(current_module, str)
        or not current_module.strip()
        or current_module != expected_module
    ):
        raise ParserRegistryError(
            f"parser registered under {expected_module!r} now reports module "
            f"{current_module!r}"
        )


def _immutable_snapshot(
    value: object,
    ancestors: set[int] | None = None,
) -> object:
    """Copy supported container values into recursively immutable containers."""
    if not isinstance(value, Mapping | list | tuple | set | frozenset | bytearray):
        return value

    if ancestors is None:
        ancestors = set()
    identity = id(value)
    if identity in ancestors:
        raise ParserResultValidationError(
            "details cannot contain circular references"
        )
    ancestors.add(identity)
    try:
        if isinstance(value, Mapping):
            return MappingProxyType(
                {
                    key: _immutable_snapshot(item, ancestors)
                    for key, item in value.items()
                }
            )
        if isinstance(value, list | tuple):
            return tuple(_immutable_snapshot(item, ancestors) for item in value)
        if isinstance(value, set | frozenset):
            return frozenset(
                _immutable_snapshot(item, ancestors) for item in value
            )
        return bytes(value)
    finally:
        ancestors.remove(identity)


@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    source_system: str
    module: str
    expected_count: int | None
    observed_count: int
    rendered_count: int = 0
    normalized_count: int = 0
    evidence_only_count: int = 0
    unmatched_count: int = 0
    duplicate_content_count: int = 0
    error_count: int = 0
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("source_system", "module"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ParserResultValidationError(
                    f"{field_name} must be nonblank"
                )

        for field_name in (
            "expected_count",
            "observed_count",
            "rendered_count",
            "normalized_count",
            "evidence_only_count",
            "unmatched_count",
            "duplicate_content_count",
            "error_count",
        ):
            value = getattr(self, field_name)
            if field_name == "expected_count" and value is None:
                continue
            if type(value) is not int or value < 0:
                raise ParserResultValidationError(
                    f"{field_name} must be a non-negative integer"
                )

        if not isinstance(self.details, Mapping):
            raise ParserResultValidationError("details must be a mapping")
        object.__setattr__(self, "details", _immutable_snapshot(self.details))


@dataclass(frozen=True, slots=True)
class ModuleParseResult:
    records: tuple[SourceRecordDraft, ...]
    metrics: ModuleMetrics

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple):
            raise ParserResultValidationError("records must be a tuple")
        if not isinstance(self.metrics, ModuleMetrics):
            raise ParserResultValidationError("metrics must be ModuleMetrics")

        identities: set[tuple[str, str, str, str, str]] = set()
        for draft in self.records:
            if not isinstance(draft, SourceRecordDraft):
                raise ParserResultValidationError(
                    "records must contain only SourceRecordDraft values"
                )
            if draft.source_system != self.metrics.source_system:
                raise ParserResultValidationError(
                    "record source_system must match metrics source_system"
                )
            if draft.module != self.metrics.module:
                raise ParserResultValidationError(
                    "record module must match metrics module"
                )
            if draft.identity in identities:
                raise ParserResultValidationError(
                    f"records contain duplicate draft identity: {draft.identity}"
                )
            identities.add(draft.identity)


@runtime_checkable
class CommandArchiveParser(Protocol):
    module: str

    def parse(
        self,
        artifacts: Sequence[ArchiveArtifactInput],
        parser_version: str,
    ) -> ModuleParseResult:
        """Parse a validated archive bundle into semantic source drafts."""
        ...


@runtime_checkable
class StructuredParserError(Protocol):
    """Safe parser failure details that reconciliation may persist and retry."""

    source_system: str
    module: str
    expected_count: int | None
    error_count: int

    @property
    def audit_details(self) -> Mapping[str, object]:
        """Return canonical, privacy-safe structured failure details."""
        ...


class ParserRegistry:
    """Register one parser per module and select them deterministically."""

    __slots__ = ("_parsers",)

    def __init__(self) -> None:
        self._parsers: dict[str, CommandArchiveParser] = {}

    def register(self, parser: CommandArchiveParser) -> None:
        module = getattr(parser, "module", None)
        parse = getattr(parser, "parse", None)
        if not isinstance(module, str) or not module.strip():
            raise ParserRegistryError("parser module must be a nonblank string")
        if not isinstance(parser, CommandArchiveParser) or not callable(parse):
            raise ParserRegistryError(
                f"parser for module {module!r} must satisfy CommandArchiveParser"
            )
        if module in self._parsers:
            raise DuplicateParserError(
                f"parser module is already registered: {module}"
            )
        self._parsers[module] = parser

    def registered_modules(self) -> frozenset[str]:
        """Return the stable registration keys without invoking parser code."""
        return frozenset(self._parsers)

    def select(
        self,
        modules: frozenset[str] | set[str] | None,
    ) -> tuple[CommandArchiveParser, ...]:
        if modules is None:
            selected_modules = set(self._parsers)
        else:
            if not isinstance(modules, set | frozenset):
                raise ParserRegistryError(
                    "selected modules must be a set, frozenset, or None"
                )
            if any(
                not isinstance(module, str) or not module.strip()
                for module in modules
            ):
                raise ParserRegistryError(
                    "selected modules must contain nonblank strings"
                )
            selected_modules = set(modules)

        unknown_modules = selected_modules.difference(self._parsers)
        if unknown_modules:
            names = ", ".join(sorted(unknown_modules))
            raise UnknownParserModuleError(f"unknown parser modules: {names}")

        selected_parsers = []
        for module in sorted(selected_modules):
            parser = self._parsers[module]
            validate_parser_module(parser, module)
            selected_parsers.append(parser)
        return tuple(selected_parsers)
