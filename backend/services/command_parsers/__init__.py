"""Public contracts and defaults for deterministic Command archive parsing."""

from services.command_parsers.archive_integrity import ArchiveIntegrityParser
from services.command_parsers.base import (
    CommandArchiveParser,
    DuplicateParserError,
    ModuleMetrics,
    ModuleParseResult,
    ParserRegistry,
    ParserRegistryError,
    ParserResultValidationError,
    UnknownParserModuleError,
    validate_parser_module,
)
from services.command_provenance import ArchiveIntegrityError


def default_parser_registry() -> ParserRegistry:
    """Build an independent registry containing the baseline archive parser."""
    registry = ParserRegistry()
    registry.register(ArchiveIntegrityParser())
    return registry


__all__ = (
    "ArchiveIntegrityError",
    "ArchiveIntegrityParser",
    "CommandArchiveParser",
    "DuplicateParserError",
    "ModuleMetrics",
    "ModuleParseResult",
    "ParserRegistry",
    "ParserRegistryError",
    "ParserResultValidationError",
    "UnknownParserModuleError",
    "default_parser_registry",
    "validate_parser_module",
)
