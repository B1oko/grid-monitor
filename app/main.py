from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app import __version__
from app.api.deps import AppState
from app.api.routers import (
    alerts,
    costs,
    discovery,
    drivers,
    health,
    history,
    inverters,
    push,
    settings,
    ui,
)
from app.core.config import get_settings
from app.core.settings_store import SettingsStore
from app.db.engine import apply_migrations, make_engine, make_session_factory
from app.db.models import Inverter
from app.drivers.registry import load_drivers
from app.services.alerts import AlertService
from app.services.discovery import InverterDiscovery
from app.services.live_manager import LiveHub
from app.services.notifier import WebPushNotifier, load_or_create_vapid
from app.services.relocator import InverterRelocator
from app.services.retention import RetentionService
from app.services.supervisor import InverterSupervisor

STATIC_DIR = Path(__file__).parent / "web" / "static"
logger = logging.getLogger(__name__)


async def _retention_loop(state: AppState) -> None:
    while True:
        try:
            cfg = await state.settings_store.get_all()
            await state.retention.run(
                retention_days=int(cfg["retention_days"]),
                downsample_after_days=int(cfg["downsample_after_days"]),
            )
        except Exception:
            logger.exception("Retention job failed")
        await asyncio.sleep(6 * 60 * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL.upper())
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_drivers()

    engine = make_engine(settings.database_url)
    await apply_migrations(engine)
    session_factory = make_session_factory(engine)
    settings_store = SettingsStore(session_factory)
    cfg = await settings_store.get_all()

    hub = LiveHub()
    supervisor = InverterSupervisor(
        session_factory=session_factory,
        hub=hub,
        recorder_interval_seconds=float(cfg["recorder_interval_seconds"]),
    )
    hub.set_hooks(on_first=supervisor.start_live, on_last=supervisor.stop_live)

    discovery_service = InverterDiscovery(
        concurrency=int(cfg["discovery_concurrency"]),
        port_scan_timeout=float(cfg["discovery_port_scan_timeout"]),
        probe_timeout=float(cfg["discovery_probe_timeout"]),
        subnet_prefix_length=int(cfg["discovery_subnet_prefix_length"]),
    )
    relocator = InverterRelocator(
        session_factory=session_factory,
        supervisor=supervisor,
        discovery=discovery_service,
    )
    retention = RetentionService(session_factory, engine.dialect.name)
    push_notifier = WebPushNotifier(
        session_factory=session_factory,
        vapid=load_or_create_vapid(settings.DATA_DIR),
        subject=settings.VAPID_SUBJECT,
    )
    alert_service = AlertService(
        session_factory=session_factory,
        settings_store=settings_store,
        supervisor=supervisor,
        notifiers=[push_notifier],
    )

    state = AppState(
        engine=engine,
        session_factory=session_factory,
        settings_store=settings_store,
        supervisor=supervisor,
        hub=hub,
        discovery=discovery_service,
        retention=retention,
        push=push_notifier,
        alerts=alert_service,
        relocator=relocator,
    )
    app.state.core = state

    async with session_factory() as session:
        inverters_list = (await session.execute(select(Inverter))).scalars().all()
    await supervisor.reload(list(inverters_list))

    state.retention_task = asyncio.create_task(_retention_loop(state), name="retention")
    await alert_service.start()
    await relocator.start()

    yield

    await relocator.stop()
    await alert_service.stop()
    task = state.retention_task
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await hub.shutdown()
    await supervisor.shutdown()
    await engine.dispose()


app = FastAPI(title="Grid Monitor", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Without Cache-Control the browser may reuse cached UI files without asking, so
# after an update new modules can run with an old translation catalog. no-cache
# keeps them cached but revalidated (a cheap 304 when unchanged).
@app.middleware("http")
async def revalidate_ui_files(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith(("/api/", "/ws/", "/docs", "/openapi.json")):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.include_router(ui.router)
app.include_router(health.router)
app.include_router(drivers.router)
app.include_router(settings.router)
app.include_router(inverters.router)
app.include_router(discovery.router)
app.include_router(history.router)
app.include_router(costs.router)
app.include_router(alerts.router)
app.include_router(push.router)
