# Changelog

Notable changes to this project are documented here.

This project follows semantic versioning while the public CLI and TOML schema settle.

## v0.1.2 - 2026-05-01

### Added

- Configure Model 336 ASRL connections with the USB virtual serial defaults and
  add `--baud-rate` for serial overrides.

## v0.1.1 - 2026-05-01

### Fixed

- Allow 0 in ramp rate column

## v0.1.0 - 2026-05-01

### Added

- Initial CLI for exporting, validating, diffing, and writing Lake Shore 336 zone
  tables.
- TOML zone files with schema version 1.
- Pre-write backups, dry-run previews, and post-write verification.
