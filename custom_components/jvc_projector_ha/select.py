"""Select platform for JVC Projector (2024 D-ILA LAN Spec)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JVCConfigEntry
from .coordinator import JvcProjectorDataUpdateCoordinator
from .entity import JvcProjectorEntity
from .jvcprojector import command, const

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class JVCSelectEntityDescription(SelectEntityDescription):
    """Describe JVC select entity."""

    command_code: str
    # Option -> parameter sent after command_code. Must match the reverse map in
    # jvcprojector/command.py (checked by tests/test_tables.py).
    code_map: dict[str, str] = field(default_factory=dict)
    # Options that can be shown but not set (e.g. HDR processing "HDR10+").
    read_only: frozenset[str] = frozenset()
    # Only available while the source is HDR (HDR10, HDR10+, HLG).
    requires_hdr: bool = False
    # Read timeout for the set command (None = default).
    op_timeout: float | None = None
    # Narrows the options for a model code (MD), e.g. 5 lens memories on NZ500.
    options_fn: Callable[[str | None], list[str]] | None = None


# Picture Mode mapping from internal values to command codes (Table 3-19)
PICTURE_MODE_TO_CODE = {
    "cinema": "01",
    "natural": "03",
    "frame_adapt_hdr": "0B",
    "sdr1": "0C",
    "sdr2": "0D",
    "hdr1": "0E",
    "hdr2": "0F",
    "hlg": "14",
    "hdr10_plus": "15",
    "filmmaker": "17",
    "frame_adapt_hdr2": "18",
    "vivid": "1B",
}

# Input codes (Table 3-6)
INPUT_TO_CODE = {const.HDMI1: "6", const.HDMI2: "7"}

# Dynamic Control mapping from internal values to command codes (Table 3-25)
DYNAMIC_CTRL_TO_CODE = {
    "off": "0",
    "low": "1",
    "high": "2",
    "balanced": "3",
}

# Installation mode (lens memory) — Installation Mode 1-10 ("0"-"9")
INSTALLATION_MODE_TO_CODE = {f"memory_{i}": f"{i - 1:X}" for i in range(1, 11)}

# Models with only five installation modes (NZ500 / NZ700 family, spec CS20242)
FIVE_MEMORY_MODELS = ("D8A1", "D8A2")


def installation_mode_options(model: str | None) -> list[str]:
    """Return the lens memories this model has."""
    options = list(INSTALLATION_MODE_TO_CODE)
    if model and model.strip().endswith(FIVE_MEMORY_MODELS):
        return options[:5]
    return options


ANAMORPHIC_TO_CODE = {"off": "0", "a": "1", "b": "2", "c": "3", "d": "4"}

HDR_PROCESSING_TO_CODE = {
    "hdr10_plus": "0",
    "static": "1",
    "frame_by_frame": "2",
    "scene_by_scene": "3",
}

HDR_LEVEL_TO_CODE = {
    "auto": "0",
    "minus_2": "1",
    "minus_1": "2",
    "zero": "3",
    "plus_1": "4",
    "plus_2": "5",
    "auto_wide": "6",
}

# Picture modes available per content type (from NZ500 manual)
CONTENT_TYPE_PICTURE_MODES = {
    "sdr": ["natural", "cinema", "vivid", "filmmaker", "sdr1", "sdr2"],
    "hdr10_plus": ["hdr10_plus"],
    "hdr10": ["frame_adapt_hdr", "frame_adapt_hdr2", "filmmaker", "hdr1", "hdr2"],
    "hlg": ["hlg"],
}

JVC_SELECTS: tuple[JVCSelectEntityDescription, ...] = (
    JVCSelectEntityDescription(
        key=const.PMPM,
        translation_key="jvc_picture_mode",
        command_code=command.PMPM,
        code_map=PICTURE_MODE_TO_CODE,
        options=list(PICTURE_MODE_TO_CODE),
        entity_category=EntityCategory.CONFIG,
    ),
    JVCSelectEntityDescription(
        key=const.INPUT,
        translation_key="jvc_input_select",
        command_code=command.INPUT,
        code_map=INPUT_TO_CODE,
        options=list(INPUT_TO_CODE),
        entity_category=EntityCategory.CONFIG,
    ),
    JVCSelectEntityDescription(
        key=const.PMDC,
        translation_key="jvc_dynamic_ctrl",
        command_code=command.PMDC,
        code_map=DYNAMIC_CTRL_TO_CODE,
        options=list(DYNAMIC_CTRL_TO_CODE),
        entity_category=EntityCategory.CONFIG,
    ),
    JVCSelectEntityDescription(
        key=const.INML,
        translation_key="jvc_installation_mode",
        command_code=command.INML,
        code_map=INSTALLATION_MODE_TO_CODE,
        options=list(INSTALLATION_MODE_TO_CODE),
        options_fn=installation_mode_options,
        # The projector answers only once the lens has finished moving.
        op_timeout=30,
        entity_category=EntityCategory.CONFIG,
    ),
    JVCSelectEntityDescription(
        key=const.INVS,
        translation_key="jvc_anamorphic",
        command_code=command.INVS,
        code_map=ANAMORPHIC_TO_CODE,
        options=list(ANAMORPHIC_TO_CODE),
        entity_category=EntityCategory.CONFIG,
    ),
    JVCSelectEntityDescription(
        key=const.PMHP,
        translation_key="jvc_hdr_processing",
        command_code=command.PMHP,
        code_map=HDR_PROCESSING_TO_CODE,
        options=list(HDR_PROCESSING_TO_CODE),
        read_only=frozenset({"hdr10_plus"}),
        requires_hdr=True,
        entity_category=EntityCategory.CONFIG,
    ),
    JVCSelectEntityDescription(
        key=const.PMHL,
        translation_key="jvc_hdr_level",
        command_code=command.PMHL,
        code_map=HDR_LEVEL_TO_CODE,
        options=list(HDR_LEVEL_TO_CODE),
        requires_hdr=True,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JVCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up JVC Projector select entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        JvcSelect(coordinator, description) for description in JVC_SELECTS
    )


class JvcSelect(JvcProjectorEntity, SelectEntity):
    """Select entity for JVC Projector (2024 LAN spec)."""

    entity_description: JVCSelectEntityDescription
    _requires_on = True

    def __init__(
        self,
        coordinator: JvcProjectorDataUpdateCoordinator,
        description: JVCSelectEntityDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return if entity is available (HDR settings need an HDR source)."""
        if not super().available:
            return False
        if self.entity_description.requires_hdr:
            content = self.coordinator.data.get(const.auto_content_type)
            return content in const.HDR_CONTENT
        return True

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        if value in self.entity_description.code_map:
            return value
        _LOGGER.debug("Unknown %s value: %s", self.entity_description.key, value)
        return None

    @property
    def options(self) -> list[str]:
        """Return the available options.

        Picture modes are filtered to those valid for the current content type.
        """
        description = self.entity_description
        if description.options_fn is not None:
            return description.options_fn(self.coordinator.data.get(const.MODEL))
        options = list(description.code_map)
        if description.key != const.PMPM:
            return options
        content_type = self.coordinator.data.get(const.auto_content_type)
        filtered = CONTENT_TYPE_PICTURE_MODES.get(content_type or "")
        if not filtered:
            return options
        current = self.coordinator.data.get(const.PMPM)
        if current in options and current not in filtered:
            # HA rejects a state that isn't one of the options.
            return [*filtered, current]
        return filtered

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        description = self.entity_description
        code = description.code_map.get(option)
        if code is None or option not in self.options:
            raise ServiceValidationError(
                f"'{option}' is not a valid option for {description.key}"
            )
        if option in description.read_only:
            raise ServiceValidationError(
                f"'{option}' is set by the projector and can't be selected"
            )
        full_command = f"{self.entity_description.command_code}{code}"
        _LOGGER.debug(
            "Setting %s to %s (%s)", self.entity_description.key, option, full_command
        )
        label = self.name if isinstance(self.name, str) else self.entity_description.key
        await self._run(
            f"Setting {label} to {option}",
            self.device.op(full_command, timeout=description.op_timeout),
        )
        self.coordinator.set_optimistic(**{self.entity_description.key: option})
