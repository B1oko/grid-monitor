from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.drivers.base import InverterDriver
from app.drivers.registry import get_driver_class, list_driver_classes

logger = logging.getLogger(__name__)


class DiscoveryStatus(StrEnum):
    SEARCHING = "searching"
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass
class DiscoveryCandidate:
    host: str
    driver_id: str
    latency_ms: float
    port: int = 502
    serial_number: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "driver_id": self.driver_id,
            "latency_ms": self.latency_ms,
            "port": self.port,
            "serial_number": self.serial_number,
        }


@dataclass
class DiscoveryResult:
    status: DiscoveryStatus
    host: str | None = None
    driver_id: str | None = None
    candidates: list[DiscoveryCandidate] = field(default_factory=list)
    subnet: str | None = None
    duration_ms: float | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "host": self.host,
            "driver_id": self.driver_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "subnet": self.subnet,
            "duration_ms": self.duration_ms,
            "message": self.message,
        }


def get_local_subnet(prefix_length: int = 24) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
    network = ipaddress.ip_network(f"{local_ip}/{prefix_length}", strict=False)
    return str(network)


def iter_subnet_hosts(subnet: str) -> list[str]:
    network = ipaddress.ip_network(subnet, strict=False)
    return [str(host) for host in network.hosts()]


def subnet_around(host: str, prefix_length: int) -> str | None:
    """Return the subnet that contains ``host``, or None when it is a host name."""
    try:
        return str(ipaddress.ip_network(f"{host}/{prefix_length}", strict=False))
    except ValueError:
        return None


async def read_serial_number(
    driver_cls: type[InverterDriver],
    host: str,
    *,
    port: int,
    unit_id: int,
    timeout: float,
) -> str | None:
    driver = driver_cls(host=host, port=port, unit_id=unit_id, timeout_seconds=timeout)
    try:
        return await driver.identify()
    except Exception:
        logger.debug("Could not read serial number of %s:%s", host, port, exc_info=True)
        return None
    finally:
        await driver.close()


async def is_port_open(host: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (TimeoutError, OSError, ConnectionRefusedError):
        return False


async def probe_drivers(
    host: str,
    *,
    port: int = 502,
    timeout: float = 2.0,
) -> list[DiscoveryCandidate]:
    candidates: list[DiscoveryCandidate] = []
    for driver_cls in list_driver_classes():
        started = time.perf_counter()
        try:
            ok = await driver_cls.probe(
                host,
                port=port,
                unit_id=driver_cls.meta.default_unit_id,
                timeout=timeout,
            )
        except Exception:
            logger.debug("Probe failed for %s with %s", host, driver_cls.meta.id, exc_info=True)
            ok = False
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if ok:
            serial_number = await read_serial_number(
                driver_cls,
                host,
                port=port,
                unit_id=driver_cls.meta.default_unit_id,
                timeout=timeout,
            )
            candidates.append(
                DiscoveryCandidate(
                    host=host,
                    driver_id=driver_cls.meta.id,
                    latency_ms=latency_ms,
                    port=port,
                    serial_number=serial_number,
                )
            )
    return candidates


class InverterDiscovery:
    def __init__(
        self,
        *,
        port: int = 502,
        concurrency: int = 32,
        port_scan_timeout: float = 0.5,
        probe_timeout: float = 2.0,
        subnet_prefix_length: int = 24,
    ) -> None:
        self._port = port
        self._concurrency = concurrency
        self._port_scan_timeout = port_scan_timeout
        self._probe_timeout = probe_timeout
        self._subnet_prefix_length = subnet_prefix_length
        self._lock = asyncio.Lock()
        self._in_progress = False
        self._last_result: DiscoveryResult | None = None

    def configure(
        self,
        *,
        concurrency: int | None = None,
        port_scan_timeout: float | None = None,
        probe_timeout: float | None = None,
        subnet_prefix_length: int | None = None,
    ) -> None:
        if concurrency is not None:
            self._concurrency = concurrency
        if port_scan_timeout is not None:
            self._port_scan_timeout = port_scan_timeout
        if probe_timeout is not None:
            self._probe_timeout = probe_timeout
        if subnet_prefix_length is not None:
            self._subnet_prefix_length = subnet_prefix_length

    @property
    def in_progress(self) -> bool:
        return self._in_progress

    @property
    def last_result(self) -> DiscoveryResult | None:
        return self._last_result

    async def discover(self, *, subnet: str | None = None) -> DiscoveryResult:
        async with self._lock:
            if self._in_progress:
                return self._last_result or DiscoveryResult(
                    status=DiscoveryStatus.SEARCHING,
                    message="Discovery already in progress",
                )

            self._in_progress = True
            started = time.perf_counter()
            try:
                resolved_subnet = subnet or get_local_subnet(self._subnet_prefix_length)
                self._last_result = DiscoveryResult(
                    status=DiscoveryStatus.SEARCHING,
                    subnet=resolved_subnet,
                    message="Scanning local network",
                )

                open_hosts = await self._scan_open_ports(resolved_subnet)
                candidates: list[DiscoveryCandidate] = []
                for host in open_hosts:
                    candidates.extend(
                        await probe_drivers(host, port=self._port, timeout=self._probe_timeout)
                    )

                candidates.sort(key=lambda item: item.latency_ms)
                duration_ms = round((time.perf_counter() - started) * 1000, 1)

                if candidates:
                    result = DiscoveryResult(
                        status=DiscoveryStatus.FOUND,
                        host=candidates[0].host,
                        driver_id=candidates[0].driver_id,
                        candidates=candidates,
                        subnet=resolved_subnet,
                        duration_ms=duration_ms,
                        message=f"Found {len(candidates)} candidate(s)",
                    )
                else:
                    result = DiscoveryResult(
                        status=DiscoveryStatus.NOT_FOUND,
                        candidates=candidates,
                        subnet=resolved_subnet,
                        duration_ms=duration_ms,
                        message="No compatible inverter found on the local network",
                    )

                self._last_result = result
                return result
            except Exception as exc:
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                result = DiscoveryResult(
                    status=DiscoveryStatus.ERROR,
                    subnet=subnet,
                    duration_ms=duration_ms,
                    message=str(exc),
                )
                self._last_result = result
                return result
            finally:
                self._in_progress = False

    async def locate(
        self,
        *,
        driver_id: str,
        serial_number: str,
        port: int,
        unit_id: int,
        near: str,
    ) -> str | None:
        """Find the address of the inverter with ``serial_number``.

        Scans the subnet around its last known address ``near`` rather than the
        server's own subnet, so it also works when Grid Monitor runs in a Docker
        bridge network. Returns None when a scan is already running.
        """
        subnet = subnet_around(near, self._subnet_prefix_length)
        if subnet is None or self._lock.locked():
            return None
        driver_cls = get_driver_class(driver_id)
        async with self._lock:
            for host in await self._scan_open_ports(subnet, port):
                found = await read_serial_number(
                    driver_cls, host, port=port, unit_id=unit_id, timeout=self._probe_timeout
                )
                if found == serial_number:
                    return host
        return None

    async def _scan_open_ports(self, subnet: str, port: int | None = None) -> list[str]:
        hosts = iter_subnet_hosts(subnet)
        semaphore = asyncio.Semaphore(self._concurrency)
        open_hosts: list[str] = []
        port = self._port if port is None else port

        async def check_host(host: str) -> None:
            async with semaphore:
                if await is_port_open(host, port, self._port_scan_timeout):
                    open_hosts.append(host)

        await asyncio.gather(*(check_host(host) for host in hosts))
        return open_hosts
