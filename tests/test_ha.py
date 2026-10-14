"""End-to-end tests in a real Home Assistant instance against the fake projector."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest

from custom_components.jvc_projector_ha.const import DOMAIN
from custom_components.jvc_projector_ha.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.fake_projector import FakeProjector, powered_on
from tests.ha_harness import home_assistant

REMOTE = "remote.jvc_projector"
SOURCE = "sensor.jvc_projector_source_display"
CONTENT = "sensor.jvc_projector_content_type"
COLORIMETRY = "sensor.jvc_projector_colorimetry"
HOURS = "sensor.jvc_projector_light_source_time"
POWER = "sensor.jvc_projector_power_state"
PICTURE = "select.jvc_projector_picture_mode"
DYNAMIC = "select.jvc_projector_dynamic_control"
LASER = "number.jvc_projector_ld_power"
LENS = "select.jvc_projector_installation_mode"
ANAMORPHIC = "select.jvc_projector_anamorphic"
HDR_PROCESSING = "select.jvc_projector_hdr_processing"
HDR_LEVEL = "select.jvc_projector_hdr_level"
LOW_LATENCY = "switch.jvc_projector_low_latency"
THEATER_OPTIMIZER = "switch.jvc_projector_theater_optimizer"
ESHIFT = "switch.jvc_projector_8k_e_shift"
ECO = "switch.jvc_projector_eco_mode"
CMD = "select.jvc_projector_clear_motion_drive"
MOTION = "select.jvc_projector_motion_enhance"
CONNECTION = "binary_sensor.jvc_projector_connection"
VERSION = "sensor.jvc_projector_software_version"
COLOR_DEPTH = "sensor.jvc_projector_color_depth"
COLOR_SPACE = "sensor.jvc_projector_color_space"
HDR_SIGNAL = "sensor.jvc_projector_hdr_signal"
NZ500 = "ILAFPJ -- D8A2"


async def _add(hass: HomeAssistant, fake: FakeProjector, password: str | None = None):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    data = {CONF_HOST: "127.0.0.1", CONF_PORT: fake.port}
    if password:
        data[CONF_PASSWORD] = password
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], data)
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    return result["result"]


def scenario(
    fn: Callable[[HomeAssistant, FakeProjector], Awaitable[None]],
    refs: dict[str, str] | None = None,
    **fake_kw,
) -> None:
    """Run fn(hass, fake) with the integration set up against a fake projector."""

    async def go():
        fake = await FakeProjector(refs=refs or powered_on(), **fake_kw).start()
        try:
            async with home_assistant() as hass:
                entry = await _add(hass, fake, fake.password)
                try:
                    await fn(hass, fake)
                finally:
                    await hass.async_block_till_done()
                    if entry.state.recoverable and entry.state.name == "LOADED":
                        await hass.config_entries.async_unload(entry.entry_id)
        finally:
            await fake.stop()

    asyncio.run(go())


async def _refresh(hass: HomeAssistant) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, (
        f"{entity_id} missing; have {hass.states.async_entity_ids()}"
    )
    return state.state


def test_setup_creates_entities_with_valid_states():
    async def check(hass, fake):
        assert _state(hass, REMOTE) == "on"
        assert _state(hass, POWER) == "on"
        assert _state(hass, SOURCE) == "4k_3840_24"
        assert _state(hass, CONTENT) == "hdr10"
        assert _state(hass, COLORIMETRY) == "bt2020_ncl"
        assert _state(hass, HOURS) == "1234"
        assert _state(hass, PICTURE) == "hdr1"
        assert _state(hass, DYNAMIC) == "balanced"
        assert _state(hass, LASER) == "47"
        # Picture modes are filtered to HDR10 ones
        assert "hdr1" in hass.states.get(PICTURE).attributes["options"]
        assert "natural" not in hass.states.get(PICTURE).attributes["options"]
        # Remote no longer misuses activities for the key list
        assert "activity_list" not in hass.states.get(REMOTE).attributes

    scenario(check)


def test_send_command_honours_num_repeats():
    async def check(hass, fake):
        start = len(fake.log)
        await hass.services.async_call(
            "remote",
            "send_command",
            {
                "entity_id": REMOTE,
                "command": "up",
                "num_repeats": 3,
                "delay_secs": 0.05,
            },
            blocking=True,
        )
        assert [c for c in fake.codes()[start:] if c.startswith("RC")] == ["RC7301"] * 3

    scenario(check)


def test_unknown_key_is_rejected():
    async def check(hass, fake):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "remote",
                "send_command",
                {"entity_id": REMOTE, "command": "nope"},
                blocking=True,
            )

    scenario(check)


def test_select_is_immediate_and_failures_are_reported():
    async def check(hass, fake):
        t = monotonic()
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": PICTURE, "option": "hdr2"},
            blocking=True,
        )
        assert monotonic() - t < 1.0  # no fixed 2 s wait any more
        assert "PMPM0F" in fake.codes("!")
        assert _state(hass, PICTURE) == "hdr2"

        fake.silent.add("!PMDC")
        with pytest.raises(HomeAssistantError, match="did not answer"):
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": DYNAMIC, "option": "low"},
                blocking=True,
            )
        assert _state(hass, DYNAMIC) == "balanced"

    scenario(check)


def test_laser_power_sets_protocol_value():
    async def check(hass, fake):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": LASER, "value": 100}, blocking=True
        )
        assert "PMCV00DB" in fake.codes("!")
        assert _state(hass, LASER) == "100"

    scenario(check)


def test_remote_key_is_not_stuck_behind_a_poll():
    async def check(hass, fake):
        for code in ("PMPM", "PMDC", "PMCV", "IFIS", "PMAT", "IFCM", "IFIN", "IFLT"):
            fake.delays[code] = 0.3
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        poll = asyncio.create_task(entry.runtime_data.async_refresh())
        await asyncio.sleep(0.4)  # the poll is busy now (≈2.4 s in total)
        t = monotonic()
        await hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": REMOTE, "command": "menu"},
            blocking=True,
        )
        assert monotonic() - t < 0.8, "key press waited for the poll"
        assert not poll.done()
        await poll

    scenario(check)


def test_standby_keeps_hours_and_no_signal_skips_queries():
    async def check(hass, fake):
        fake.refs["SC"] = "0"
        start = len(fake.log)
        await _refresh(hass)
        polled = fake.codes("?")[start:]
        assert "PMAT" not in polled and "IFCM" not in polled and "IFIS" not in polled
        assert _state(hass, SOURCE) == "no_signal"

        fake.refs["PW"] = "0"
        await _refresh(hass)
        assert _state(hass, POWER) == "standby"
        assert _state(hass, REMOTE) == "off"
        assert _state(hass, HOURS) == "1234"
        assert _state(hass, COLORIMETRY) == "no_data"
        assert _state(hass, PICTURE) == "unavailable"

    scenario(check)


def test_power_on_off_is_optimistic():
    async def check(hass, fake):
        await hass.services.async_call(
            "remote", "turn_off", {"entity_id": REMOTE}, blocking=True
        )
        assert "PW0" in fake.codes("!")
        await hass.async_block_till_done()
        assert _state(hass, POWER) in ("cooling", "standby")

    scenario(check)


def test_projector_offline_marks_entities_unavailable():
    async def check(hass, fake):
        await fake.stop()
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        await entry.runtime_data.device.disconnect()
        await _refresh(hass)
        assert _state(hass, REMOTE) == "unavailable"
        assert _state(hass, HOURS) == "unavailable"

    scenario(check)


def test_password_and_reauth():
    async def check(hass, fake):
        assert _state(hass, REMOTE) == "on"
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": entry.entry_id},
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_PASSWORD: "wrong"}
        )
        assert result["errors"] == {"base": "invalid_auth"}
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_PASSWORD: "MyPassword"}
        )
        assert result["type"] == "abort" and result["reason"] == "reauth_successful"
        await hass.async_block_till_done()
        assert entry.data[CONF_PASSWORD] == "MyPassword"
        assert _state(hass, REMOTE) == "on"

    scenario(check, password="MyPassword")


def test_reconfigure_changes_address():
    async def check(hass, fake):
        other = await FakeProjector(refs=powered_on()).start()
        try:
            entry = hass.config_entries.async_entries(DOMAIN)[0]
            flow = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
            )
            result = await hass.config_entries.flow.async_configure(
                flow["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: other.port}
            )
            assert result["reason"] == "reconfigure_successful", result
            await hass.async_block_till_done()
            assert entry.data[CONF_PORT] == other.port
            assert _state(hass, REMOTE) == "on"
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
        finally:
            await other.stop()

    scenario(check)


async def _select(hass, entity_id, option):
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": option},
        blocking=True,
    )


def test_lens_memory_and_anamorphic():
    async def check(hass, fake):
        assert _state(hass, LENS) == "memory_1"
        # NZ500 (D8A2) has five installation modes
        assert hass.states.get(LENS).attributes["options"] == [
            f"memory_{i}" for i in range(1, 6)
        ]
        await _select(hass, LENS, "memory_3")
        assert "INML2" in fake.codes("!")
        assert _state(hass, LENS) == "memory_3"
        with pytest.raises(HomeAssistantError):
            await _select(hass, LENS, "memory_7")

        assert _state(hass, ANAMORPHIC) == "off"
        await _select(hass, ANAMORPHIC, "a")
        assert "INVS1" in fake.codes("!")
        await _refresh(hass)
        assert _state(hass, ANAMORPHIC) == "a"
        assert _state(hass, LENS) == "memory_3"

    scenario(check, refs=powered_on(MD=NZ500))


def test_low_latency_switch():
    async def check(hass, fake):
        assert _state(hass, LOW_LATENCY) == "off"
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LOW_LATENCY}, blocking=True
        )
        assert "PMLL1" in fake.codes("!")
        assert _state(hass, LOW_LATENCY) == "on"

        fake.silent.add("!PMLL")
        with pytest.raises(HomeAssistantError, match="did not answer"):
            await hass.services.async_call(
                "switch", "turn_off", {"entity_id": LOW_LATENCY}, blocking=True
            )
        assert _state(hass, LOW_LATENCY) == "on"

    scenario(check)


def test_hdr_settings_follow_content_type():
    async def check(hass, fake):
        assert _state(hass, HDR_PROCESSING) == "static"
        assert _state(hass, HDR_LEVEL) == "auto"
        await _select(hass, HDR_PROCESSING, "scene_by_scene")
        assert "PMHP3" in fake.codes("!")
        with pytest.raises(HomeAssistantError, match="can't be selected"):
            await _select(hass, HDR_PROCESSING, "hdr10_plus")
        await _select(hass, HDR_LEVEL, "plus_1")
        assert "PMHL4" in fake.codes("!")

        fake.refs["PMAT"] = "1"  # SDR source
        start = len(fake.log)
        await _refresh(hass)
        assert _state(hass, HDR_PROCESSING) == "unavailable"
        assert _state(hass, HDR_LEVEL) == "unavailable"
        assert "PMHP" not in fake.codes("?")[start:]

    scenario(check)


def test_settings_unavailable_in_standby():
    async def check(hass, fake):
        fake.refs["PW"] = "0"
        await _refresh(hass)
        for entity_id in (LENS, ANAMORPHIC, LOW_LATENCY, HDR_PROCESSING):
            assert _state(hass, entity_id) == "unavailable"

    scenario(check)


def test_new_settings_on_an_nz900():
    async def check(hass, fake):
        assert _state(hass, THEATER_OPTIMIZER) == "on"
        assert _state(hass, ESHIFT) == "on"
        assert _state(hass, ECO) == "off"
        assert _state(hass, CMD) == "low"
        assert hass.states.get(CMD).attributes["options"] == [
            "off",
            "low",
            "high",
            "inverse_telecine",
        ]
        assert _state(hass, MOTION) == "off"

        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": THEATER_OPTIMIZER}, blocking=True
        )
        assert "PMNM0" in fake.codes("!")
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": ESHIFT}, blocking=True
        )
        assert "PMUS0" in fake.codes("!")
        await _select(hass, CMD, "inverse_telecine")
        assert "PMCM5" in fake.codes("!")
        await _select(hass, MOTION, "high")
        assert "PMME2" in fake.codes("!")
        await _refresh(hass)
        assert _state(hass, CMD) == "inverse_telecine"
        assert _state(hass, MOTION) == "high"

    scenario(check)


def test_signal_details_version_and_connection():
    async def check(hass, fake):
        assert _state(hass, COLOR_DEPTH) == "10bit"
        assert _state(hass, COLOR_SPACE) == "ycbcr_420"
        assert _state(hass, HDR_SIGNAL) == "smpte_st_2084"
        assert _state(hass, VERSION) == "0300PJ"
        assert _state(hass, CONNECTION) == "on"

        # firmware version on the device page
        device = next(iter(dr.async_get(hass).devices.values()))
        assert device.sw_version == "0300PJ"
        assert device.model == "DLA-NZ900"

        await fake.stop()
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        await entry.runtime_data.device.disconnect()
        await _refresh(hass)
        assert _state(hass, REMOTE) == "unavailable"
        assert _state(hass, CONNECTION) == "off"  # still available, reports off

    scenario(check)


def test_nz500_gets_only_what_it_supports():
    async def check(hass, fake):
        ids = hass.states.async_entity_ids()
        for entity_id in (LOW_LATENCY, THEATER_OPTIMIZER, ESHIFT, MOTION):
            assert entity_id not in ids, entity_id
        assert ECO in ids and CMD in ids
        # NZ500 Clear Motion Drive: off / low (7) / high (6), no inverse telecine
        assert hass.states.get(CMD).attributes["options"] == ["off", "low", "high"]
        assert _state(hass, CMD) == "high"
        await _select(hass, CMD, "low")
        assert "PMCM7" in fake.codes("!")
        await _refresh(hass)
        assert "PMNM" not in fake.codes("?") and "PMUS" not in fake.codes("?")

    scenario(check, refs=powered_on(MD=NZ500, PMCM="6"))


def test_low_latency_disables_cmd_and_dynamic_control():
    async def check(hass, fake):
        assert _state(hass, CMD) == "low"
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LOW_LATENCY}, blocking=True
        )
        assert _state(hass, CMD) == "unavailable"
        assert _state(hass, DYNAMIC) == "unavailable"

    scenario(check)


def test_theater_optimizer_needs_hdr():
    async def check(hass, fake):
        fake.refs["PMAT"] = "1"  # SDR
        await _refresh(hass)
        assert _state(hass, THEATER_OPTIMIZER) == "unavailable"

    scenario(check)


def test_power_on_while_cooling_is_refused():
    async def check(hass, fake):
        fake.refs["PW"] = "2"  # cooling
        await _refresh(hass)
        start = len(fake.log)
        with pytest.raises(HomeAssistantError, match="cooling down"):
            await hass.services.async_call(
                "remote", "turn_on", {"entity_id": REMOTE}, blocking=True
            )
        assert "PW1" not in fake.codes("!")[start:]

        fake.refs["PW"] = "0"  # standby: works
        await _refresh(hass)
        await hass.services.async_call(
            "remote", "turn_on", {"entity_id": REMOTE}, blocking=True
        )
        assert "PW1" in fake.codes("!")

    scenario(check)


def test_missing_version_is_read_later():
    async def check(hass, fake):
        assert _state(hass, VERSION) == "unknown"
        fake.refs["IFSV"] = "0310PJ"
        fake.silent.discard("IFSV")
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        entry.runtime_data._force_slow = True
        await _refresh(hass)
        assert _state(hass, VERSION) == "0310PJ"
        device = next(iter(dr.async_get(hass).devices.values()))
        assert device.sw_version == "0310PJ"

    refs = powered_on()
    del refs["IFSV"]
    scenario(check, refs=refs, silent={"IFSV"})


def test_diagnostics_redacts_password_and_host():
    async def check(hass, fake):
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        diag = await async_get_config_entry_diagnostics(hass, entry)
        assert diag["entry"][CONF_PASSWORD] == "**REDACTED**"
        assert diag["entry"][CONF_HOST] == "**REDACTED**"
        assert diag["projector"]["specification"] == "CS20241"
        assert diag["projector"]["software_version"] == "0300PJ"
        assert diag["coordinator"]["last_update_success"] is True

    scenario(check, password="MyPassword")
