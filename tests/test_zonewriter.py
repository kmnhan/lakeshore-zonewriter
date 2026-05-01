from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stderr
import unittest
from unittest.mock import patch

from pyvisa import constants

from lakeshore_zonewriter.cli import main
from lakeshore_zonewriter.controller import format_zone_command, parse_zone_response
from lakeshore_zonewriter.models import ValidationError, Zone, ZoneTable
from lakeshore_zonewriter.toml_io import dumps_zone_table, load_zone_table, save_zone_table
from lakeshore_zonewriter.transport import open_controller_transport


def make_zone(zone: int, *, p: float = 10.0) -> Zone:
    return Zone(
        zone=zone,
        upper_bound_k=float(zone * 10),
        p=p,
        i=20.0,
        d=0.0,
        manual_output_percent=0.0,
        heater_range="medium",
        control_input="B",
        ramp_rate_k_per_min=1.0,
    )


def make_table(output: int, *, p: float = 10.0) -> ZoneTable:
    return ZoneTable(output=output, zones=tuple(make_zone(zone, p=p) for zone in range(1, 11)))


class FakeController:
    def __init__(self, state: dict[int, ZoneTable]):
        self.state = state
        self.closed = False
        self.written_tables: list[ZoneTable] = []

    def read_zone_table(self, output: int) -> ZoneTable:
        return self.state[output]

    def write_zone_table(self, table: ZoneTable) -> None:
        self.written_tables.append(table)
        self.state[table.output] = table

    def close(self) -> None:
        self.closed = True


class FakeControllerFactory:
    def __init__(self, state: dict[int, ZoneTable]):
        self.state = state
        self.instances: list[FakeController] = []
        self.calls: list[str] = []

    def __call__(self, resource: str) -> FakeController:
        self.calls.append(resource)
        self.instances.append(FakeController(self.state))
        return self.instances[-1]


class ZoneModelTests(unittest.TestCase):
    def test_zone_table_requires_all_ten_zones(self) -> None:
        with self.assertRaises(ValidationError) as error:
            ZoneTable.from_mapping(
                {
                    "schema_version": 1,
                    "model": "Lake Shore 336",
                    "output": 1,
                    "zones": [
                        [
                            1,
                            10.0,
                            10.0,
                            20.0,
                            0.0,
                            0.0,
                            "medium",
                            "B",
                            1.0,
                        ]
                    ],
                }
            )
        self.assertIn("exactly 10 zones", str(error.exception))

    def test_zone_normalizes_enum_aliases(self) -> None:
        zone = Zone(
            zone=1,
            upper_bound_k=25,
            p=10,
            i=20,
            d=0,
            manual_output_percent=0,
            heater_range="med",
            control_input="input a",
            ramp_rate_k_per_min=10,
        )
        self.assertEqual(zone.heater_range, "medium")
        self.assertEqual(zone.control_input, "A")


class TomlTests(unittest.TestCase):
    def test_toml_round_trip(self) -> None:
        table = make_table(2)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.toml"
            save_zone_table(table, path)
            loaded = load_zone_table(path)
        self.assertEqual(loaded, table)

    def test_toml_dump_is_editable(self) -> None:
        dumped = dumps_zone_table(make_table(1))
        self.assertIn("schema_version = 1", dumped)
        self.assertIn("output = 1", dumped)
        self.assertIn("# zone, upper_bound_k, p, i, d", dumped)
        self.assertIn('zones = [', dumped)
        self.assertIn('[ 1,  10, 10, 20, 0, 0, "medium", "B", 1],', dumped)
        self.assertIn('[10, 100, 10, 20, 0, 0, "medium", "B", 1],', dumped)

    def test_example_file_uses_canonical_aligned_dump(self) -> None:
        path = Path("examples/zones-output1.toml")
        table = load_zone_table(path)
        self.assertEqual(path.read_text(encoding="utf-8"), dumps_zone_table(table))

    def test_old_block_style_toml_is_rejected(self) -> None:
        lines = [
            "schema_version = 1",
            'model = "Lake Shore 336"',
            "output = 1",
            "",
        ]
        for zone in range(1, 11):
            lines.extend(
                [
                    "[[zones]]",
                    f"zone = {zone}",
                    f"upper_bound_k = {float(zone * 10)}",
                    "p = 10.0",
                    "i = 20.0",
                    "d = 0.0",
                    "manual_output_percent = 0.0",
                    'heater_range = "medium"',
                    'control_input = "B"',
                    "ramp_rate_k_per_min = 1.0",
                    "",
                ]
            )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.toml"
            path.write_text("\n".join(lines), encoding="utf-8")
            with self.assertRaises(ValidationError) as error:
                load_zone_table(path)

        self.assertIn("row arrays", str(error.exception))


