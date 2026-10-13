"""Switch platform for JVC Projector (2024 D-ILA LAN Spec)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JVCConfigEntry
from .coordinator import JvcProjectorDataUpdateCoordinator
from .entity import JvcProjectorEntity
from .jvcprojector import command, const


@dataclass(frozen=True, kw_only=True)
class JVCSwitchEntityDescription(SwitchEntityDescription):
    """Describe a JVC on/off setting."""

    command_code: str


JVC_SWITCHES = (
    JVCSwitchEntityDescription(
        key=const.PMLL,
        translation_key="jvc_low_latency",
        command_code=command.PMLL,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JVCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up JVC Projector switches from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(JvcSwitch(coordinator, d) for d in JVC_SWITCHES)


class JvcSwitch(JvcProjectorEntity, SwitchEntity):
    """An on/off picture setting (projector must be on)."""

    entity_description: JVCSwitchEntityDescription
    _requires_on = True

    def __init__(
        self,
        coordinator: JvcProjectorDataUpdateCoordinator,
        description: JVCSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the setting."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return value == const.ON

    async def _set(self, on: bool) -> None:
        label = self.name if isinstance(self.name, str) else self.entity_description.key
        await self._run(
            f"Turning {label} {'on' if on else 'off'}",
            self.device.op(f"{self.entity_description.command_code}{int(on)}"),
        )
        self.coordinator.set_optimistic(
            **{self.entity_description.key: const.ON if on else const.OFF}
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._set(False)
