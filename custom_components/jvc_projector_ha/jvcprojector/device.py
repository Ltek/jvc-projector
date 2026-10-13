"""Module for representing a JVC Projector device."""

from __future__ import annotations

import asyncio
import contextlib
from hashlib import sha256
import logging
import re
from time import monotonic

from . import const
from .command import (
    AUTH_SALT,
    END,
    HEAD_ACK,
    HEAD_LEN,
    HEAD_OP,
    HEAD_REF,
    HEAD_RES,
    PJACK,
    PJNAK,
    PJNG,
    PJOK,
    PJREQ,
    JvcCommand,
)
from .connection import JvcConnection
from .error import (
    JvcProjectorAuthError,
    JvcProjectorCommandError,
    JvcProjectorConnectError,
    JvcProjectorTimeoutError,
)

# Keep the socket open this long after the last command, so a burst of commands
# (a poll, or a held remote key) reuses one connection instead of reconnecting.
KEEPALIVE_TTL = 2

# Delay between commands to prevent overwhelming the projector
COMMAND_THROTTLE_DELAY = 0.1  # seconds

# The projector refuses a new connection that comes too soon after the last one.
RECONNECT_GUARD = 0.75  # seconds

# Attempts when the projector refuses the connection or answers PJ_NG (busy).
# Kept short: a refused projector should fail fast, not stall every command.
CONNECT_RETRIES = 5

# Regex to match a SHA256 hash (64 hex characters)
SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")

