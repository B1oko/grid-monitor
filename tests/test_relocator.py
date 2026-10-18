from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.engine import apply_migrations, make_engine, make_session_factory
from app.db.models import Inverter
from app.drivers.base import InverterDriver, InverterReading
from app.services.reader import SharedReader
from app.services.relocator import (
    RELOCATE_AFTER_SECONDS,
    RETRY_AFTER_SECONDS,
    InverterRelocator,
)


class FakeDriver(InverterDriver):
    def __init__(self, serial_number: str | None = "H2S1234") -> None:
        super().__init__(host="192.0.2.10")
        self.serial_number = serial_number
        self.online = True
        self.identify_calls = 0

    async def read(self) -> InverterReading:
        if not self.online:
            raise ConnectionError("Unable to connect")
        return InverterReading()

    async def identify(self) -> str | None:
        self.identify_calls += 1
        return self.serial_number

    @classmethod
    async def probe(cls, host: str, **kwargs: object) -> bool:
        return True


@pytest.fixture
async def env(tmp_path: Path):
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'relocator.db').as_posix()}")
    await apply_migrations(engine)
    session_factory = make_session_factory(engine)
    async with session_factory() as session:
        inverter = Inverter(name="Roof", driver_id="saj-h2", host="192.0.2.10")
        session.add(inverter)
        await session.commit()

    driver = FakeDriver()
    runtime = SimpleNamespace(inverter=inverter, reader=SharedReader(driver))
    supervisor = SimpleNamespace(runtimes={inverter.id: runtime}, reload_from_db=AsyncMock())
    discovery = SimpleNamespace(locate=AsyncMock(return_value="192.0.2.42"))
    relocator = InverterRelocator(
        session_factory=session_factory, supervisor=supervisor, discovery=discovery
    )
    yield SimpleNamespace(
        relocator=relocator,
        runtime=runtime,
        driver=driver,
        supervisor=supervisor,
        discovery=discovery,
        session_factory=session_factory,
        inverter_id=inverter.id,
    )
    await engine.dispose()


async def _stored(env) -> Inverter:
    async with env.session_factory() as session:
        return (await session.execute(select(Inverter))).scalar_one()


async def _fail_read(reader: SharedReader) -> None:
    with pytest.raises(ConnectionError):
        await reader.read()


@pytest.mark.asyncio
async def test_learns_serial_number_after_first_successful_read(env) -> None:
    await env.relocator.check()
    assert env.driver.identify_calls == 0

    await env.runtime.reader.read()
    await env.relocator.check()
    await env.relocator.check()

    assert env.driver.identify_calls == 1
    assert env.runtime.inverter.serial_number == "H2S1234"
    assert (await _stored(env)).serial_number == "H2S1234"


@pytest.mark.asyncio
async def test_driver_without_serial_number_is_asked_once(env) -> None:
    env.driver.serial_number = None
    await env.runtime.reader.read()
    await env.relocator.check()
    await env.relocator.check()

    assert env.driver.identify_calls == 1
    assert (await _stored(env)).serial_number is None
    env.discovery.locate.assert_not_awaited()


@pytest.mark.asyncio
async def test_follows_inverter_to_new_address(env) -> None:
    await env.runtime.reader.read()
    await env.relocator.check()

    env.driver.online = False
    await _fail_read(env.runtime.reader)
    failing_since = env.runtime.reader.failing_since
    assert failing_since is not None

    await env.relocator.check(now=failing_since + RELOCATE_AFTER_SECONDS - 1)
    env.discovery.locate.assert_not_awaited()

    await env.relocator.check(now=failing_since + RELOCATE_AFTER_SECONDS)
    env.discovery.locate.assert_awaited_once_with(
        driver_id="saj-h2",
        serial_number="H2S1234",
        port=502,
        unit_id=1,
        near="192.0.2.10",
    )
    stored = await _stored(env)
    assert stored.host == "192.0.2.42"
    assert stored.serial_number == "H2S1234"
    env.supervisor.reload_from_db.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_is_retried_after_a_pause(env) -> None:
    env.discovery.locate.return_value = None
    await env.runtime.reader.read()
    await env.relocator.check()
    env.driver.online = False
    await _fail_read(env.runtime.reader)
    start = env.runtime.reader.failing_since + RELOCATE_AFTER_SECONDS

    await env.relocator.check(now=start)
    await env.relocator.check(now=start + RETRY_AFTER_SECONDS - 1)
    assert env.discovery.locate.await_count == 1

    await env.relocator.check(now=start + RETRY_AFTER_SECONDS)
    assert env.discovery.locate.await_count == 2
    assert (await _stored(env)).host == "192.0.2.10"
    env.supervisor.reload_from_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_read_clears_failure(env) -> None:
    env.driver.online = False
    await _fail_read(env.runtime.reader)
    assert env.runtime.reader.failing_since is not None
    env.driver.online = True
    await env.runtime.reader.read()
    assert env.runtime.reader.failing_since is None
