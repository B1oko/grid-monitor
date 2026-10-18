# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-18

### Added

- Inverters are identified by their serial number, read from the inverter the
  first time it answers. When an inverter stops answering for a few minutes,
  the subnet around its last address is scanned for the same serial number and
  its address is updated, so it keeps recording into the same history after
  the router gives it a new IP address
- The SAJ H2 / AIO3 driver reads the serial number, and drivers can implement
  `identify()` to support this
- The serial number is shown in Settings → Inverters and in network scan
  results, which also mark inverters that are already added
- `serial_number` field in the inverter API

### Changed

- Changing an inverter's model, address, port or unit id forgets its serial
  number, which is read again from the new connection

## [0.2.0] - 2026-10-16

### Added

- Pluggable inverter driver registry with a canonical reading model
- SAJ H2 / AIO3 Modbus TCP driver
- Multi-inverter support with configuration stored in the database
- SQLite by default, PostgreSQL optional
- Alembic migrations applied on startup
- First-run setup wizard and settings UI
- Optional history retention and hourly downsampling
- Multi-arch Docker image publishing workflow
- Alerts with web push notifications: grid import above the contracted power,
  no solar production in daylight, and inverter not responding
- Alert history (`GET /api/alerts`) and an active-alert banner on the dashboard
- English and Spanish translations. The language follows the browser and can be
  changed in Settings → Appearance; push notifications use each device's language
- `AGENTS.md` with working and translation rules for contributors and AI agents
- Costs page with an estimate of the electricity bill from your tariff prices
  (Spanish 2.0TD periods, surplus credit, taxes), a projection to the end of
  the billing period, savings from solar and cost per day. Tariffs are set in
  Settings → Tariff and keep their start date so past periods use old prices
- Versioning: every pull request raises the version in `pyproject.toml` and
  adds its section here. CI checks it, and a new version on `main` publishes
  the `X.Y.Z` and `latest` images and creates the `vX.Y.Z` tag and GitHub release

### Changed

- New web UI: sidebar on desktop and tab bar on mobile, with Home, History,
  Alerts and Settings pages instead of a single page with dialogs
- Home shows the energy flow and cards for solar, home, battery and grid, with
  grid import against the contracted power
- Settings is split into Inverters, Alerts, Location, Data, Appearance and
  About, with a save bar that appears only when there are unsaved changes
- First-run setup is a page instead of a wizard dialog
- Alert events and push subscriptions store parameters and language instead of
  rendered text (migration `0003`, applied on startup)
- History: today, yesterday and 7 days plot every recorded sample on a real
  time axis, with breaks where data is missing. Battery level has its own chart
- History: this month and this year show energy per day or month in kWh
  (solar, home, grid import/export, battery charge/discharge) with period
  totals and self-sufficiency, split by the browser's time zone
  (`GET /api/energy`). The 30-day range was removed
- Chart and dashboard colors changed to a palette that stays distinguishable
  with color-vision deficiency in light and dark themes
- Updated FastAPI 0.141 (Starlette 1.8), Uvicorn 0.52, pydantic-settings 2.15
  and pymodbus 3.15. The Modbus transport passes `device_id` instead of the
  removed `slave` argument

### Fixed

- Deleting an inverter now also deletes its alerts. Alerts left behind by
  inverters deleted earlier are removed on upgrade
- Spacing between the text, fields and button in Settings → Location
- The browser tab showed `nav.setup` instead of the app name on the welcome screen
- After an update the UI could show translation keys (such as `tariff.add_title`)
  instead of text, because the browser kept an old catalog. UI files are now
  always revalidated
- Installed apps (for example on a phone) kept old files after an update. The
  service worker now always checks with the server, and its cache is named
  after the app version so each release replaces it

## [0.1.0] - 2026-08-21

- Initial public release
