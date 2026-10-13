"""Module for representing a JVC Projector network connection."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket

from .error import JvcProjectorConnectError


class JvcConnection:
    """Class for representing a JVC Projector network connection."""

    def __init__(self, ip: str, port: int, timeout: float):
        """Initialize class."""
        self._ip = ip
        self._port = port
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    @property
    def ip(self) -> str:
        """Return ip address."""
        return self._ip

    @property
    def port(self) -> int:
        """Return port."""
        return self._port

    def is_connected(self) -> bool:
        """Return if connected to device."""
        return self._reader is not None and self._writer is not None

    async def connect(self) -> None:
        """Connect to device."""
        assert self._reader is None and self._writer is None
        conn = asyncio.open_connection(self._ip, self._port)
        self._reader, self._writer = await asyncio.wait_for(conn, timeout=self._timeout)

    async def read(self, n: int) -> bytes:
        """Read exactly n bytes from device (raises on EOF)."""
        assert self._reader
        try:
            return await asyncio.wait_for(
                self._reader.readexactly(n), timeout=self._timeout
            )
        except asyncio.IncompleteReadError as err:
            raise JvcProjectorConnectError("Connection closed by projector") from err

    async def readline(self) -> bytes:
        """Read all bytes up to newline from device (raises on EOF)."""
        assert self._reader
        data = await asyncio.wait_for(self._reader.readline(), timeout=self._timeout)
        if not data:
            raise JvcProjectorConnectError("Connection closed by projector")
        return data

    async def write(self, data: bytes) -> None:
        """Write data to device."""
        assert self._writer
        try:
            self._writer.write(data)
            await self._writer.drain()
        except (ConnectionError, OSError) as err:
            raise JvcProjectorConnectError(f"Write failed: {err}") from err

    async def disconnect(self) -> None:
        """Disconnect from device."""
        writer = self._writer
        self._writer = None
        self._reader = None
        if writer:
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), timeout=1)


def is_ip_address(host: str) -> bool:
    """Return True if host is an IPv4/IPv6 literal (no DNS lookup needed)."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def resolve(host: str) -> str:
    """Resolve hostname to an IPv4 address.

    Uses the event loop's resolver, so no extra dependency (aiodns) is needed.
    """
    if is_ip_address(host):
        return host
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, None, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except (socket.gaierror, OSError) as err:
        raise JvcProjectorConnectError(f"Failed to resolve host {host}") from err
    if not infos:
        raise JvcProjectorConnectError(f"Failed to resolve host {host}")
    return str(infos[0][4][0])
