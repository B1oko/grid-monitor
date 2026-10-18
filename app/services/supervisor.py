from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Inverter
from app.drivers.base import InverterDriver
from app.drivers.registry import get_driver_class
from app.services.live_manager import LiveHub, LivePoller
from app.services.reader import SharedReader
from app.services.recorder import Recorder

logger = logging.getLogger(__name__)


class InverterRuntime:
    def __init__(
        self,
        inverter: Inverter,
        reader: SharedReader,
        recorder: Recorder,
        poller: LivePoller,
    ) -> None:
        self.inverter = inverter
        self.reader = reader
        self.recorder = recorder
        self.poller = poller

    @property
    def driver(self) -> InverterDriver:
        return self.reader.driver

    async def start(self) -> None:
        await self.recorder.start()

    async def start_live(self) -> None:
        await self.poller.start()

    async def stop_live(self) -> None:
        await self.poller.stop()

    async def stop(self) -> None:
        await self.poller.stop()
        await self.recorder.stop()
        await self.reader.close()


def build_driver(inverter: Inverter) -> InverterDriver:
    cls = get_driver_class(inverter.driver_id)
    return cls(
        host=inverter.host,
        port=inverter.port,
        unit_id=inverter.unit_id,
        timeout_seconds=inverter.timeout_seconds,
        extra=inverter.extra,
    )


class InverterSupervisor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        hub: LiveHub,
        recorder_interval_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._hub = hub
        self._recorder_interval_seconds = recorder_interval_seconds
        self._runtimes: dict[int, InverterRuntime] = {}
        self._live_wanted = False

    @property
    def runtimes(self) -> dict[int, InverterRuntime]:
        return self._runtimes

    def set_recorder_interval(self, seconds: float) -> None:
        self._recorder_interval_seconds = seconds

    def get_runtime(self, inverter_id: int) -> InverterRuntime | None:
        return self._runtimes.get(inverter_id)

    def list_status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": runtime.inverter.id,
                "name": runtime.inverter.name,
                "driver_id": runtime.inverter.driver_id,
                "host": runtime.driver.host,
                "port": runtime.driver.port,
                "enabled": runtime.inverter.enabled,
            }
            for runtime in self._runtimes.values()
        ]

    async def reload(self, inverters: list[Inverter]) -> None:
        wanted = {item.id: item for item in inverters if item.enabled}
        for inverter_id in list(self._runtimes):
            if inverter_id not in wanted:
                await self._stop_one(inverter_id)

        for inverter in wanted.values():
            current = self._runtimes.get(inverter.id)
            if current is None or _config_changed(current.inverter, inverter):
                await self._stop_one(inverter.id)
                await self._start_one(inverter)
            else:
                current.inverter = inverter

    async def reload_from_db(self) -> None:
        async with self._session_factory() as session:
            inverters = (await session.execute(select(Inverter))).scalars().all()
        await self.reload(list(inverters))

    async def start_live(self) -> None:
        self._live_wanted = True
        for runtime in self._runtimes.values():
            await runtime.start_live()

    async def stop_live(self) -> None:
        self._live_wanted = False
        for runtime in self._runtimes.values():
            await runtime.stop_live()

    async def shutdown(self) -> None:
        self._live_wanted = False
        for inverter_id in list(self._runtimes):
            await self._stop_one(inverter_id)

    async def _start_one(self, inverter: Inverter) -> None:
        reader = SharedReader(build_driver(inverter))
        recorder = Recorder(
            inverter_id=inverter.id,
            driver=reader,
            session_factory=self._session_factory,
            interval_seconds=self._recorder_interval_seconds,
        )
        poller = LivePoller(
            inverter_id=inverter.id,
            driver=reader,
            hub=self._hub,
            poll_interval_seconds=inverter.poll_interval_s,
        )
        runtime = InverterRuntime(inverter, reader, recorder, poller)
        self._runtimes[inverter.id] = runtime
        await runtime.start()
        if self._live_wanted:
            await runtime.start_live()
        logger.info("Started inverter %s (%s @ %s)", inverter.id, inverter.name, inverter.host)

    async def _stop_one(self, inverter_id: int) -> None:
        runtime = self._runtimes.pop(inverter_id, None)
        if runtime is not None:
            await runtime.stop()
            logger.info("Stopped inverter %s", inverter_id)


def _config_changed(old: Inverter, new: Inverter) -> bool:
    fields = (
        "name",
        "driver_id",
        "host",
        "port",
        "unit_id",
        "timeout_seconds",
        "poll_interval_s",
        "battery_capacity_kwh",
        "enabled",
        "extra",
    )
    return any(getattr(old, field) != getattr(new, field) for field in fields)
