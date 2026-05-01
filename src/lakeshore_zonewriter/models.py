from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    field_validator,
    model_validator,
)


class ZoneWriterError(Exception):
    """Base exception for user-facing errors."""


class ValidationError(ZoneWriterError):
    """Raised when zone table data is invalid."""


HEATER_RANGE_CODES = {
    "off": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

HEATER_RANGE_NAMES = {value: key for key, value in HEATER_RANGE_CODES.items()}

HEATER_RANGE_ALIASES = {
    "0": "off",
    "off": "off",
    "1": "low",
    "low": "low",
    "2": "medium",
    "med": "medium",
    "medium": "medium",
    "3": "high",
    "high": "high",
}

CONTROL_INPUT_CODES = {
    "default": 0,
    "A": 1,
    "B": 2,
    "C": 3,
    "D": 4,
    "D2": 5,
    "D3": 6,
    "D4": 7,
    "D5": 8,
}

CONTROL_INPUT_NAMES = {value: key for key, value in CONTROL_INPUT_CODES.items()}

CONTROL_INPUT_ALIASES = {
    "0": "default",
    "default": "default",
    "none": "default",
    "previous": "default",
    "1": "A",
    "a": "A",
    "input a": "A",
    "2": "B",
    "b": "B",
    "input b": "B",
    "3": "C",
    "c": "C",
    "input c": "C",
    "4": "D",
    "d": "D",
    "input d": "D",
    "5": "D2",
    "d2": "D2",
    "input d2": "D2",
    "6": "D3",
    "d3": "D3",
    "input d3": "D3",
    "7": "D4",
    "d4": "D4",
    "input d4": "D4",
    "8": "D5",
    "d5": "D5",
    "input d5": "D5",
}

ZONE_ROW_FIELDS = (
    "zone",
    "upper_bound_k",
    "p",
    "i",
    "d",
    "manual_output_percent",
    "heater_range",
    "control_input",
    "ramp_rate_k_per_min",
)


def normalize_heater_range(value: Any) -> str:
    if isinstance(value, int):
        try:
            return HEATER_RANGE_NAMES[value]
        except KeyError as exc:
            raise ValidationError(f"invalid heater range code: {value}") from exc

    key = str(value).strip().lower()
    try:
        return HEATER_RANGE_ALIASES[key]
    except KeyError as exc:
        valid = ", ".join(HEATER_RANGE_CODES)
        raise ValidationError(f"invalid heater_range {value!r}; expected one of {valid}") from exc


def heater_range_code(value: Any) -> int:
    return HEATER_RANGE_CODES[normalize_heater_range(value)]


def normalize_control_input(value: Any) -> str:
    if isinstance(value, int):
        try:
            return CONTROL_INPUT_NAMES[value]
        except KeyError as exc:
            raise ValidationError(f"invalid control input code: {value}") from exc

    key = str(value).strip().lower()
    try:
        return CONTROL_INPUT_ALIASES[key]
    except KeyError as exc:
        valid = ", ".join(CONTROL_INPUT_CODES)
        raise ValidationError(
            f"invalid control_input {value!r}; expected one of {valid}"
        ) from exc


def control_input_code(value: Any) -> int:
    return CONTROL_INPUT_CODES[normalize_control_input(value)]


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    zone: int = Field(ge=1, le=10)
    upper_bound_k: float = Field(ge=0)
    p: float = Field(ge=0.1, le=1000)
    i: float = Field(ge=0.1, le=1000)
    d: float = Field(ge=0, le=200)
    manual_output_percent: float = Field(ge=0, le=100)
    heater_range: str
    control_input: str
    ramp_rate_k_per_min: float = Field(ge=0, le=100)

    @field_validator("heater_range", mode="before")
    @classmethod
    def _normalize_heater_range(cls, value: Any) -> str:
        try:
            return normalize_heater_range(value)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("control_input", mode="before")
    @classmethod
    def _normalize_control_input(cls, value: Any) -> str:
        try:
            return normalize_control_input(value)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> Zone:
        try:
            return cls.model_validate(mapping)
        except PydanticValidationError as exc:
            raise ValidationError(_format_pydantic_errors("zone entry", exc)) from exc

    def validate(self) -> list[str]:
        try:
            Zone.model_validate(self.model_dump())
        except PydanticValidationError as exc:
            return _pydantic_error_messages(exc)
        return []


class ZoneTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    output: int = Field(ge=1, le=2)
    zones: tuple[Zone, ...]
    schema_version: int = 1
    model: str = "Lake Shore 336"

    @field_validator("zones", mode="before")
    @classmethod
    def _normalize_zone_rows(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value

        normalized_zones: list[Any] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, list):
                if len(item) != len(ZONE_ROW_FIELDS):
                    raise ValueError(
                        f"zone row {index} must have {len(ZONE_ROW_FIELDS)} values"
                    )
                normalized_zones.append(dict(zip(ZONE_ROW_FIELDS, item, strict=True)))
                continue
            raise ValueError("zones must contain row arrays, not tables")
        return normalized_zones

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("schema_version must be 1")
        return value

    @model_validator(mode="after")
    def _validate_zone_set(self) -> ZoneTable:
        errors: list[str] = []
        if len(self.zones) != 10:
            errors.append("exactly 10 zones are required")

        zone_numbers = [zone.zone for zone in self.zones]
        seen: set[int] = set()
        duplicates: set[int] = set()
        for zone_number in zone_numbers:
            if zone_number in seen:
                duplicates.add(zone_number)
            seen.add(zone_number)

        expected = set(range(1, 11))
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        if duplicates:
            errors.append(
                "duplicate zones: "
                + ", ".join(str(zone_number) for zone_number in sorted(duplicates))
            )
        if missing:
            errors.append(
                "missing zones: "
                + ", ".join(str(zone_number) for zone_number in missing)
            )
        if extra:
            errors.append(
                "unexpected zones: "
                + ", ".join(str(zone_number) for zone_number in extra)
            )

        if errors:
            raise ValueError("; ".join(errors))
        return self

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> ZoneTable:
        try:
            return cls.model_validate(mapping)
        except PydanticValidationError as exc:
            raise ValidationError(_format_pydantic_errors("zone table", exc)) from exc

    def sorted_zones(self) -> tuple[Zone, ...]:
        return tuple(sorted(self.zones, key=lambda zone: zone.zone))

    def zone_by_number(self) -> dict[int, Zone]:
        return {zone.zone: zone for zone in self.zones}

    def validate(self) -> list[str]:
        try:
            ZoneTable.model_validate(self.model_dump())
        except PydanticValidationError as exc:
            return _pydantic_error_messages(exc)
        return []

    def raise_if_invalid(self) -> None:
        errors = self.validate()
        if errors:
            raise ValidationError("; ".join(errors))


def _format_pydantic_errors(context: str, exc: PydanticValidationError) -> str:
    messages = _pydantic_error_messages(exc)
    return f"{context} is invalid: {'; '.join(messages)}"


def _pydantic_error_messages(exc: PydanticValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"]
        if location:
            messages.append(f"{location}: {message}")
        else:
            messages.append(message)
    return messages
