from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import sys
from typing import TextIO

import questionary

from lakeshore_zonewriter.controller import Controller, format_zone_command
from lakeshore_zonewriter.diff import diff_zone_tables
from lakeshore_zonewriter.models import ZoneTable, ZoneWriterError
from lakeshore_zonewriter.toml_io import load_zone_table, save_zone_table
from lakeshore_zonewriter.transport import list_resources, open_controller_transport


ControllerFactory = Callable[[str], Controller]
ResourceLister = Callable[[], tuple[str, ...]]


def main(
    argv: list[str] | None = None,
    *,
    controller_factory: ControllerFactory | None = None,
    resource_lister: ResourceLister | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    resource_lister = resource_lister or list_resources
    now = now or datetime.now

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    active_controller_factory = controller_factory
    if active_controller_factory is None:
        baud_rate = getattr(args, "baud_rate", None)

        def _default_factory(resource: str) -> Controller:
            return default_controller_factory(resource, baud_rate=baud_rate)

        active_controller_factory = _default_factory

    try:
        return args.func(
            args,
            controller_factory=active_controller_factory,
            resource_lister=resource_lister,
            stdin=stdin,
            stdout=stdout,
            now=now,
        )
    except ZoneWriterError as exc:
        print(f"error: {exc}", file=stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted", file=stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lakeshore-zonewriter",
        description=(
            "Read, validate, compare, and write Lake Shore 336 zone tables. "
            "Hardware commands use a fixed 50 ms request interval and 10 second timeout."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list-resources",
        help="Show PyVISA resources the controller can be opened from.",
        description=(
            "List the PyVISA resource names visible on this machine. Use one of these "
            "values with --resource, or omit --resource on hardware commands to choose "
            "from the same list interactively."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    list_parser.set_defaults(func=cmd_list_resources)

    export_parser = subparsers.add_parser(
        "export",
        help="Read one output's 10 zones from the controller and write a TOML file.",
        description=(
            "Read all 10 zone-table rows for one Lake Shore 336 output and write them "
            "to an editable TOML file. If --resource is omitted, choose a PyVISA "
            "resource from an interactive list. If --output is omitted, enter Output "
            "1 or 2 when prompted. The exported TOML records the selected output."
        ),
        epilog=(
            "Examples:\n"
            "  lakeshore-zonewriter export --file zones.toml\n"
            "  lakeshore-zonewriter export --resource ASRL3::INSTR --output 1 --file zones.toml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(export_parser)
    export_parser.add_argument(
        "--file",
        required=True,
        type=Path,
        help="TOML file to create or replace with the controller's zone table.",
    )
    export_parser.add_argument(
        "--output",
        type=int,
        choices=(1, 2),
        help="Controller output to read. If omitted, prompt for Output 1 or 2.",
    )
    export_parser.set_defaults(func=cmd_export)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Check a TOML zone file without connecting to hardware.",
        description=(
            "Parse and validate a zone TOML file. This checks schema_version, output, "
            "the presence of exactly 10 zones, zone numbering, numeric ranges, and "
            "heater/input enum names. It does not connect to the controller."
        ),
        epilog="Example:\n  lakeshore-zonewriter validate --file zones.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    validate_parser.add_argument(
        "--file", required=True, type=Path, help="Zone TOML file to validate."
    )
    validate_parser.set_defaults(func=cmd_validate)

    diff_parser = subparsers.add_parser(
        "diff",
        help="Compare the controller to the output declared in a TOML file.",
        description=(
            "Load a TOML zone file, use its top-level output value, read that output's "
            "current 10 zones from the controller, and print field-level differences. "
            "Returns exit code 0 when there are no differences and 1 when differences "
            "are found."
        ),
        epilog=(
            "Examples:\n"
            "  lakeshore-zonewriter diff --file zones.toml\n"
            "  lakeshore-zonewriter diff --resource ASRL3::INSTR --file zones.toml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(diff_parser)
    diff_parser.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Zone TOML file whose output and zone values are compared.",
    )
    diff_parser.set_defaults(func=cmd_diff)

    write_parser = subparsers.add_parser(
        "write",
        help="Back up, confirm, write, and verify zones from a TOML file.",
        description=(
            "Write the 10 zones in a TOML file to the file's top-level output. The "
            "write command does not accept --output and will not override the file. "
            "Before writing, it reads the current controller zones for that output, "
            "saves a timestamped backup TOML, prints the diff, and asks for "
            "confirmation unless --yes is used. After writing, it re-reads the "
            "controller and fails if verification differs."
        ),
        epilog=(
            "Examples:\n"
            "  lakeshore-zonewriter write --file zones.toml --dry-run\n"
            "  lakeshore-zonewriter write --resource ASRL3::INSTR --file zones.toml\n"
            "  lakeshore-zonewriter write --resource ASRL3::INSTR --file zones.toml --yes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(write_parser)
    write_parser.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Zone TOML file to validate and write. Its output field is authoritative.",
    )
    write_parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Directory for the pre-write backup. Defaults to the zone file directory.",
    )
    write_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the diff and exact ZONE commands, but do not back up or write.",
    )
    write_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive write confirmation.",
    )
    write_parser.set_defaults(func=cmd_write)
    return parser


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--resource",
        help=(
            "PyVISA resource name for the controller. If omitted, choose from "
            "detected resources interactively."
        ),
    )
    parser.add_argument(
        "--baud-rate",
        type=int,
        help=(
            "Serial baud rate for ASRL resources. Defaults to 57600 for the "
            "Lake Shore 336 USB virtual serial port."
        ),
    )


def default_controller_factory(resource: str, *, baud_rate: int | None = None) -> Controller:
    transport = open_controller_transport(resource, baud_rate=baud_rate)
    return Controller(transport)


def cmd_list_resources(
    args: argparse.Namespace,
    *,
    resource_lister: ResourceLister,
    stdout: TextIO,
    **_: object,
) -> int:
    resources = resource_lister()
    if not resources:
        print("No VISA resources found.", file=stdout)
        return 0
    for resource in resources:
        print(resource, file=stdout)
    return 0


def cmd_export(
    args: argparse.Namespace,
    *,
    controller_factory: ControllerFactory,
    resource_lister: ResourceLister,
    stdin: TextIO,
    stdout: TextIO,
    **_: object,
) -> int:
    resource = select_resource(
        args.resource, resource_lister=resource_lister, stdin=stdin, stdout=stdout
    )
    output = select_output(args.output, stdin=stdin, stdout=stdout)
    controller = controller_factory(resource)
    try:
        table = controller.read_zone_table(output)
    finally:
        controller.close()

    save_zone_table(table, args.file)
    print(f"Exported Output {output} zones to {args.file}", file=stdout)
    return 0


def cmd_validate(
    args: argparse.Namespace,
    *,
    stdout: TextIO,
    **_: object,
) -> int:
    table = load_zone_table(args.file)
    print(
        f"Valid zone file: {args.file} (Output {table.output}, {len(table.zones)} zones)",
        file=stdout,
    )
    return 0


def cmd_diff(
    args: argparse.Namespace,
    *,
    controller_factory: ControllerFactory,
    resource_lister: ResourceLister,
    stdin: TextIO,
    stdout: TextIO,
    **_: object,
) -> int:
    file_table = load_zone_table(args.file)
    resource = select_resource(
        args.resource, resource_lister=resource_lister, stdin=stdin, stdout=stdout
    )
    controller_table = read_current_table(
        resource, controller_factory, file_table.output
    )
    differences = diff_zone_tables(controller_table, file_table)
    print_diff(differences, stdout=stdout)
    return 1 if differences else 0


def cmd_write(
    args: argparse.Namespace,
    *,
    controller_factory: ControllerFactory,
    resource_lister: ResourceLister,
    stdin: TextIO,
    stdout: TextIO,
    now: Callable[[], datetime],
    **_: object,
) -> int:
    file_table = load_zone_table(args.file)
    resource = select_resource(
        args.resource, resource_lister=resource_lister, stdin=stdin, stdout=stdout
    )
    controller_table = read_current_table(
        resource, controller_factory, file_table.output
    )
    differences = diff_zone_tables(controller_table, file_table)

    if args.dry_run:
        print_diff(differences, stdout=stdout)
        print_commands(file_table, stdout=stdout)
        return 0

    if not differences:
        print(
            f"Controller Output {file_table.output} already matches {args.file}; no writes needed.",
            file=stdout,
        )
        return 0

    backup_path = backup_file_path(args.file, args.backup_dir, file_table.output, now())
    save_zone_table(controller_table, backup_path)
    print(f"Backed up current Output {file_table.output} zones to {backup_path}", file=stdout)
    print_diff(differences, stdout=stdout)

    if not args.yes and not confirm_write(file_table, args.file, stdin=stdin, stdout=stdout):
        print("Aborted; no zones written.", file=stdout)
        return 1

    controller = controller_factory(resource)
    try:
        controller.write_zone_table(file_table)
        verified_table = controller.read_zone_table(file_table.output)
    finally:
        controller.close()

    verification_differences = diff_zone_tables(verified_table, file_table)
    if verification_differences:
        details = "\n".join(verification_differences)
        raise ZoneWriterError(f"verification failed after write:\n{details}")

    print(
        f"Wrote and verified Output {file_table.output} zones from {args.file}",
        file=stdout,
    )
    return 0


def select_output(output: int | None, *, stdin: TextIO, stdout: TextIO) -> int:
    if output is not None:
        return output

    while True:
        stdout.write("Select output to export (1 or 2): ")
        stdout.flush()
        answer = stdin.readline()
        if answer == "":
            raise ZoneWriterError("output selection is required")
        answer = answer.strip()
        if answer in {"1", "2"}:
            return int(answer)
        print("Please enter 1 or 2.", file=stdout)


def select_resource(
    resource: str | None,
    *,
    resource_lister: ResourceLister,
    stdin: TextIO,
    stdout: TextIO,
) -> str:
    if resource:
        return resource

    resources = resource_lister()
    if not resources:
        raise ZoneWriterError(
            "no VISA resources found; connect the controller or pass --resource"
        )

    if stdin.isatty() and stdout.isatty():
        selected_resource = questionary.select(
            "Select VISA resource:",
            choices=list(resources),
        ).ask()
        if selected_resource:
            return str(selected_resource)
        raise ZoneWriterError("resource selection is required")

    print("Select VISA resource:", file=stdout)
    for index, resource_name in enumerate(resources, start=1):
        print(f"  {index}) {resource_name}", file=stdout)

    while True:
        stdout.write(f"Resource [1-{len(resources)}]: ")
        stdout.flush()
        answer = stdin.readline()
        if answer == "":
            raise ZoneWriterError("resource selection is required")
        answer = answer.strip()
        try:
            selected = int(answer)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(resources):
            return resources[selected - 1]
        print(f"Please enter a number from 1 to {len(resources)}.", file=stdout)


def read_current_table(
    resource: str,
    controller_factory: ControllerFactory,
    output: int,
) -> ZoneTable:
    controller = controller_factory(resource)
    try:
        return controller.read_zone_table(output)
    finally:
        controller.close()


def print_diff(differences: list[str], *, stdout: TextIO) -> None:
    if not differences:
        print("No differences.", file=stdout)
        return
    print("Differences (controller -> file):", file=stdout)
    for difference in differences:
        print(f"  - {difference}", file=stdout)


def print_commands(table: ZoneTable, *, stdout: TextIO) -> None:
    print("ZONE commands:", file=stdout)
    for zone in table.sorted_zones():
        print(format_zone_command(table.output, zone), file=stdout)


def backup_file_path(
    source_file: Path, backup_dir: Path | None, output: int, timestamp: datetime
) -> Path:
    directory = backup_dir or source_file.parent
    name = (
        f"{source_file.stem}.output{output}.backup."
        f"{timestamp.strftime('%Y%m%d-%H%M%S')}.toml"
    )
    return directory / name


def confirm_write(
    table: ZoneTable, source_file: Path, *, stdin: TextIO, stdout: TextIO
) -> bool:
    stdout.write(
        f"Write zones from {source_file} to controller Output {table.output}? [y/N]: "
    )
    stdout.flush()
    answer = stdin.readline()
    return answer.strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