_LOGGER = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Return the network password as the projector expects it.

    A 64-character hex string is taken as already hashed. Anything else is
    hashed as SHA-256(password + "JVCKWPJ").
    """
    if SHA256_PATTERN.match(password):
        return password
    return sha256(f"{password}{AUTH_SALT}".encode()).hexdigest()


class JvcDevice:
    """Class for representing a JVC Projector device."""

    def __init__(
        self, ip: str, port: int, timeout: float, password: str | None = None
    ) -> None:
        """Initialize class."""
        self._conn = JvcConnection(ip, port, timeout)
        self._timeout = timeout

        self._auth = hash_password(password).encode() if password else b""
        self._auth_type = (
            "none"
            if not password
            else "pre-hashed"
            if SHA256_PATTERN.match(password)
            else "plaintext"
        )
        self._auth_logged = False

        self._lock = asyncio.Lock()
        self._keepalive: asyncio.Task | None = None
        self._last: float = 0.0

    @property
    def ip(self) -> str:
        """Return the IP address this device connects to."""
        return self._conn.ip

    async def send(self, cmds: list[JvcCommand]) -> None:
        """Send commands to device.

        Any failure drops the connection so the next command starts clean.
        """
        async with self._lock:
            # Treat status refreshes with special handling
            is_refresh = len(cmds) > 1 and cmds[0].is_ref and cmds[0].is_power

            if self._keepalive:
                self._keepalive.cancel()
                self._keepalive = None

            ok = False
            try:
                if not self._conn.is_connected():
                    await self._connect()

                for cmd in cmds:
                    await self._send(cmd)
                    # Throttle since some projectors dont like back to back commands
                    await asyncio.sleep(COMMAND_THROTTLE_DELAY)
                    # If device is not powered on, skip remaining commands
                    if is_refresh and cmds[0].response != const.ON:
                        break
                ok = True
            finally:
                if ok:
                    # Delay disconnect to keep connection alive.
                    self._keepalive = asyncio.create_task(
                        self._disconnect(KEEPALIVE_TTL)
                    )
                else:
                    await self._disconnect()

    async def _connect(self) -> None:
        """Open the socket and run the PJ_OK / PJREQ / PJACK handshake."""
        if not self._auth_logged and self._auth:
            _LOGGER.debug(
                "Using %s password for authentication",
                "pre-hashed SHA-256"
                if self._auth_type == "pre-hashed"
                else "plaintext",
            )
            self._auth_logged = True

        elapsed = monotonic() - self._last
        if elapsed < RECONNECT_GUARD:
            await asyncio.sleep(RECONNECT_GUARD - elapsed)

        retries = 0
        while retries < CONNECT_RETRIES:
            try:
                _LOGGER.debug("Connecting to %s", self._conn.ip)
                await self._conn.connect()
            except ConnectionRefusedError:
                retries += 1
                _LOGGER.debug("Connection refused, retry %d", retries)
                if retries < CONNECT_RETRIES:
                    await asyncio.sleep(0.2 * retries)
                continue
            except (TimeoutError, OSError) as err:
                raise JvcProjectorConnectError(
                    f"Cannot connect to {self._conn.ip}: {err or 'timeout'}"
                ) from err

            try:
                data = await self._conn.read(len(PJOK))
            except TimeoutError as err:
                await self._conn.disconnect()
                raise JvcProjectorConnectError("Handshake init timeout") from err

            _LOGGER.debug("Handshake received %s", data)

            if data == PJNG:
                _LOGGER.debug("Handshake retrying on busy")
                await self._conn.disconnect()
                retries += 1
                await asyncio.sleep(0.25 * retries)
                continue

            if data != PJOK:
                await self._conn.disconnect()
                raise JvcProjectorCommandError("Handshake init invalid")

            break
        else:
            raise JvcProjectorConnectError(
                f"{self._conn.ip} refused the connection or stayed busy"
            )

        _LOGGER.debug("Handshake sending '%s'", PJREQ.decode())

        # Send PJREQ with password if set
        if self._auth:
            await self._conn.write(PJREQ + b"_" + self._auth)
        else:
            await self._conn.write(PJREQ)

        try:
            data = await self._conn.read(len(PJACK))
        except TimeoutError as err:
            await self._conn.disconnect()
            raise JvcProjectorConnectError("Handshake ack timeout") from err

        _LOGGER.debug("Handshake received %s", data)

        if data == PJNAK:
            await self._conn.disconnect()
            _LOGGER.error("Projector at %s rejected the password", self._conn.ip)
            raise JvcProjectorAuthError

        if data != PJACK:
            await self._conn.disconnect()
            raise JvcProjectorCommandError("Handshake ack invalid")

        self._last = monotonic()

    async def connect(self) -> None:
        """Open a connection now (used to validate host/password)."""
        async with self._lock:
            if not self._conn.is_connected():
                await self._connect()

    async def _send(self, cmd: JvcCommand) -> None:
        """Send one command and read its ACK (and reply, for a reference)."""
        assert self._conn.is_connected()
        assert len(cmd.code) >= 2

        code = cmd.code.encode()
        data = (HEAD_REF if cmd.is_ref else HEAD_OP) + code + END

        _LOGGER.debug(
            "Sending %s '%s' (%s)", "ref" if cmd.is_ref else "op", cmd.code, data
        )
        await self._conn.write(data)

        timeout = cmd.timeout or self._timeout
        try:
            data = await self._conn.readline(timeout)
        except TimeoutError as err:
            raise JvcProjectorTimeoutError(
                f"No answer to '{cmd.code}' within {timeout:g} s"
            ) from err

        _LOGGER.debug("Received ack %s", data)

        if not data.startswith(HEAD_ACK + code[0:2]):
            raise JvcProjectorCommandError(
                f"Response ack invalid '{data!r}' for '{cmd.code}'"
            )

        if cmd.is_ref:
            try:
                data = await self._conn.readline()
            except TimeoutError as err:
                raise JvcProjectorTimeoutError(
                    f"No reply to '{cmd.code}' within {self._timeout:g} s"
                ) from err

            _LOGGER.debug("Received ref %s (%s)", data[HEAD_LEN + 2 : -1], data)

            if not data.startswith(HEAD_RES + code[0:2]):
                raise JvcProjectorCommandError(
                    f"Ref ack invalid '{data!r}' for '{cmd.code}'"
                )

            try:
                cmd.response = data[HEAD_LEN + 2 : -1].decode()
            except UnicodeDecodeError:
                cmd.response = data.hex()
                _LOGGER.debug("Failed to decode response '%s'", data)

        cmd.ack = True

    async def disconnect(self) -> None:
        """Disconnect from device."""
        if self._keepalive:
            self._keepalive.cancel()
            self._keepalive = None
        await self._disconnect()

    async def _disconnect(self, delay: float = 0) -> None:
        """Disconnect from device (optionally after a delay)."""
        if delay:
            await asyncio.sleep(delay)
            # Close only if no command grabbed the connection meanwhile.
            if self._lock.locked():
                return
        self._keepalive = None
        if self._conn.is_connected():
            with contextlib.suppress(Exception):
                await self._conn.disconnect()
            self._last = monotonic()
            _LOGGER.debug("Disconnected")
