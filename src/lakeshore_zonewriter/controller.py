from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError as PydanticValidationError

from lakeshore_zonewriter.models import (
    ValidationError,
    Zone,
    ZoneTable,
    ZoneWriterError,
    control_input_code,
    normalize_control_input,
    normalize_heater_range,
    heater_range_code,
)


class Transport(Protocol):
    def query(self, message: str) -> str:
        ...

    def write(self, message: str) -> object:
        ...


class ControllerError(ZoneWriterError):
    """Raised when controller communication or response parsing fails."""


class Controller:
    def __init__(self, transport: Transport):
        self.transport = transport

    def read_zone_table(self, output: int) -> ZoneTable:
        zones = []
        for zone_number in range(1, 11):
            response = self.transport.query(f"ZONE? {output},{zone_number}")
            zones.append(parse_zone_response(zone_number, response))
        return ZoneTable(output=output, zones=tuple(zones))

    def write_zone_table(self, table: ZoneTable) -> None:
        table.raise_if_invalid()
        for zone in table.sorted_zones():
            self.transport.write(format_zone_command(table.output, zone))

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close is not None:
            close()


def parse_zone_response(zone_number: int, response: str) -> Zone:
    parts = [part.strip() for part in response.strip().split(",")]
    if len(parts) != 8:
        raise ControllerError(
            f"ZONE? response for zone {zone_number} returned {len(parts)} fields; expected 8"
        )

    try:
        heater_range = normalize_heater_range(int(parts[5]))
        control_input = normalize_control_input(int(parts[6]))
        return Zone(
            zone=zone_number,
            upper_bound_k=float(parts[0]),
            p=float(parts[1]),
            i=float(parts[2]),
            d=float(parts[3]),
            manual_output_percent=float(parts[4]),
            heater_range=heater_range,
            control_input=control_input,
            ramp_rate_k_per_min=float(parts[7]),
        )
    except (ValueError, ValidationError, PydanticValidationError) as exc:
        raise ControllerError(
            f"could not parse ZONE? response for zone {zone_number}: {response!r}"
        ) from exc


def format_zone_command(output: int, zone: Zone) -> str:
    return (
        "ZONE "
        f"{output},"
        f"{zone.zone},"
        f"{_format_number(zone.upper_bound_k)},"
        f"{_format_number(zone.p)},"
        f"{_format_number(zone.i)},"
        f"{_format_number(zone.d)},"
        f"{_format_number(zone.manual_output_percent)},"
        f"{heater_range_code(zone.heater_range)},"
        f"{control_input_code(zone.control_input)},"
        f"{_format_number(zone.ramp_rate_k_per_min)}"
    )


def _format_number(value: float) -> str:
    return format(value, ".12g")
