"""Follows inverters to their new IP address, for example after a DHCP lease change.

Each inverter's serial number is learned from its driver the first time it answers.
When an inverter has not answered for a while, the subnet around its last address is
scanned for a device with the same serial number and the stored address is updated,
so its history continues under the same inverter.
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Inverter
from app.services.discovery import InverterDiscovery
from app.services.supervisor import InverterRuntime, InverterSupervisor

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60.0
RELOCATE_AFTER_SECONDS = 180.0
RETRY_AFTER_SECONDS = 15 * 60.0


class InverterRelocator:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        supervisor: InverterSupervisor,
        discovery: InverterDiscovery,
    ) -> None:
        self._session_factory = session_factory
        self._supervisor = supervisor
        self._discovery = discovery
        self._task: asyncio.Task[None] | None = None
        # Runtime whose serial number was already asked for, per inverter. A runtime
        # is replaced when its connection settings change, which asks again.
        self._identified: dict[int, InverterRuntime] = {}
        self._last_search: dict[int, float] = {}

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="relocator")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            await self.check()

    async def check(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for runtime in list(self._supervisor.runtimes.values()):
            try:
                if runtime.inverter.serial_number is None:
                    await self._learn_serial(runtime)
                else:
                    await self._follow(runtime, now)
            except Exception:
                logger.exception("Relocator: check of inverter %s failed", runtime.inverter.id)

    async def _learn_serial(self, runtime: InverterRuntime) -> None:
        inverter = runtime.inverter
        if runtime.reader.last_read_at is None or self._identified.get(inverter.id) is runtime:
            return
        serial_number = await runtime.reader.identify()
        self._identified[inverter.id] = runtime
        if serial_number is None:
            return
        async with self._session_factory() as session:
            await session.execute(
                update(Inverter)
                .where(Inverter.id == inverter.id, Inverter.serial_number.is_(None))
                .values(serial_number=serial_number)
            )
            await session.commit()
        inverter.serial_number = serial_number
        logger.info("Inverter %s has serial number %s", inverter.id, serial_number)

    async def _follow(self, runtime: InverterRuntime, now: float) -> None:
        inverter = runtime.inverter
        failing_since = runtime.reader.failing_since
        if failing_since is None or now - failing_since < RELOCATE_AFTER_SECONDS:
            return
        last_search = self._last_search.get(inverter.id)
        if last_search is not None and now - last_search < RETRY_AFTER_SECONDS:
            return
        self._last_search[inverter.id] = now

        logger.info(
            "Inverter %s is not answering at %s, searching for serial number %s",
            inverter.id,
            inverter.host,
            inverter.serial_number,
        )
        host = await self._discovery.locate(
            driver_id=inverter.driver_id,
            serial_number=inverter.serial_number,
            port=inverter.port,
            unit_id=inverter.unit_id,
            near=inverter.host,
        )
        if host is None or host == inverter.host:
            return

        async with self._session_factory() as session:
            await session.execute(
                update(Inverter).where(Inverter.id == inverter.id).values(host=host)
            )
            await session.commit()
        logger.info("Inverter %s moved from %s to %s", inverter.id, inverter.host, host)
        self._last_search.pop(inverter.id, None)
        await self._supervisor.reload_from_db()
