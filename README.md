# Grid Monitor

Self-hosted live dashboard for solar inverters. Drop a container on a Raspberry Pi
or any Linux box, add your inverter, and watch PV, battery, home load and grid
power in real time.

> **Do not expose this app to the public internet.** There is no authentication
> yet. Keep it on your LAN, a VPN, or behind a reverse proxy with access control.

## Quick start

```bash
docker run -d --name grid-monitor \
  --restart unless-stopped \
  --network host \
  -v gridmonitor:/data \
  ghcr.io/<your-username>/grid-monitor:latest
```

Then open `http://<host>:8000`. The setup page will ask you to scan the
network or enter the inverter address.

`docker compose up -d` with the bundled [docker-compose.yml](docker-compose.yml)
does the same thing.

On Docker Desktop (macOS/Windows), host networking is not available. Use
[docker-compose.bridge.yml](docker-compose.bridge.yml) and add the inverter IP
manually:

```bash
docker compose -f docker-compose.bridge.yml up -d
```

The UI will be at `http://localhost:8080`.

### Tags

| Tag | Meaning |
| --- | --- |
| `latest` | Latest release |
| `0.2.0`, `0.2`, `0` | A specific release, its newest patch, or its newest minor version |
| `edge` | Latest build from `main`, including unreleased dependency updates |

Every pull request raises the version, and each new version on `main` is
published as a release with its notes from [CHANGELOG.md](CHANGELOG.md).

Images are published to GitHub Container Registry and, when configured, Docker Hub.

## Supported inverters

| Driver id | Brand / model | Protocol |
| --- | --- | --- |
| `saj-h2` | SAJ H2 with AIO3 | Modbus TCP (port 502, unit 1) |

More drivers can be added without changing the rest of the app. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Using the app

The UI works in any browser and can be installed on a phone's home screen. It
has a sidebar on desktop and a tab bar on mobile, with five pages:

| Page | What it shows |
| --- | --- |
| **Home** | Live energy flow and cards for solar, home, battery and grid, with grid import shown against your contracted power |
| **History** | Live, today, yesterday and the last 7 days show every recorded sample. This month and this year show daily or monthly energy (kWh) with totals and self-sufficiency |
| **Costs** | Estimated electricity bill for the current or a past billing period: breakdown like your bill, projection to the end of the period, energy by tariff period, savings from solar and cost per day |
| **Alerts** | Active alerts, alert history and notifications for this device |
| **Settings** | Inverters, Alerts, Tariff (electricity prices), Location, Data (recording and retention), Appearance (language and theme) and About |

