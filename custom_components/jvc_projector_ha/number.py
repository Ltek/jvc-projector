"""Number platform for JVC Projector (2024 D-ILA LAN Spec)."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JVCConfigEntry
from .coordinator import JvcProjectorDataUpdateCoordinator
from .entity import JvcProjectorEntity
from .jvcprojector import command, const

_LOGGER = logging.getLogger(__name__)

# LD Current Value range mapping (from PMLP spec: Low=109, Med=160, High=219)
LD_CURRENT_MIN = 109  # Minimum LD current value
LD_CURRENT_MAX = 219  # Maximum LD current value


def protocol_to_percent(protocol_value: float) -> int:
    """Map the projector's LD current (109-219) to the 1-100 slider."""
    protocol_value = max(LD_CURRENT_MIN, min(LD_CURRENT_MAX, protocol_value))
    return round(
        (protocol_value - LD_CURRENT_MIN) / (LD_CURRENT_MAX - LD_CURRENT_MIN) * 99 + 1
    )


def percent_to_protocol(value: float) -> int:
    """Map the 1-100 slider to the projector's LD current (109-219)."""
    value = max(1, min(100, value))
    return round(LD_CURRENT_MIN + (value - 1) / 99 * (LD_CURRENT_MAX - LD_CURRENT_MIN))


@dataclass(frozen=True, kw_only=True)
class JVCNumberEntityDescription(NumberEntityDescription):
    """Describe JVC number entity."""

    command_code: str


JVC_NUMBERS = (
    JVCNumberEntityDescription(
        key=const.PMCV,
        translation_key="jvc_ld_power",
        command_code=command.PMCV,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.AUTO,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JVCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up JVC Projector number entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        JvcNumber(coordinator, description) for description in JVC_NUMBERS
    )


class JvcNumber(JvcProjectorEntity, NumberEntity):
    """Laser (LD) power for JVC Projector (2024 LAN spec)."""

    entity_description: JVCNumberEntityDescription
    _requires_on = True

    def __init__(
        self,
        coordinator: JvcProjectorDataUpdateCoordinator,
        description: JVCNumberEntityDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value (1-100)."""
        raw_value = self.coordinator.data.get(self.entity_description.key)
        if raw_value is None:
            return None
        try:
            return protocol_to_percent(float(raw_value))
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Invalid %s value: %s", self.entity_description.key, raw_value
            )
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the laser power."""
        protocol_value = percent_to_protocol(value)
        await self._run(
            "Setting laser power",
            self.device.op(
                f"{self.entity_description.command_code}{protocol_value:04X}"
            ),
        )
        self.coordinator.set_optimistic(**{self.entity_description.key: protocol_value})
