# lakeshore-zonewriter

[![Tests][tests-badge]][tests]
[![PyPI][pypi-badge]][pypi]
[![Python][python-badge]][pypi]
[![License][license-badge]][license]
[![uv][uv-badge]][uv]

`lakeshore-zonewriter` reads and writes Lake Shore 336 controller zone tables using
PyVISA. Zone files are TOML so they can be reviewed and edited by hand.

The CLI uses the controller commands documented for the Model 336:

- Query: `ZONE? <output>,<zone>`
- Write: `ZONE <output>,<zone>,<upper bound>,<P>,<I>,<D>,<manual output>,<range>,<input>,<rate>`

The tool writes zone table data only. It does not change the controller output mode.

Controller connections use a fixed 50 ms interval between requests and a 10 second
PyVISA timeout. ASRL resources, including the Model 336 USB virtual serial port,
default to 57,600 baud, 7 data bits, odd parity, 1 stop bit, no flow control, and
CR/LF message termination.

## Install `lakeshore-zonewriter` as a CLI Tool using [uv](https://docs.astral.sh/uv/)

```bash
uv tool install lakeshore-zonewriter
```

After installation, run the installed console script directly. For one-off use
without installing, use `uvx lakeshore-zonewriter`.

Check the installed CLI:

```bash
lakeshore-zonewriter --help
```

## List VISA Resources

```bash
lakeshore-zonewriter list-resources
```

## Export Zones

Export prompts for Output 1 or 2 if `--output` is omitted.

```bash
lakeshore-zonewriter export --file zones.toml
```

If `--resource` is omitted, the CLI opens an interactive terminal dropdown of
detected PyVISA resources. In non-interactive shells it falls back to a numbered
selection prompt. For scripts, pass both values explicitly:

```bash
lakeshore-zonewriter export --resource ASRL3::INSTR --output 1 --file zones.toml
```

If a controller is configured differently, override the serial baud rate:

```bash
lakeshore-zonewriter export --resource ASRL3::INSTR --baud-rate 9600 --output 1 --file zones.toml
```

## Edit the TOML File

See [examples/zones-output1.toml](examples/zones-output1.toml) for a sample file.

Each file must contain exactly 10 zone rows. The top-level `output` field is the write
target. The `write` command does not accept `--output`, so it cannot override the file.
The `zones` value must use the compact row format shown in the example; `[[zones]]`
table-style entries are not supported.

Valid `heater_range` values are `off`, `low`, `medium`, and `high`. Valid
`control_input` values are `default`, `A`, `B`, `C`, `D`, `D2`, `D3`, `D4`, and `D5`
(`D2`-`D5` only for Model 336 with the 3062 option card).

## Validate, Diff, and Write

Validate without connecting to hardware:

```bash
lakeshore-zonewriter validate --file zones.toml
```

Compare the controller to the file's `output`:

```bash
lakeshore-zonewriter diff --file zones.toml
```

Preview writes without changing the controller:

```bash
lakeshore-zonewriter write --file zones.toml --dry-run
```

Write zones from the file:

```bash
lakeshore-zonewriter write --file zones.toml
```

Before writing, the CLI exports a timestamped backup of the current controller zones
for the file's output, prints the diff, and asks for confirmation. Use `--yes` for
non-interactive runs.

## Test

From a source checkout, install the project environment and run tests:

```bash
uv sync
```

```bash
uv run python -m unittest discover -s tests
```

## Release

Use `pyproject.toml` as the source of truth for the package version. Keep `CHANGELOG.md`
updated by moving notable entries from `Unreleased` into the new version section.

Release checklist:

1. Choose the next semantic version.
2. Update `CHANGELOG.md`, including the release date.
3. Bump `version` in `pyproject.toml`.
4. Run tests:

   ```bash
   uv run python -m unittest discover -s tests
   ```

5. Build the package:

   ```bash
   uv build
   ```

6. Commit the release and create a tag that matches the package version:

   ```bash
   git commit -am "Release X.Y.Z"
   git tag vX.Y.Z
   ```

7. Push the commit and tag:

   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```

Pushing a `v*` tag runs the release workflow, which tests, builds, publishes to
PyPI through trusted publishing, and creates a GitHub Release using the matching
`CHANGELOG.md` section with the built distributions attached.

PyPI publishing requires a trusted publisher for this repository, workflow
`release.yml`, and environment `pypi`.

## License

Apache-2.0. See [LICENSE](LICENSE).

[tests-badge]: https://img.shields.io/github/actions/workflow/status/kmnhan/lakeshore-zonewriter/tests.yml?branch=main&label=tests&style=flat-square
[tests]: https://github.com/kmnhan/lakeshore-zonewriter/actions/workflows/tests.yml
[pypi-badge]: https://img.shields.io/pypi/v/lakeshore-zonewriter?style=flat-square
[pypi]: https://pypi.org/project/lakeshore-zonewriter/
[python-badge]: https://img.shields.io/pypi/pyversions/lakeshore-zonewriter?style=flat-square
[license-badge]: https://img.shields.io/pypi/l/lakeshore-zonewriter?style=flat-square
[license]: LICENSE
[uv-badge]: https://img.shields.io/badge/packaged%20with-uv-654ff0?style=flat-square
[uv]: https://docs.astral.sh/uv/