The interface is available in **English** and **Spanish**. The language
follows the browser and can be changed in **Settings → Appearance**. Push
notifications are sent in the language of each device. To add a language, see
[AGENTS.md](AGENTS.md#adding-a-language).

## How it works

- Live values are polled over Modbus only while a browser is connected.
- A background recorder writes samples to SQLite (default every 5 minutes).
- Configuration (inverters, intervals, retention) is stored in the database and
  edited from the UI. Environment variables are only for bootstrap.
- Each inverter's serial number is read the first time it answers. If it stops
  answering for a few minutes (for example because the router gave it a new IP
  address), the subnet around its last address is scanned for the same serial
  number and the address is updated. Its history stays with the same inverter.

## Electricity costs

Enter the prices from your electricity bill in **Settings → Tariff** and the
**Costs** page estimates what you spend from the grid power the inverter
measures. The model follows the Spanish 2.0TD access tariff used for homes up to
15 kW:

- Energy priced in three periods: peak (P1, 10-14 and 18-22), standard (P2,
  8-10, 14-18 and 22-24) and off-peak (P3, 0-8, weekends and fixed-date national
  holidays). With a single price, enter it in all three.
- Contracted power billed per kW and day in two periods.
- Surplus credit under simplified net billing: it lowers the energy cost of a
  billing period to zero at most, and the page shows how much was left over.
- Other daily charges (social bonus, meter rental), electricity tax and VAT.

A tariff applies from its start date until the next one, so past periods keep
the prices they had. Estimates use the inverter's meter, not the utility meter,
and can differ slightly from the bill.

## Alerts and push notifications

Grid Monitor checks the inverter every 10 seconds in the background, with or
without a browser open, and sends a web push notification to your phone when:

| Alert | Default |
| --- | --- |
| Grid import above the contracted power | 5,500 W for 1 minute |
| No solar production while the sun is up | under 50 W for 30 minutes, sun above 15° |
| Inverter not responding | 10 minutes |

Each alert also notifies you when it clears. Thresholds, delays and your
location (needed to know when it is daytime) are set in **Settings → Alerts**
and **Settings → Location**. Notifications are turned on for each device from
the **Alerts** page.
Overload uses grid power where positive means importing from the grid.

Notifications are delivered as web push, so they reach your phone anywhere
without exposing the app to the internet. They need Grid Monitor served over
HTTPS with a trusted certificate. See
[docs/push-notifications.md](docs/push-notifications.md) for the full setup:
certificates for a LAN-only service, reverse proxy examples, enabling
notifications on Android and iOS, and troubleshooting.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `/data` in Docker, `./data` locally | SQLite file and runtime data |
| `DATABASE_URL` | `sqlite+aiosqlite:///$DATA_DIR/gridmonitor.db` | Set this to use PostgreSQL |
| `TZ` | `UTC` | Container timezone |
| `LOG_LEVEL` | `INFO` | Logging level |
| `PORT` | `8000` | Used only by local uvicorn helpers |
| `VAPID_SUBJECT` | project URL | Contact (`mailto:` or URL) sent to push services |

PostgreSQL example:

```bash
docker compose -f docker-compose.postgres.yml up -d
```

Or:

```text
DATABASE_URL=postgresql+asyncpg://gridmonitor:gridmonitor@db:5432/gridmonitor
```

## Network notes

- **Host networking (Linux)** is the plug-and-play option: the container can
  scan the LAN and reach the inverter.
- **Bridge networking** needs the inverter IP typed on the setup page. Discovery
  cannot see your home LAN from Docker Desktop.
- **Network scans** walk a `/24` and probe Modbus TCP. Only run a scan on a
  network you own or are authorized to scan. When an inverter stops answering,
  Grid Monitor scans the subnet of its last address to find it again, at most
  every 15 minutes.
- **A fixed IP address** (a DHCP reservation in your router) for the inverter
  avoids the gap in the history while it is found again.
- Some inverters (including the SAJ AIO3) accept a limited number of Modbus
  clients. If Home Assistant is already polling the same unit, readings can
  flake. Prefer a single active Modbus reader.

If the container cannot write to `/data`, the volume is probably owned by root.
The image runs as uid `1000` after fixing ownership on startup. You can also
`chown 1000:1000` the bind mount.

## Local development

```bash
uv sync --all-groups
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check .
```

## HTTP API

| Endpoint | Description |
| --- | --- |
| `GET /health` | App status and configured inverters |
| `GET /api/drivers` | Installed inverter drivers |
| `GET/POST/PATCH/DELETE /api/inverters` | Inverter configuration |
| `GET /api/inverters/{id}/snapshot` | One-shot live reading |
| `GET/PUT /api/settings` | Persisted app settings |
| `GET /api/history` | Aggregated history (`inverter_id`, `from`, `to`, `resolution`) |
| `GET /api/energy` | Energy in kWh per day or month (`inverter_id`, `from`, `to`, `resolution`, `tz`) |
| `GET /api/alerts` | Alert history (`limit`, `active`) |
| `GET/POST/PUT/DELETE /api/tariffs` | Electricity tariffs |
| `GET /api/costs` | Estimated cost for a billing period (`inverter_id`, `from`, `to`, `tz`) |
| `GET /i18n/languages.json`, `/i18n/{lang}.json` | Available languages and translation catalogs |
| `GET /api/push/public-key` | VAPID public key and number of subscribed devices |
| `POST /api/push/subscribe`, `/unsubscribe` | Register or remove a push subscription |
| `POST /api/push/test` | Send a test notification to every device |
| `POST /api/discover` | Opt-in LAN scan |
| `WS /ws/live` | Live samples (`inverter_id` on every message) |

## Roadmap

- Optional authentication for the UI and API
- Home Assistant MQTT discovery
- Additional inverter drivers
- 32-bit ARM (`linux/arm/v7`) images if there is demand

## License

[MIT](LICENSE)
