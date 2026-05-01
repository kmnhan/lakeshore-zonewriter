from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any

from lakeshore_zonewriter.models import Zone, ZoneTable, ZoneWriterError


class ZoneFileError(ZoneWriterError):
    """Raised when a TOML zone file cannot be read or written."""


def load_zone_table(path: str | Path) -> ZoneTable:
    zone_path = Path(path)
    try:
        with zone_path.open("rb") as file:
            data = tomllib.load(file)
    except OSError as exc:
        raise ZoneFileError(f"could not read {zone_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ZoneFileError(f"invalid TOML in {zone_path}: {exc}") from exc

    return ZoneTable.from_mapping(data)


def save_zone_table(table: ZoneTable, path: str | Path) -> None:
    table.raise_if_invalid()
    zone_path = Path(path)
    try:
        zone_path.write_text(dumps_zone_table(table), encoding="utf-8")
    except OSError as exc:
        raise ZoneFileError(f"could not write {zone_path}: {exc}") from exc


def dumps_zone_table(table: ZoneTable) -> str:
    table.raise_if_invalid()

    lines = [
        "# Lake Shore 336 zone table",
        "schema_version = 1",
        f"model = {_toml_string(table.model)}",
        f"output = {table.output}",
        "",
        "# zones columns:",
        "# zone, upper_bound_k, p, i, d, manual_output_percent, heater_range, control_input, ramp_rate_k_per_min",
        "zones = [",
    ]

    lines.extend(_dump_zone_rows(table.sorted_zones()))

    lines.append("]")

    return "\n".join(lines).rstrip() + "\n"


def _dump_zone_rows(zones: tuple[Zone, ...]) -> list[str]:
    rows = [_zone_row_values(zone) for zone in zones]
    widths = [
        max(len(row[column]) for row in rows)
        for column in range(len(rows[0]))
    ]
    return [_dump_zone_row(row, widths) for row in rows]


def _zone_row_values(zone: Zone) -> list[str]:
    return [
        str(zone.zone),
        _format_float(zone.upper_bound_k),
        _format_float(zone.p),
        _format_float(zone.i),
        _format_float(zone.d),
        _format_float(zone.manual_output_percent),
        _toml_string(zone.heater_range),
        _toml_string(zone.control_input),
        _format_float(zone.ramp_rate_k_per_min),
    ]


def _dump_zone_row(values: list[str], widths: list[int]) -> str:
    alignments = (">", ">", ">", ">", ">", ">", "<", "<", ">")
    padded_values = [
        f"{value:{alignment}{width}}"
        for value, width, alignment in zip(values, widths, alignments, strict=True)
    ]
    return f"  [{', '.join(padded_values)}],"


def _format_float(value: float) -> str:
    return format(value, ".12g")


def _toml_string(value: Any) -> str:
    return json.dumps(str(value))
