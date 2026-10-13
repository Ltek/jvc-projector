"""Remote platform for JVC Projector (2024 LAN Spec)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging
from time import monotonic
from typing import Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JVCConfigEntry
from .entity import JvcProjectorEntity
from .jvcprojector import const
from .jvcprojector.const import REMOTE_BUTTON_MAP

_LOGGER = logging.getLogger(__name__)

# Minimal anti-spam protection (only applies to back-to-back commands)
COMMAND_GUARD = 0.15  # remote key presses
POWER_COMMAND_GUARD = 0.75  # only if user double-taps power

_HEX = set("0123456789ABCDEFabcdef")


def resolve_key(cmd: str) -> tuple[str, str]:
    """Return (name, code) for a button name, REMOTE_* name or 4-digit hex code."""
    lower = cmd.strip().lower()
    if lower.startswith("remote_"):
        lower = lower[7:]
    if lower in REMOTE_BUTTON_MAP:
        return lower, REMOTE_BUTTON_MAP[lower]
    if len(lower) == 4 and set(lower) <= _HEX:
        return f"raw({lower.upper()})", lower.upper()
    raise ServiceValidationError(
        f"Unknown JVC remote command '{cmd}'. Use a button name "
        f"({', '.join(REMOTE_BUTTON_MAP)}) or a 4-digit hex code."
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JVCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the JVC Projector remote entity."""
    async_add_entities([JvcProjectorRemote(entry.runtime_data)])


class JvcProjectorRemote(JvcProjectorEntity, RemoteEntity):
    """JVC Projector remote control (2024 LAN spec)."""

    _attr_name = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the remote."""
        super().__init__(*args, **kwargs)
        self._last_command_time: float | None = None

    @property
    def is_on(self) -> bool:
        """Return True if projector is on or warming."""
        return self.coordinator.data.get(const.POWER) in (const.ON, const.WARMING)

    async def _guard_if_needed(self, min_delay: float) -> None:
        """Delay only if the previous command was very recent."""
        if self._last_command_time is not None:
            elapsed = monotonic() - self._last_command_time
            if elapsed < min_delay:
                await asyncio.sleep(min_delay - elapsed)
        self._last_command_time = monotonic()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the projector on."""
        await self._guard_if_needed(POWER_COMMAND_GUARD)
        await self._run("Power on", self.device.power_on())
        self.coordinator.set_optimistic(**{const.POWER: const.WARMING})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the projector off."""
        await self._guard_if_needed(POWER_COMMAND_GUARD)
        await self._run("Power off", self.device.power_off())
        self.coordinator.set_optimistic(**{const.POWER: const.COOLING})
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send remote control key presses.

        Each command is a button name (``menu``, ``up``, ``ok`` …), a
        ``REMOTE_*`` constant name, or a raw 4-digit hex code. ``num_repeats``
        and ``delay_secs`` are honoured, so a held key can be sent as one call.
        """
        keys = [resolve_key(cmd) for cmd in command]  # validate all first
        num_repeats = max(1, int(kwargs.get(ATTR_NUM_REPEATS, 1)))
        delay = float(kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS))

        for repeat in range(num_repeats):
            if repeat and delay > 0:
                await asyncio.sleep(delay)
            for name, code in keys:
                await self._guard_if_needed(COMMAND_GUARD)
                _LOGGER.debug("Sending remote key %s (%s)", name, code)
                await self._run(f"Remote key '{name}'", self.device.remote(code))
