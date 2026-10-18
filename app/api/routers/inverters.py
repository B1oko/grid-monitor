from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select

from app.api.deps import AppState, get_state
from app.api.schemas import InverterCreate, InverterOut, InverterUpdate
from app.db.models import AlertEvent, Inverter
from app.drivers.registry import get_driver_class

router = APIRouter(prefix="/api", tags=["inverters"])


# Changing any of these may point the inverter at a different device, so the
# serial number is learned again.
CONNECTION_FIELDS = ("driver_id", "host", "port", "unit_id")


async def _reload(state: AppState) -> None:
    await state.supervisor.reload_from_db()


@router.get("/inverters", response_model=list[InverterOut])
async def list_inverters(state: AppState = Depends(get_state)) -> list[Inverter]:
    async with state.session_factory() as session:
        result = await session.execute(select(Inverter).order_by(Inverter.id))
        return list(result.scalars().all())


@router.post("/inverters", response_model=InverterOut, status_code=201)
async def create_inverter(
    body: InverterCreate,
    state: AppState = Depends(get_state),
) -> Inverter:
    try:
        get_driver_class(body.driver_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    inverter = Inverter(**body.model_dump())
    async with state.session_factory() as session:
        session.add(inverter)
        await session.commit()
        await session.refresh(inverter)
        created = inverter
    await _reload(state)
    return created


@router.get("/inverters/{inverter_id}", response_model=InverterOut)
async def get_inverter(inverter_id: int, state: AppState = Depends(get_state)) -> Inverter:
    async with state.session_factory() as session:
        inverter = await session.get(Inverter, inverter_id)
        if inverter is None:
            raise HTTPException(status_code=404, detail="Inverter not found")
        return inverter


@router.patch("/inverters/{inverter_id}", response_model=InverterOut)
async def update_inverter(
    inverter_id: int,
    body: InverterUpdate,
    state: AppState = Depends(get_state),
) -> Inverter:
    values = body.model_dump(exclude_unset=True)
    if "driver_id" in values:
        try:
            get_driver_class(values["driver_id"])
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with state.session_factory() as session:
        inverter = await session.get(Inverter, inverter_id)
        if inverter is None:
            raise HTTPException(status_code=404, detail="Inverter not found")
        if any(
            key in values and values[key] != getattr(inverter, key) for key in CONNECTION_FIELDS
        ):
            inverter.serial_number = None
        for key, value in values.items():
            setattr(inverter, key, value)
        await session.commit()
        await session.refresh(inverter)
        updated = inverter
    await _reload(state)
    return updated


@router.delete("/inverters/{inverter_id}", status_code=204)
async def delete_inverter(inverter_id: int, state: AppState = Depends(get_state)) -> Response:
    async with state.session_factory() as session:
        inverter = await session.get(Inverter, inverter_id)
        if inverter is None:
            raise HTTPException(status_code=404, detail="Inverter not found")
        # SQLite does not enforce ON DELETE CASCADE, so remove the alerts explicitly.
        await session.execute(delete(AlertEvent).where(AlertEvent.inverter_id == inverter_id))
        await session.delete(inverter)
        await session.commit()
    await _reload(state)
    return Response(status_code=204)


@router.get("/inverters/{inverter_id}/snapshot")
async def snapshot(inverter_id: int, state: AppState = Depends(get_state)) -> dict[str, object]:
    runtime = state.supervisor.get_runtime(inverter_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Inverter is not running")
    try:
        reading = await runtime.reader.read()
        return reading.model_dump(mode="json")
    finally:
        if not state.hub.is_polling:
            await runtime.driver.close()
