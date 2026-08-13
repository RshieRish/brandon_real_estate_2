"""Shared immutable contracts for Command domain materializers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from services.command_provenance import SourceRecordDraft


class MaterializerRegistryError(ValueError):
    """Raised when materializer registration or selection is unsafe."""


class DuplicateMaterializerError(MaterializerRegistryError):
    """Raised when two materializers claim one module."""


class UnknownMaterializerModuleError(MaterializerRegistryError):
    """Raised when a requested module has no materializer."""


class MaterializationResultValidationError(ValueError):
    """Raised when a materializer returns invalid audit metrics."""


def _immutable(value: object, ancestors: set[int] | None = None) -> object:
    if not isinstance(value, Mapping | list | tuple | set | frozenset):
        return value
    if ancestors is None:
        ancestors = set()
    identity = id(value)
    if identity in ancestors:
        raise MaterializationResultValidationError(
            "materialization details cannot contain circular references"
        )
    ancestors.add(identity)
    try:
        if isinstance(value, Mapping):
            return MappingProxyType(
                {str(key): _immutable(item, ancestors) for key, item in value.items()}
            )
        if isinstance(value, list | tuple):
            return tuple(_immutable(item, ancestors) for item in value)
        return frozenset(_immutable(item, ancestors) for item in value)
    finally:
        ancestors.remove(identity)


@dataclass(frozen=True, slots=True)
class ModuleMaterializationResult:
    module: str
    normalized_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    links_created: int
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.module, str) or not self.module.strip():
            raise MaterializationResultValidationError("module must be nonblank")
        for field_name in (
            "normalized_count",
            "created_count",
            "updated_count",
            "unchanged_count",
            "links_created",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise MaterializationResultValidationError(
                    f"{field_name} must be a non-negative integer"
                )
        if not isinstance(self.details, Mapping):
            raise MaterializationResultValidationError("details must be a mapping")
        object.__setattr__(self, "details", _immutable(self.details))


@runtime_checkable
class CommandDomainMaterializer(Protocol):
    module: str

    async def materialize(
        self,
        db: AsyncSession,
        records: Sequence[SourceRecordDraft],
        *,
        bundle_fingerprint: str,
    ) -> ModuleMaterializationResult:
        """Materialize one parsed module inside the caller transaction."""
        ...


def validate_materializer_module(
    materializer: CommandDomainMaterializer,
    expected_module: str,
) -> None:
    current_module = getattr(materializer, "module", None)
    if (
        not isinstance(current_module, str)
        or not current_module.strip()
        or current_module != expected_module
    ):
        raise MaterializerRegistryError(
            "registered materializer reports a different module"
        )


class MaterializerRegistry:
    """Register one materializer per module and select deterministically."""

    __slots__ = ("_materializers",)

    def __init__(self) -> None:
        self._materializers: dict[str, CommandDomainMaterializer] = {}

    def register(self, materializer: CommandDomainMaterializer) -> None:
        module = getattr(materializer, "module", None)
        method = getattr(materializer, "materialize", None)
        if not isinstance(module, str) or not module.strip():
            raise MaterializerRegistryError("materializer module must be nonblank")
        if not isinstance(materializer, CommandDomainMaterializer) or not callable(
            method
        ):
            raise MaterializerRegistryError(
                "materializer must satisfy CommandDomainMaterializer"
            )
        if module in self._materializers:
            raise DuplicateMaterializerError(
                f"materializer module is already registered: {module}"
            )
        self._materializers[module] = materializer

    def registered_modules(self) -> frozenset[str]:
        return frozenset(self._materializers)

    def select(
        self,
        modules: frozenset[str] | set[str] | None,
    ) -> tuple[CommandDomainMaterializer, ...]:
        if modules is None:
            selected = set(self._materializers)
        else:
            if not isinstance(modules, set | frozenset):
                raise MaterializerRegistryError(
                    "selected modules must be a set, frozenset, or None"
                )
            if any(
                not isinstance(module, str) or not module.strip()
                for module in modules
            ):
                raise MaterializerRegistryError(
                    "selected modules must contain nonblank strings"
                )
            selected = set(modules)
        unknown = selected.difference(self._materializers)
        if unknown:
            raise UnknownMaterializerModuleError(
                "unknown materializer modules: " + ", ".join(sorted(unknown))
            )
        values = []
        for module in sorted(selected):
            materializer = self._materializers[module]
            validate_materializer_module(materializer, module)
            values.append(materializer)
        return tuple(values)


__all__ = (
    "CommandDomainMaterializer",
    "DuplicateMaterializerError",
    "MaterializationResultValidationError",
    "MaterializerRegistry",
    "MaterializerRegistryError",
    "ModuleMaterializationResult",
    "UnknownMaterializerModuleError",
    "validate_materializer_module",
)
