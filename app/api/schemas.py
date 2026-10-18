from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class InverterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    driver_id: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=502, ge=1, le=65535)
    unit_id: int = Field(default=1, ge=1, le=255)
    timeout_seconds: float = Field(default=3.0, ge=0.5, le=30)
    poll_interval_s: float = Field(default=2.0, ge=0.5, le=60)
    battery_capacity_kwh: float | None = Field(default=None, ge=0)
    enabled: bool = True
    extra: dict[str, Any] | None = None


class InverterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    driver_id: str | None = Field(default=None, min_length=1, max_length=64)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    unit_id: int | None = Field(default=None, ge=1, le=255)
    timeout_seconds: float | None = Field(default=None, ge=0.5, le=30)
    poll_interval_s: float | None = Field(default=None, ge=0.5, le=60)
    battery_capacity_kwh: float | None = Field(default=None, ge=0)
    enabled: bool | None = None
    extra: dict[str, Any] | None = None


class InverterOut(BaseModel):
    id: int
    name: str
    driver_id: str
    host: str
    port: int
    unit_id: int
    timeout_seconds: float
    poll_interval_s: float
    battery_capacity_kwh: float | None
    enabled: bool
    extra: dict[str, Any] | None
    serial_number: str | None = None

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    timezone: str | None = None
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    downsample_after_days: int | None = Field(default=None, ge=0, le=3650)
    recorder_interval_seconds: float | None = Field(default=None, ge=10, le=3600)
    discovery_concurrency: int | None = Field(default=None, ge=1, le=256)
    discovery_port_scan_timeout: float | None = Field(default=None, ge=0.1, le=5)
    discovery_probe_timeout: float | None = Field(default=None, ge=0.2, le=10)
    discovery_subnet_prefix_length: int | None = Field(default=None, ge=16, le=30)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    alerts_check_interval_seconds: float | None = Field(default=None, ge=5, le=300)
    alert_overload_enabled: bool | None = None
    alert_overload_limit_w: int | None = Field(default=None, ge=100, le=100_000)
    alert_overload_minutes: float | None = Field(default=None, ge=0, le=120)
    alert_no_pv_enabled: bool | None = None
    alert_no_pv_minutes: float | None = Field(default=None, ge=1, le=600)
    alert_no_pv_threshold_w: int | None = Field(default=None, ge=0, le=10_000)
    alert_no_pv_min_sun_elevation_deg: float | None = Field(default=None, ge=0, le=60)
    alert_offline_enabled: bool | None = None
    alert_offline_minutes: float | None = Field(default=None, ge=1, le=600)
    billing_day: int | None = Field(default=None, ge=1, le=28)


class TariffIn(BaseModel):
    valid_from: date
    energy_price_p1: float = Field(ge=0, le=10)
    energy_price_p2: float = Field(ge=0, le=10)
    energy_price_p3: float = Field(ge=0, le=10)
    power_price_p1: float = Field(ge=0, le=10)
    power_price_p2: float = Field(ge=0, le=10)
    contracted_power_p1_kw: float = Field(ge=0, le=100)
    contracted_power_p2_kw: float = Field(ge=0, le=100)
    export_price: float = Field(default=0.0, ge=0, le=10)
    fixed_daily: float = Field(default=0.0, ge=0, le=100)
    electricity_tax_pct: float = Field(default=0.0, ge=0, le=100)
    vat_pct: float = Field(default=0.0, ge=0, le=100)


class TariffOut(TariffIn):
    id: int

    model_config = {"from_attributes": True}


class Resolution(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


class HistoryPoint(BaseModel):
    ts: datetime | str
    pv_power_w: int | None = None
    battery_power_w: int | None = None
    grid_power_w: int | None = None
    load_power_w: int | None = None
    inverter_power_w: int | None = None
    battery_soc_pct: float | None = None
    battery_temp_c: float | None = None


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1024)
    keys: PushKeys
    language: str | None = Field(default=None, max_length=35)


class PushUnsubscribe(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1024)


class AlertEventOut(BaseModel):
    id: int
    inverter_id: int
    kind: str
    title: str
    message: str
    started_at: datetime
    notified_at: datetime
    resolved_at: datetime | None
    peak_value: float | None
    params: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @field_validator("started_at", "notified_at", "resolved_at")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite drops the offset; timestamps are always written in UTC.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
