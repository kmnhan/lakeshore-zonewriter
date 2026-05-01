from __future__ import annotations

import time
from typing import Any

import pyvisa
from pyvisa import constants


REQUEST_INTERVAL_MS = 50
CONTROLLER_TIMEOUT_MS = 10_000
CONTROLLER_BAUD_RATE = 57_600
CONTROLLER_DATA_BITS = 7
CONTROLLER_PARITY = constants.Parity.odd
CONTROLLER_STOP_BITS = constants.StopBits.one
CONTROLLER_FLOW_CONTROL = constants.ControlFlow.none
CONTROLLER_READ_TERMINATION = "\r\n"
CONTROLLER_WRITE_TERMINATION = "\r\n"


class RequestHandler:
    """A pyvisa wrapper that rate-limits instrument requests."""

    def __init__(self, resource_name: str, interval_ms: int = 50, **kwargs: Any):
        self.resource_name = resource_name
        self.interval_ms = interval_ms
        self._resource_kwargs = kwargs
        self.inst: Any | None = None
        self._last_update = 0

    def open(self) -> None:
        self.inst = pyvisa.ResourceManager().open_resource(
            self.resource_name, **self._resource_kwargs
        )
        self._last_update = time.perf_counter_ns()

    def wait_time(self) -> None:
        if self.interval_ms == 0:
            return
        interval_ns = self.interval_ms * 1_000_000
        while (time.perf_counter_ns() - self._last_update) <= interval_ns:
            time.sleep(0.0001)

    def write(self, *args: Any, **kwargs: Any) -> Any:
        inst = self._require_open()
        self.wait_time()
        result = inst.write(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        return result

    def query(self, *args: Any, **kwargs: Any) -> Any:
        inst = self._require_open()
        self.wait_time()
        result = inst.query(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        return result

    def read(self, *args: Any, **kwargs: Any) -> Any:
        inst = self._require_open()
        self.wait_time()
        result = inst.read(*args, **kwargs)
        self._last_update = time.perf_counter_ns()
        return result

    def close(self) -> None:
        if self.inst is not None:
            self.inst.close()
            self.inst = None

    def _require_open(self) -> Any:
        if self.inst is None:
            raise RuntimeError("resource is not open")
        return self.inst


def list_resources() -> tuple[str, ...]:
    return tuple(pyvisa.ResourceManager().list_resources())


def open_controller_transport(
    resource_name: str,
    *,
    baud_rate: int | None = None,
) -> RequestHandler:
    resource_kwargs: dict[str, Any] = {
        "timeout": CONTROLLER_TIMEOUT_MS,
        "read_termination": CONTROLLER_READ_TERMINATION,
        "write_termination": CONTROLLER_WRITE_TERMINATION,
    }
    if _is_serial_resource(resource_name):
        resource_kwargs.update(
            baud_rate=baud_rate or CONTROLLER_BAUD_RATE,
            data_bits=CONTROLLER_DATA_BITS,
            parity=CONTROLLER_PARITY,
            stop_bits=CONTROLLER_STOP_BITS,
            flow_control=CONTROLLER_FLOW_CONTROL,
        )

    handler = RequestHandler(
        resource_name,
        interval_ms=REQUEST_INTERVAL_MS,
        **resource_kwargs,
    )
    handler.open()
    return handler


def _is_serial_resource(resource_name: str) -> bool:
    return resource_name.upper().startswith("ASRL")
