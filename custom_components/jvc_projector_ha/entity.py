"""Base Entity for the JVC Projector (2024 LAN Spec)."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME, decode_model
from .coordinator import JvcProjectorDataUpdateCoordinator
from .jvcprojector import const as pj_const
from .jvcprojector.error import (
    JvcProjectorConnectError,
    JvcProjectorError,
    JvcProjectorTimeoutError,
)
from .jvcprojector.projector import JvcProjector


class JvcProjectorEntity(CoordinatorEntity[JvcProjectorDataUpdateCoordinator]):
    """Base class for all JVC Projector entities (2024 spec)."""

    _attr_has_entity_name = True

    # Controls that only work while the projector is on set this to True.
    _requires_on = False

    def __init__(self, coordinator: JvcProjectorDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        self._attr_unique_id = coordinator.unique_id

        device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.unique_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            connections={(CONNECTION_NETWORK_MAC, coordinator.device.mac)},
        )
        raw_model = (coordinator.data or {}).get(pj_const.MODEL)
        if raw_model:
            device_info["model"] = decode_model(raw_model)
        if coordinator.device.version:
            device_info["sw_version"] = coordinator.device.version
        self._attr_device_info = device_info

    @property
    def device(self) -> JvcProjector:
        """Return the underlying projector device."""
        return self.coordinator.device

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        if self._requires_on:
            return self.coordinator.data.get(pj_const.POWER) == pj_const.ON
        return True

    async def _run(self, what: str, command: Awaitable[None]) -> None:
        """Run a projector command; raise a HomeAssistantError if it fails.

        HA shows the error in the Dashboard, instead of the failure only being
        written to the log.
        """
        try:
            await command
        except JvcProjectorTimeoutError as err:
            self.coordinator.note_command_timeout()
            raise HomeAssistantError(
                f"{what}: the projector did not answer ({err}). It may not "
                "support this setting with the current signal or mode, or it "
                "needs longer: see the timeouts under Configure."
            ) from err
        except JvcProjectorConnectError as err:
            raise HomeAssistantError(
                f"{what}: cannot reach the projector ({err})"
            ) from err
        except JvcProjectorError as err:
            raise HomeAssistantError(f"{what} failed: {err}") from err
        # It answered, so a recovery pause (if any) can end now.
        self.coordinator.end_quiet()
