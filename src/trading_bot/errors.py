from __future__ import annotations


class FormValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        fields: tuple[str, ...] | list[str],
        display_field: str | None = None,
    ) -> None:
        super().__init__(message)
        normalized_fields = tuple(dict.fromkeys(str(field).strip() for field in fields if str(field).strip()))
        self.field_names = normalized_fields
        self.display_field = display_field or (normalized_fields[0] if normalized_fields else None)