class ControllerCommandTests(unittest.TestCase):
    def test_parse_zone_response(self) -> None:
        zone = parse_zone_response(1, "25.0,10,20,0,0,2,2,10\r\n")
        self.assertEqual(zone.zone, 1)
        self.assertEqual(zone.upper_bound_k, 25.0)
        self.assertEqual(zone.heater_range, "medium")
        self.assertEqual(zone.control_input, "B")

    def test_format_zone_command(self) -> None:
        command = format_zone_command(1, make_zone(1))
        self.assertEqual(command, "ZONE 1,1,10,10,20,0,0,2,2,1")


class TransportTests(unittest.TestCase):
    def test_controller_transport_uses_336_serial_defaults(self) -> None:
        class FakeResourceManager:
            def __init__(self) -> None:
                self.open_calls: list[tuple[str, dict[str, object]]] = []

            def open_resource(self, resource: str, **kwargs: object) -> object:
                self.open_calls.append((resource, kwargs))
                return object()

        manager = FakeResourceManager()
        with patch("lakeshore_zonewriter.transport.pyvisa.ResourceManager", return_value=manager):
            handler = open_controller_transport("ASRL3::INSTR")

        self.assertEqual(handler.interval_ms, 50)
        self.assertEqual(
            manager.open_calls,
            [
                (
                    "ASRL3::INSTR",
                    {
                        "timeout": 10_000,
                        "read_termination": "\r\n",
                        "write_termination": "\r\n",
                        "baud_rate": 57_600,
                        "data_bits": 7,
                        "parity": constants.Parity.odd,
                        "stop_bits": constants.StopBits.one,
                        "flow_control": constants.ControlFlow.none,
                    },
                )
            ],
        )

    def test_controller_transport_allows_baud_rate_override(self) -> None:
        class FakeResourceManager:
            def __init__(self) -> None:
                self.open_calls: list[tuple[str, dict[str, object]]] = []

            def open_resource(self, resource: str, **kwargs: object) -> object:
                self.open_calls.append((resource, kwargs))
                return object()

        manager = FakeResourceManager()
        with patch("lakeshore_zonewriter.transport.pyvisa.ResourceManager", return_value=manager):
            open_controller_transport("ASRL3::INSTR", baud_rate=9600)

        self.assertEqual(manager.open_calls[0][1]["baud_rate"], 9600)

    def test_controller_transport_skips_serial_settings_for_non_serial_resource(self) -> None:
        class FakeResourceManager:
            def __init__(self) -> None:
                self.open_calls: list[tuple[str, dict[str, object]]] = []

            def open_resource(self, resource: str, **kwargs: object) -> object:
                self.open_calls.append((resource, kwargs))
                return object()

        manager = FakeResourceManager()
        with patch("lakeshore_zonewriter.transport.pyvisa.ResourceManager", return_value=manager):
            open_controller_transport("TCPIP0::192.0.2.10::7777::SOCKET")

        self.assertEqual(
            manager.open_calls,
            [
                (
                    "TCPIP0::192.0.2.10::7777::SOCKET",
                    {
                        "timeout": 10_000,
                        "read_termination": "\r\n",
                        "write_termination": "\r\n",
                    },
                )
            ],
        )


