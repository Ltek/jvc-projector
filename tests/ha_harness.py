"""A minimal real Home Assistant instance for integration tests.

No pytest-homeassistant-custom-component: just HomeAssistant core started in a
temporary config dir, with this integration linked into custom_components/.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
from pathlib import Path
import tempfile

from homeassistant import config_entries, loader
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    category_registry as cr,
    device_registry as dr,
    entity,
    entity_registry as er,
    floor_registry as fr,
    frame,
    issue_registry as ir,
    label_registry as lr,
    restore_state as rs,
    translation,
)
from homeassistant.setup import async_setup_component

INTEGRATION = (
    Path(__file__).resolve().parent.parent / "custom_components" / "jvc_projector_ha"
)


@contextlib.asynccontextmanager
async def home_assistant() -> AsyncIterator[HomeAssistant]:
    """Yield a running HomeAssistant with the integration available."""
    with tempfile.TemporaryDirectory() as config_dir:
        custom = Path(config_dir) / "custom_components"
        custom.mkdir()
        (custom / "jvc_projector_ha").symlink_to(INTEGRATION)

        hass = HomeAssistant(config_dir)
        hass.config.skip_pip = True
        hass.config.skip_pip_packages = []
        frame.async_setup(hass)
        loader.async_setup(hass)
        entity.async_setup(hass)
        translation.async_setup(hass)
        await ar.async_load(hass)
        await cr.async_load(hass)
        await fr.async_load(hass)
        await lr.async_load(hass)
        await dr.async_load(hass)
        await er.async_load(hass)
        await ir.async_load(hass)
        await rs.async_load(hass)
        hass.config_entries = config_entries.ConfigEntries(hass, {})
        await hass.config_entries.async_initialize()
        hass.set_state(CoreState.running)
        assert await async_setup_component(hass, "homeassistant", {})
        try:
            yield hass
        finally:
            await hass.async_stop(force=True)
