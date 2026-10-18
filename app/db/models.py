from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Inverter(Base):
    __tablename__ = "inverters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    driver_id: Mapped[str] = mapped_column(String(64), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=502)
    unit_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    poll_interval_s: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    battery_capacity_kwh: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Learned from the driver; used to find the inverter again after an IP change.
    serial_number: Mapped[str | None] = mapped_column(String(64))

    samples: Mapped[list[InverterSample]] = relationship(
        back_populates="inverter", cascade="all, delete-orphan"
    )


class InverterSample(Base):
    __tablename__ = "inverter_samples"
    __table_args__ = (UniqueConstraint("inverter_id", "ts", name="uq_inverter_sample_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inverter_id: Mapped[int] = mapped_column(
        ForeignKey("inverters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    pv_power_w: Mapped[int | None] = mapped_column(Integer)
    battery_power_w: Mapped[int | None] = mapped_column(Integer)
    grid_power_w: Mapped[int | None] = mapped_column(Integer)
    load_power_w: Mapped[int | None] = mapped_column(Integer)
    inverter_power_w: Mapped[int | None] = mapped_column(Integer)
    battery_soc_pct: Mapped[float | None] = mapped_column(Float)
    battery_temp_c: Mapped[float | None] = mapped_column(Float)

    inverter: Mapped[Inverter] = relationship(back_populates="samples")


class AppSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inverter_id: Mapped[int] = mapped_column(
        ForeignKey("inverters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    peak_value: Mapped[float | None] = mapped_column(Float)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Tariff(Base):
    """Electricity prices in effect from ``valid_from`` until the next tariff starts."""

    __tablename__ = "tariffs"
    __table_args__ = (UniqueConstraint("valid_from", name="uq_tariff_valid_from"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    energy_price_p1: Mapped[float] = mapped_column(Float, nullable=False)
    energy_price_p2: Mapped[float] = mapped_column(Float, nullable=False)
    energy_price_p3: Mapped[float] = mapped_column(Float, nullable=False)
    power_price_p1: Mapped[float] = mapped_column(Float, nullable=False)
    power_price_p2: Mapped[float] = mapped_column(Float, nullable=False)
    contracted_power_p1_kw: Mapped[float] = mapped_column(Float, nullable=False)
    contracted_power_p2_kw: Mapped[float] = mapped_column(Float, nullable=False)
    export_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fixed_daily: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    electricity_tax_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    vat_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
