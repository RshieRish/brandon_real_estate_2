"""Public contracts and defaults for deterministic Command archive parsing."""

from services.command_parsers.archive_integrity import ArchiveIntegrityParser
from services.command_parsers.contacts import ContactsParser
from services.command_parsers.base import (
    CommandArchiveParser,
    DuplicateParserError,
    ModuleMetrics,
    ModuleParseResult,
    ParserRegistry,
    ParserRegistryError,
    StructuredParserError,
    ParserResultValidationError,
    UnknownParserModuleError,
    validate_parser_module,
)
from services.command_provenance import ArchiveIntegrityError


def default_parser_registry() -> ParserRegistry:
    """Build an independent registry containing all production parsers."""
    registry = ParserRegistry()
    registry.register(ArchiveIntegrityParser())
    registry.register(ContactsParser())
    return registry


__all__ = (
    "ArchiveIntegrityError",
    "ArchiveIntegrityParser",
    "CommandArchiveParser",
    "ContactsParser",
    "DuplicateParserError",
    "ModuleMetrics",
    "ModuleParseResult",
    "ParserRegistry",
    "ParserRegistryError",
    "StructuredParserError",
    "ParserResultValidationError",
    "UnknownParserModuleError",
    "default_parser_registry",
    "validate_parser_module",
)
