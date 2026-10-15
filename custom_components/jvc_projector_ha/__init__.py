"""The jvc_projector_ha integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .coordinator import JvcProjectorDataUpdateCoordinator
from .jvcprojector.error import (
    JvcProjectorAuthError,
    JvcProjectorConnectError,
    JvcProjectorError,
)
from .jvcprojector.projector import JvcProjector
from .options import Timing

_LOGGER = logging.getLogger(__name__)

type JVCConfigEntry = ConfigEntry[JvcProjectorDataUpdateCoordinator]

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.REMOTE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

SETUP_TIMEOUT = 30  # seconds


async def async_setup_entry(hass: HomeAssistant, entry: JVCConfigEntry) -> bool:
    """Set up integration from a config entry."""
    host = entry.data[CONF_HOST]
    timing = Timing.from_options(entry.options)

    device = JvcProjector(
        host=host,
        port=entry.data[CONF_PORT],
        password=entry.data.get(CONF_PASSWORD),
        timeout=timing.response_timeout,
    )

    try:
        _LOGGER.debug("Setting up JVC Projector at %s", host)
        await asyncio.wait_for(device.connect(get_info=True), timeout=SETUP_TIMEOUT)
    except TimeoutError as err:
        await device.disconnect()
        raise ConfigEntryNotReady(f"Connection timeout to {host}") from err
    except JvcProjectorAuthError as err:
        await device.disconnect()
        raise ConfigEntryAuthFailed("Password authentication failed") from err
    except (JvcProjectorConnectError, JvcProjectorError) as err:
        await device.disconnect()
        raise ConfigEntryNotReady(f"Unable to connect to {host}: {err}") from err

    coordinator = JvcProjectorDataUpdateCoordinator(hass, entry, device, timing)
    entry.runtime_data = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await device.disconnect()
        raise

    async def disconnect_on_stop(event: Event) -> None:
        """Disconnect when Home Assistant stops."""
        await device.disconnect()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, disconnect_on_stop)
    )
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _options_updated(hass: HomeAssistant, entry: JVCConfigEntry) -> None:
    """Apply changed timing options by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: JVCConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.device.disconnect()
    return unload_ok
