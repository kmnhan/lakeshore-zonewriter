# lakeshore-zonewriter

`lakeshore-zonewriter` reads and writes Lake Shore 336 controller zone tables using
PyVISA. Zone files are TOML so they can be reviewed and edited by hand.

The CLI uses the controller commands documented for the Model 336:

- Query: `ZONE? <output>,<zone>`
- Write: `ZONE <output>,<zone>,<upper bound>,<P>,<I>,<D>,<manual output>,<range>,<input>,<rate>`

The tool writes zone table data only. It does not change the controller output mode.

Controller connections use a fixed 50 ms interval between requests and a 10 second
PyVISA timeout.

## Install

```bash
uv sync
```

## List VISA Resources

```bash
uv run lakeshore-zonewriter list-resources
```

## Export Zones

Export prompts for Output 1 or 2 if `--output` is omitted.

```bash
uv run lakeshore-zonewriter export --file zones.toml
```

If `--resource` is omitted, the CLI opens an interactive terminal dropdown of
detected PyVISA resources. In non-interactive shells it falls back to a numbered
selection prompt. For scripts, pass both values explicitly:

```bash
uv run lakeshore-zonewriter export --resource ASRL3::INSTR --output 1 --file zones.toml
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
uv run lakeshore-zonewriter validate --file zones.toml
```

Compare the controller to the file's `output`:

```bash
uv run lakeshore-zonewriter diff --file zones.toml
```

Preview writes without changing the controller:

```bash
uv run lakeshore-zonewriter write --file zones.toml --dry-run
```

Write zones from the file:

```bash
uv run lakeshore-zonewriter write --file zones.toml
```

Before writing, the CLI exports a timestamped backup of the current controller zones
for the file's output, prints the diff, and asks for confirmation. Use `--yes` for
non-interactive runs.

## Test

```bash
uv run python -m unittest discover -s tests
```
