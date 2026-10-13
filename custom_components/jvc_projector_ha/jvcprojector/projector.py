"""Module for interacting with a JVC Projector."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
import logging

from . import command, const
from .command import JvcCommand
from .connection import is_ip_address, resolve
from .device import JvcDevice
from .error import JvcProjectorConnectError, JvcProjectorError

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 20554
# Per-read timeout. A healthy projector answers in well under a second; a long
# timeout only makes every queued command wait longer when it does not.
DEFAULT_TIMEOUT = 5.0


class JvcProjector:
    """Class for interacting with a JVC Projector.

    User commands (remote keys, power, settings) take priority over status
    polling: while one is waiting, :meth:`poll_ref` holds back, so a key press
    waits for at most the one poll command already on the wire.
    """

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        password: str | None = None,
    ) -> None:
        """Initialize class."""
        self._host = host
        self._port = port
        self._timeout = timeout
        self._password = password

        self._device: JvcDevice | None = None
        self._ip: str = ""
        self._model: str = ""
        self._mac: str = ""
        self._version: str = ""

        # Re-resolve the hostname before the next connection (set after a
        # connection failure, so a changed DHCP address is picked up).
        self._resolve_needed = True

        # Priority gate: number of user commands waiting or running.
        self._user_active = 0
        self._user_idle = asyncio.Event()
        self._user_idle.set()

    @property
    def ip(self) -> str:
        """Returns ip."""
        if not self._ip:
            raise JvcProjectorError("ip not initialized")
        return self._ip

    @property
    def host(self) -> str:
        """Returns host."""
        return self._host

    @property
    def port(self) -> int:
        """Returns port."""
        return self._port

    @property
    def model(self) -> str:
        """Returns model name."""
        if not self._mac:
            raise JvcProjectorError("model not initialized")
        return self._model

    @property
    def model_code(self) -> str | None:
        """Return the raw model code (MD), or None if not read yet."""
        if not self._model or self._model == "(unknown)":
            return None
        return self._model

    @property
    def mac(self) -> str:
        """Returns mac address."""
        if not self._mac:
            raise JvcProjectorError("mac address not initialized")
        return self._mac

    @property
    def version(self) -> str | None:
        """Get device software version."""
        return self._version or None

    async def _ensure_device(self) -> JvcDevice:
        """Return the device, (re)resolving the host when needed."""
        if self._device is None or self._resolve_needed:
            ip = await resolve(self._host)
            self._resolve_needed = False
            if self._device is None or ip != self._device.ip:
                if self._device is not None:
                    _LOGGER.info(
                        "%s now resolves to %s (was %s)", self._host, ip, self._ip
                    )
                    await self._device.disconnect()
                self._ip = ip
                self._device = JvcDevice(ip, self._port, self._timeout, self._password)
        return self._device

    async def connect(self, get_info: bool = False) -> None:
        """Connect to device and optionally read model and MAC address."""
        device = await self._ensure_device()
        try:
            await device.connect()
        except JvcProjectorConnectError:
            self._mark_unreachable()
            raise
        if get_info:
            await self.get_info()

    def _mark_unreachable(self) -> None:
        """Re-resolve the host on the next attempt (hostnames only)."""
        if not is_ip_address(self._host):
            self._resolve_needed = True

    async def disconnect(self) -> None:
        """Disconnect from device (the device object is kept for reuse)."""
        if self._device:
            await self._device.disconnect()

    async def get_info(self) -> dict[str, str]:
        """Get device info."""
        model = JvcCommand(command.MODEL, True)
        mac = JvcCommand(command.MAC, True)
        await self._send([model, mac])

        if mac.response is None:
            raise JvcProjectorError("Mac address not available")

        if model.response is None:
            model.response = "(unknown)"

        self._model = model.response
        self._mac = mac.response

        return {"model": self._model, "mac": self._mac}

    async def get_state(self) -> dict[str, str | None]:
        """Get power, input and signal (input/signal only when powered on)."""
        await self._wait_for_user_commands()
        pwr = JvcCommand(command.POWER, True)
        inp = JvcCommand(command.INPUT, True)
        src = JvcCommand(command.SOURCE, True)
        res = await self._send([pwr, inp, src])
        return {
            "power": res[0] or None,
            "input": res[1] or const.NOSIGNAL,
            "source": res[2] or const.NOSIGNAL,
        }

    async def get_version(self) -> str | None:
        """Get device software version."""
        return await self.ref(command.VERSION)

    async def test(self) -> bool:
        """Run test command."""
        cmd = JvcCommand(f"{command.TEST}")
        await self._send([cmd])
        return cmd.ack

    async def power_on(self) -> None:
        """Run power on command."""
        await self.op(f"{command.POWER}1")

    async def power_off(self) -> None:
        """Run power off command."""
        await self.op(f"{command.POWER}0")

    async def remote(self, code: str) -> None:
        """Run remote code command."""
        await self.op(f"{command.REMOTE}{code}")

    async def op(self, code: str, timeout: float | None = None) -> None:
        """Send an operation (a user command; takes priority over polling)."""
        async with self.user_command():
            await self._send([JvcCommand(code, False, timeout)])

    async def ref(self, code: str) -> str | None:
        """Send a reference (query) right away."""
        return (await self._send([JvcCommand(code, True)]))[0]

    async def poll_ref(self, code: str) -> str | None:
        """Send a reference for status polling; waits for user commands first."""
        await self._wait_for_user_commands()
        return await self.ref(code)

    @contextlib.asynccontextmanager
    async def user_command(self) -> AsyncIterator[None]:
        """Mark a user command as pending so polling yields to it."""
        self._user_active += 1
        self._user_idle.clear()
        try:
            yield
        finally:
            self._user_active -= 1
            if self._user_active == 0:
                self._user_idle.set()

    async def _wait_for_user_commands(self) -> None:
        """Wait until no user command is pending."""
        await self._user_idle.wait()

    async def _send(self, cmds: list[JvcCommand]) -> list[str | None]:
        """Send commands to the device (connecting on demand)."""
        device = await self._ensure_device()
        try:
            await device.send(cmds)
        except JvcProjectorConnectError:
            self._mark_unreachable()
            raise
        return [cmd.response for cmd in cmds]