class CliTests(unittest.TestCase):
    def test_export_prompts_for_output_when_omitted(self) -> None:
        state = {1: make_table(1), 2: make_table(2)}
        factory = FakeControllerFactory(state)
        stdout = StringIO()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "exported.toml"
            code = main(
                ["export", "--resource", "ASRL3::INSTR", "--file", str(path)],
                controller_factory=factory,
                stdin=StringIO("2\n"),
                stdout=stdout,
            )
            exported = load_zone_table(path)

        self.assertEqual(code, 0)
        self.assertEqual(exported.output, 2)
        self.assertIn("Select output", stdout.getvalue())

    def test_export_prompts_for_resource_when_omitted(self) -> None:
        state = {1: make_table(1), 2: make_table(2)}
        factory = FakeControllerFactory(state)
        stdout = StringIO()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "exported.toml"
            code = main(
                ["export", "--output", "1", "--file", str(path)],
                controller_factory=factory,
                resource_lister=lambda: ("ASRL1::INSTR", "ASRL3::INSTR"),
                stdin=StringIO("2\n"),
                stdout=stdout,
            )
            exported = load_zone_table(path)

        self.assertEqual(code, 0)
        self.assertEqual(exported.output, 1)
        self.assertEqual(factory.calls[0], "ASRL3::INSTR")
        self.assertIn("Select VISA resource", stdout.getvalue())

    def test_export_passes_baud_rate_to_default_controller_factory(self) -> None:
        class FakeTransport:
            def query(self, command: str) -> str:
                self.command = command
                return "10,10,20,0,0,2,2,1\r\n"

            def close(self) -> None:
                self.closed = True

        stdout = StringIO()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "exported.toml"
            with patch(
                "lakeshore_zonewriter.cli.open_controller_transport",
                return_value=FakeTransport(),
            ) as open_transport:
                code = main(
                    [
                        "export",
                        "--resource",
                        "ASRL3::INSTR",
                        "--baud-rate",
                        "9600",
                        "--output",
                        "1",
                        "--file",
                        str(path),
                    ],
                    stdout=stdout,
                )

        self.assertEqual(code, 0)
        open_transport.assert_called_once_with("ASRL3::INSTR", baud_rate=9600)

    def test_missing_resource_errors_when_no_resources_detected(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "exported.toml"
            code = main(
                ["export", "--output", "1", "--file", str(path)],
                controller_factory=FakeControllerFactory({1: make_table(1), 2: make_table(2)}),
                resource_lister=lambda: (),
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 1)
        self.assertIn("no VISA resources found", stderr.getvalue())

    def test_write_uses_output_from_zone_file(self) -> None:
        original_output_1 = make_table(1, p=10)
        original_output_2 = make_table(2, p=10)
        desired_output_2 = make_table(2, p=11)
        state = {1: original_output_1, 2: original_output_2}
        factory = FakeControllerFactory(state)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.toml"
            save_zone_table(desired_output_2, path)
            stdout = StringIO()
            code = main(
                [
                    "write",
                    "--resource",
                    "ASRL3::INSTR",
                    "--file",
                    str(path),
                    "--yes",
                ],
                controller_factory=factory,
                stdout=stdout,
                now=lambda: datetime(2026, 5, 1, 12, 0, 0),
            )
            backup = Path(tmp) / "zones.output2.backup.20260501-120000.toml"
            backed_up = load_zone_table(backup)

        self.assertEqual(code, 0)
        self.assertEqual(state[1], original_output_1)
        self.assertEqual(state[2], desired_output_2)
        self.assertEqual(backed_up, original_output_2)
        self.assertIn("Output 2", stdout.getvalue())

    def test_write_prompts_for_resource_but_uses_file_output(self) -> None:
        original_output_1 = make_table(1, p=10)
        original_output_2 = make_table(2, p=10)
        desired_output_2 = make_table(2, p=11)
        state = {1: original_output_1, 2: original_output_2}
        factory = FakeControllerFactory(state)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.toml"
            save_zone_table(desired_output_2, path)
            stdout = StringIO()
            code = main(
                [
                    "write",
                    "--file",
                    str(path),
                    "--yes",
                ],
                controller_factory=factory,
                resource_lister=lambda: ("ASRL1::INSTR", "ASRL3::INSTR"),
                stdin=StringIO("2\n"),
                stdout=stdout,
                now=lambda: datetime(2026, 5, 1, 12, 0, 0),
            )

        self.assertEqual(code, 0)
        self.assertEqual(factory.calls[0], "ASRL3::INSTR")
        self.assertEqual(state[1], original_output_1)
        self.assertEqual(state[2], desired_output_2)

    def test_write_rejects_output_override(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.toml"
            save_zone_table(make_table(2), path)
            with redirect_stderr(StringIO()):
                code = main(
                    [
                        "write",
                        "--resource",
                        "ASRL3::INSTR",
                        "--file",
                        str(path),
                        "--output",
                        "1",
                    ],
                    controller_factory=FakeControllerFactory(
                        {1: make_table(1), 2: make_table(2)}
                    ),
                )
        self.assertEqual(code, 2)

    def test_dry_run_does_not_write(self) -> None:
        original = make_table(1, p=10)
        desired = make_table(1, p=12)
        state = {1: original, 2: make_table(2)}
        factory = FakeControllerFactory(state)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.toml"
            save_zone_table(desired, path)
            stdout = StringIO()
            code = main(
                [
                    "write",
                    "--resource",
                    "ASRL3::INSTR",
                    "--file",
                    str(path),
                    "--dry-run",
                ],
                controller_factory=factory,
                stdout=stdout,
            )

        self.assertEqual(code, 0)
        self.assertEqual(state[1], original)
        self.assertIn("ZONE commands:", stdout.getvalue())

    def test_diff_returns_one_when_different(self) -> None:
        state = {1: make_table(1, p=10), 2: make_table(2)}
        factory = FakeControllerFactory(state)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.toml"
            save_zone_table(make_table(1, p=13), path)
            stdout = StringIO()
            code = main(
                ["diff", "--resource", "ASRL3::INSTR", "--file", str(path)],
                controller_factory=factory,
                stdout=stdout,
            )

        self.assertEqual(code, 1)
        self.assertIn("Differences", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
