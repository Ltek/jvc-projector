"""Diagnostics for the JVC Projector integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import JVCConfigEntry
from .models import model_code, spec_for, supports

TO_REDACT = {CONF_PASSWORD, CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: JVCConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (password and host redacted)."""
    coordinator = entry.runtime_data
    device = coordinator.device
    model = device.model_code
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "projector": {
            "model": model,
            "model_code": model_code(model),
            "specification": spec_for(model),
            "software_version": device.version,
            "unsupported_here": sorted(
                code
                for code in ("PMLL", "PMNM", "PMME", "PMUS", "PMCV", "PMDC")
                if not supports(model, code)
            ),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "failing_queries": dict(coordinator.failures),
            "data": coordinator.data,
        },
    }
