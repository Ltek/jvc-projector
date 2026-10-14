"""Protocol-level tests against the fake projector (no Home Assistant needed)."""

from __future__ import annotations

import asyncio
from hashlib import sha256

import pytest

from custom_components.jvc_projector_ha.jvcprojector import connection, projector
from custom_components.jvc_projector_ha.jvcprojector.device import hash_password
from custom_components.jvc_projector_ha.jvcprojector.error import (
    JvcProjectorAuthError,
    JvcProjectorConnectError,
    JvcProjectorTimeoutError,
)
from custom_components.jvc_projector_ha.jvcprojector.projector import JvcProjector
from tests.fake_projector import FakeProjector, powered_on


def run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


async def _setup(**kw) -> tuple[FakeProjector, JvcProjector]:
    fake = await FakeProjector(refs=powered_on(), **kw).start()
    pj = JvcProjector("127.0.0.1", port=fake.port, timeout=0.5, password=fake.password)
    return fake, pj


def test_state_and_info():
    async def go():
        fake, pj = await _setup()
        await pj.connect(get_info=True)
        assert pj.mac == "E0DADC0A1B2C"
        assert pj.model_code == "ILAFPJ -- B8A1"
        assert pj.version == "0300PJ"
        assert await pj.get_state() == {
            "power": "on",
            "input": "hdmi1",
            "source": "signal",
        }
        assert await pj.poll_ref("IFIS") == "4k_3840_24"
        assert await pj.poll_ref("IFCM") == "bt2020_ncl"
        assert await pj.poll_ref("PMAT") == "hdr10"
        assert await pj.poll_ref("IFLT") == "1234"
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_standby_skips_input_and_signal():
    async def go():
        fake, pj = await _setup()
        fake.refs["PW"] = "0"
        state = await pj.get_state()
        assert state["power"] == "standby"
        assert fake.codes("?") == ["PW"]
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_password_plain_and_prehashed():
    async def go():
        fake = await FakeProjector(refs=powered_on(), password="MyPassword").start()
        for pw in ("MyPassword", sha256(b"MyPasswordJVCKWPJ").hexdigest()):
            pj = JvcProjector("127.0.0.1", port=fake.port, timeout=0.5, password=pw)
            assert (await pj.get_state())["power"] == "on"
            await pj.disconnect()
        bad = JvcProjector("127.0.0.1", port=fake.port, timeout=0.5, password="nope")
        with pytest.raises(JvcProjectorAuthError):
            await bad.get_state()
        await fake.stop()

    run(go())


def test_hash_password():
    plain = "MyPassword"
    hashed = sha256(b"MyPasswordJVCKWPJ").hexdigest()
    assert hash_password(plain) == hashed
    assert hash_password(hashed) == hashed


def test_timeout_raises_and_does_not_desync():
    """A late reply must never be taken as the answer to the next command."""

    async def go():
        fake, pj = await _setup()
        fake.delays["PMPM"] = 0.8  # longer than the 0.5 s timeout
        with pytest.raises(JvcProjectorTimeoutError):
            await pj.poll_ref("PMPM")
        assert await pj.poll_ref("PMDC") == "balanced"
        assert await pj.poll_ref("IFIS") == "4k_3840_24"
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_unanswered_operation_raises():
    async def go():
        fake, pj = await _setup()
        fake.silent.add("PMLL")
        with pytest.raises(JvcProjectorTimeoutError):
            await pj.op("PMLL1")
        await pj.op("PMDC1")  # connection recovers
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_user_command_jumps_ahead_of_poll():
    """A remote key waits for at most the one poll command already in flight."""

    async def go():
        fake, pj = await _setup()
        for code in ("PMPM", "PMDC", "PMCV", "IFIS", "PMAT", "IFCM"):
            fake.delays[code] = 0.15

        async def poll():
            for code in ("PMPM", "PMDC", "PMCV", "IFIS", "PMAT", "IFCM"):
                await pj.poll_ref(code)

        task = asyncio.create_task(poll())
        await asyncio.sleep(0.05)  # poll is now on its first command
        await pj.remote("732E")
        await pj.remote("7301")
        await task

        codes = fake.codes()
        first_key = codes.index("RC732E")
        assert first_key <= 1, codes
        assert codes[first_key + 1] == "RC7301", codes
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_connection_reused_for_a_burst():
    async def go():
        fake, pj = await _setup()
        for _ in range(5):
            await pj.remote("7301")
        assert fake.connections == 1
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_refused_connection_is_connect_error():
    async def go():
        fake, pj = await _setup()
        await fake.stop()
        await asyncio.sleep(0.05)
        with pytest.raises(JvcProjectorConnectError):
            await pj.get_state()

    run(go())


def test_is_ip_address():
    assert connection.is_ip_address("192.168.1.20")
    assert connection.is_ip_address("::1")
    assert not connection.is_ip_address("projector.local")


def test_resolve_localhost_without_aiodns():
    assert run(connection.resolve("localhost")) == "127.0.0.1"
    assert run(connection.resolve("10.0.0.5")) == "10.0.0.5"


def test_hostname_is_re_resolved_after_a_failure(monkeypatch):
    """A changed DHCP address is picked up without reloading the integration."""

    async def go():
        fake, _ = await _setup()
        answers = ["10.255.255.1", "127.0.0.1"]  # first: stale address
        calls: list[str] = []

        async def fake_resolve(host: str) -> str:
            calls.append(host)
            return answers[min(len(calls), len(answers)) - 1]

        monkeypatch.setattr(projector, "resolve", fake_resolve)
        pj = JvcProjector("jvc.lan", port=fake.port, timeout=0.3)
        with pytest.raises(JvcProjectorConnectError):
            await pj.get_state()
        assert (await pj.get_state())["power"] == "on"
        assert calls == ["jvc.lan", "jvc.lan"]
        assert pj.ip == "127.0.0.1"
        await pj.disconnect()
        await fake.stop()

    run(go())


def test_operation_timeout_override_for_lens_moves():
    """Installation mode ACKs only after the lens stops; it gets a longer wait."""

    async def go():
        fake, pj = await _setup()
        fake.delays["!INML"] = 0.8  # > the 0.5 s default timeout
        await pj.op("INML2", timeout=2)
        assert await pj.poll_ref("INML") == "memory_3"
        await pj.disconnect()
        await fake.stop()

    run(go())
