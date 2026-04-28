from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


@dataclass
class ParsedEmail:
    subject: str = ""
    body: str = ""


@dataclass(frozen=True)
class FieldBinding:
    value_key: str
    form_field: str
    selectors: tuple[str, ...]


@dataclass
class Ticket:
    CORE_FIELDS: ClassVar[tuple[str, ...]] = (
        "short_description",
        "description",
        "caller_name",
        "caller_email",
        "category",
        "subcategory",
    )

    short_description: str = ""
    description: str = ""
    caller_name: str = ""
    caller_email: str = ""
    category: str = ""
    subcategory: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Ticket":
        if data is None:
            return cls()
        if not hasattr(data, "items"):
            raise TypeError("Ticket JSON must be an object.")

        values = {field_name: "" for field_name in cls.CORE_FIELDS}
        extra_fields = {}
        for key, value in data.items():
            if key in values:
                values[key] = _stringify(value)
            else:
                extra_fields[key] = value

        return cls(**values, extra_fields=extra_fields)

    def to_dict(self) -> dict[str, Any]:
        data = {field_name: getattr(self, field_name) for field_name in self.CORE_FIELDS}
        data.update(self.extra_fields)
        return data
