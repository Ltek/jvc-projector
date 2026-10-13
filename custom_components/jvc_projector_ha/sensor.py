"""Sensor platform for JVC Projector (2024 D-ILA LAN Spec)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JVCConfigEntry
from .const import decode_model
from .coordinator import JvcProjectorDataUpdateCoordinator
from .entity import JvcProjectorEntity
from .jvcprojector import command, const


def _formatter_values(pattern: str) -> list[str]:
    """Return the state values a command.py formatter can produce."""
    fmt = command.JvcCommand.formatters[pattern]
    values = fmt.values() if isinstance(fmt, dict) else fmt
    return [v for v in values if v is not None]


SOURCE_DISPLAY_OPTIONS = _formatter_values("IFIS(..)")
COLORIMETRY_OPTIONS = _formatter_values("IFCM(.)")
CONTENT_TYPE_OPTIONS = _formatter_values("PMAT(.)")

POWERED_DOWN = (const.STANDBY, const.COOLING)


@dataclass(frozen=True, kw_only=True)
class JVCSensorEntityDescription(SensorEntityDescription):
    """Describe JVC sensor entity."""

    # State shown while the projector is in standby or cooling down.
    off_value: str | None = None


JVC_SENSORS = (
    JVCSensorEntityDescription(
        key=const.POWER,
        translation_key="jvc_power_state",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[const.ON, const.STANDBY, const.WARMING, const.COOLING, const.ERROR],
    ),
    JVCSensorEntityDescription(
        key=const.IFIS,
        translation_key="jvc_source_display",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=SOURCE_DISPLAY_OPTIONS,
        off_value="no_signal",
    ),
    JVCSensorEntityDescription(
        key=const.IFIN,
        translation_key="jvc_input_display",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        options=[const.HDMI1, const.HDMI2],
    ),
    JVCSensorEntityDescription(
        key=const.auto_content_type,
        translation_key="jvc_auto_content_type",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=CONTENT_TYPE_OPTIONS,
    ),
    JVCSensorEntityDescription(
        key=const.IFCM,
        translation_key="jvc_colorimetry",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=COLORIMETRY_OPTIONS,
        off_value="no_data",
    ),
    JVCSensorEntityDescription(
        key=const.MODEL,
        translation_key="jvc_model",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

HOURS_SENSOR = SensorEntityDescription(
    key=const.IFLT,
    translation_key="jvc_light_source_time",
    device_class=SensorDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.HOURS,
    state_class=SensorStateClass.TOTAL_INCREASING,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JVCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up JVC Projector sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        JvcSensor(coordinator, description) for description in JVC_SENSORS
    ]
    entities.append(JvcHoursSensor(coordinator, HOURS_SENSOR))
    async_add_entities(entities)


class JvcSensor(JvcProjectorEntity, SensorEntity):
    """Sensor entity for JVC Projector (2024 LAN spec)."""

    entity_description: JVCSensorEntityDescription

    def __init__(
        self,
        coordinator: JvcProjectorDataUpdateCoordinator,
        description: JVCSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"

    @property
    def native_value(self) -> str | None:
        """Return the sensor value."""
        description = self.entity_description
        if (
            description.off_value is not None
            and self.coordinator.data.get(const.POWER) in POWERED_DOWN
        ):
            return description.off_value

        value = self.coordinator.data.get(description.key)
        if value is None:
            return None
        if description.key == const.MODEL:
            return decode_model(value)
        if description.options is not None and value not in description.options:
            return None
        return value


class JvcHoursSensor(JvcProjectorEntity, RestoreSensor):
    """Light-source hours.

    The projector only reports hours while it is on. The last value is kept in
    standby (it can't change then) and restored after a Home Assistant restart.
    """

    def __init__(
        self,
        coordinator: JvcProjectorDataUpdateCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"
        self._restored: int | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last known value."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            try:
                self._restored = int(float(str(last.native_value)))
            except ValueError:
                self._restored = None

    @property
    def native_value(self) -> int | None:
        """Return hours (live while on, last known otherwise)."""
        value = self.coordinator.data.get(const.IFLT)
        if isinstance(value, int):
            return value
        return self._restored
