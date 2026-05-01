from __future__ import annotations

from lakeshore_zonewriter.models import Zone, ZoneTable


FLOAT_FIELDS = (
    "upper_bound_k",
    "p",
    "i",
    "d",
    "manual_output_percent",
    "ramp_rate_k_per_min",
)

TEXT_FIELDS = ("heater_range", "control_input")


def diff_zone_tables(
    controller_table: ZoneTable, file_table: ZoneTable, tolerance: float = 1e-6
) -> list[str]:
    lines: list[str] = []
    if controller_table.output != file_table.output:
        lines.append(
            f"Output: controller={controller_table.output} file={file_table.output}"
        )

    controller_zones = controller_table.zone_by_number()
    file_zones = file_table.zone_by_number()

    for zone_number in range(1, 11):
        controller_zone = controller_zones.get(zone_number)
        file_zone = file_zones.get(zone_number)
        if controller_zone is None:
            lines.append(f"Zone {zone_number}: missing from controller data")
            continue
        if file_zone is None:
            lines.append(f"Zone {zone_number}: missing from file data")
            continue
        lines.extend(_diff_zone(controller_zone, file_zone, tolerance))

    return lines


def _diff_zone(controller_zone: Zone, file_zone: Zone, tolerance: float) -> list[str]:
    lines: list[str] = []
    for field in FLOAT_FIELDS:
        controller_value = getattr(controller_zone, field)
        file_value = getattr(file_zone, field)
        if abs(controller_value - file_value) > tolerance:
            lines.append(
                f"Zone {file_zone.zone} {field}: "
                f"controller={_format_value(controller_value)} "
                f"file={_format_value(file_value)}"
            )

    for field in TEXT_FIELDS:
        controller_value = getattr(controller_zone, field)
        file_value = getattr(file_zone, field)
        if controller_value != file_value:
            lines.append(
                f"Zone {file_zone.zone} {field}: "
                f"controller={controller_value} file={file_value}"
            )

    return lines


def _format_value(value: float) -> str:
    return format(value, ".12g")
