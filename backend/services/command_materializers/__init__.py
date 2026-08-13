"""Production registry for Command domain materializers."""

from services.command_materializers.base import (
    CommandDomainMaterializer,
    DuplicateMaterializerError,
    MaterializationResultValidationError,
    MaterializerRegistry,
    MaterializerRegistryError,
    ModuleMaterializationResult,
    UnknownMaterializerModuleError,
    validate_materializer_module,
)


def default_materializer_registry() -> MaterializerRegistry:
    from services.command_contact_materializer import ContactMaterializer

    registry = MaterializerRegistry()
    registry.register(ContactMaterializer())
    return registry


def __getattr__(name: str):
    if name == "ContactMaterializer":
        from services.command_contact_materializer import ContactMaterializer

        return ContactMaterializer
    raise AttributeError(name)


__all__ = (
    "CommandDomainMaterializer",
    "ContactMaterializer",
    "DuplicateMaterializerError",
    "MaterializationResultValidationError",
    "MaterializerRegistry",
    "MaterializerRegistryError",
    "ModuleMaterializationResult",
    "UnknownMaterializerModuleError",
    "default_materializer_registry",
    "validate_materializer_module",
)
