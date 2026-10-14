"""A fake JVC projector speaking the LAN protocol, for tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic

UNIT = b"\x89\x01"


@dataclass
class FakeProjector:
    """TCP server emulating a JVC D-ILA projector (one client at a time)."""

    password: str | None = None
    # Reference code (e.g. "PW", "PMPM") -> raw reply payload (e.g. "1", "03").
    refs: dict[str, str] = field(default_factory=dict)
    # Code prefix -> seconds to wait before answering ("!INML" = operations only).
    delays: dict[str, float] = field(default_factory=dict)
    # Code prefixes the projector never answers ("!PMLL" = operations only).
    silent: set[str] = field(default_factory=set)
    # (monotonic time, "?"|"!", code) for every command received.
    log: list[tuple[float, str, str]] = field(default_factory=list)
    connections: int = 0
    port: int = 0
    _server: asyncio.base_events.Server | None = None

    async def start(self) -> FakeProjector:
        """Start listening on a free localhost port."""
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def codes(self, kind: str | None = None) -> list[str]:
        """Return received codes, optionally only '?' (ref) or '!' (op)."""
        return [c for _, k, c in self.log if kind is None or k == kind]

    def _match(self, table: dict[str, float] | set[str], code: str) -> object:
        for prefix in sorted(table, key=len, reverse=True):
            if code.startswith(prefix):
                return table[prefix] if isinstance(table, dict) else True
        return None

    async def _client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        try:
            writer.write(b"PJ_OK")
            await writer.drain()
            req = await reader.readexactly(5)
            assert req == b"PJREQ", req
            if self.password:
                expected = sha256(f"{self.password}JVCKWPJ".encode()).hexdigest()
                got = (await reader.readexactly(1 + 64)).decode()[1:]
                if got != expected:
                    writer.write(b"PJNAK")
                    await writer.drain()
                    return
            writer.write(b"PJACK")
            await writer.drain()

            while True:
                line = await reader.readline()
                if not line:
                    return
                kind = chr(line[0])
                code = line[3:-1].decode()
                self.log.append((monotonic(), kind, code))
                if self._match(self.silent, code) or self._match(
                    self.silent, kind + code
                ):
                    continue
                delay = self._match(self.delays, kind + code) or self._match(
                    self.delays, code
                )
                if delay:
                    await asyncio.sleep(float(delay))  # type: ignore[arg-type]
                head = code[:2].encode()
                if code == "\0\0":
                    writer.write(b"\x06" + UNIT + b"\0\0\n")
                elif kind == "?":
                    value = self.refs.get(code)
                    if value is None:
                        continue  # unknown ref: no answer, like the real thing
                    writer.write(b"\x06" + UNIT + head + b"\n")
                    writer.write(b"@" + UNIT + head + value.encode() + b"\n")
                else:
                    writer.write(b"\x06" + UNIT + head + b"\n")
                    self._apply(code)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        finally:
            writer.close()

    def _apply(self, code: str) -> None:
        """Make an operation visible to later references."""
        if code.startswith("PW"):
            self.refs["PW"] = code[2:]
        elif code.startswith("RC"):
            return
        else:
            for ref in sorted(self.refs, key=len, reverse=True):
                if code.startswith(ref) and len(ref) >= 2:
                    self.refs[ref] = code[len(ref) :]
                    return


def powered_on(**extra: str) -> dict[str, str]:
    """Reference replies for an NZ900 that is on with a 4K HDR10 signal."""
    refs = {
        # NZ900 family: supports every setting the integration has
        "MD": "ILAFPJ -- B8A1",
        "IFSV": "0300PJ",
        "LSMA": "E0DADC0A1B2C",
        "PW": "1",
        "IP": "6",
        "SC": "1",
        "PMPM": "0E",
        "PMDC": "3",
        "PMCV": "00A0",
        "IFIS": "19",
        "PMAT": "3",
        "IFCM": "9",
        "IFIN": "6",
        "IFLT": "04D2",
        "INML": "0",
        "INVS": "0",
        "PMLL": "0",
        "PMHP": "1",
        "PMHL": "0",
        "PMNM": "1",
        "PMUS": "1",
        "PMCM": "3",
        "PMME": "0",
        "FUEM": "0",
        "IFDC": "1",
        "IFXV": "3",
        "IFHR": "2",
    }
    refs.update(extra)
    return refs
