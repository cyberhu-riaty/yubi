"""Keep protocol v21 names at the boundary while Python APIs use English.

Aliases preserve message identity for plugins loaded before the naming migration.
They do not create a second message class or change dataclass field metadata.
"""
from __future__ import annotations

from functools import wraps


def legacy_wire(class_name: str, fields: dict[str, str]):
    """Declare English attribute -> legacy wire field mappings explicitly."""
    def decorate(message_class):
        message_class.__wire_class_name__ = class_name
        message_class.__wire_fields__ = dict(fields)
        original_init = message_class.__init__
        aliases = {legacy: english for english, legacy in fields.items()}

        @wraps(original_init)
        def initialize(self, *args, **kwargs):
            mapped = {}
            for name, value in kwargs.items():
                attribute = aliases.get(name, name)
                if attribute in mapped:
                    raise TypeError(f"Multiple values for argument {attribute!r}")
                mapped[attribute] = value
            original_init(self, *args, **mapped)

        message_class.__init__ = initialize
        for legacy, english in aliases.items():
            if legacy == english:
                continue
            def get_value(self, attribute=english):
                return getattr(self, attribute)

            def set_value(self, value, attribute=english):
                setattr(self, attribute, value)

            setattr(message_class, legacy, property(get_value, set_value))
        return message_class
    return decorate


def wire_class_name(value) -> str:
    message_class = value if isinstance(value, type) else type(value)
    return getattr(message_class, "__wire_class_name__", message_class.__name__)


def wire_field_name(message_class, attribute: str) -> str:
    return getattr(message_class, "__wire_fields__", {}).get(attribute, attribute)


def resolve_wire_class(module, class_name: str):
    aliases = getattr(module, "WIRE_CLASS_ALIASES", {})
    attribute = next((name for name, legacy in aliases.items()
                      if legacy == class_name), class_name)
    return getattr(module, attribute)
