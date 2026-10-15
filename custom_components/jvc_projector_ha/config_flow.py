"""Config flow for the jvc_projector integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac
from homeassistant.util.network import is_host_valid
import voluptuous as vol

from .const import DOMAIN, NAME
from .jvcprojector.error import JvcProjectorAuthError, JvcProjectorConnectError
from .jvcprojector.projector import DEFAULT_PORT, JvcProjector
from .options import LIMITS, Timing

_LOGGER = logging.getLogger(__name__)

CONNECTION_TIMEOUT = 30  # seconds


class InvalidHost(Exception):
    """Error indicating invalid network host."""


async def get_mac_address(host: str, port: int, password: str | None) -> str:
    """Connect once and return the projector's MAC address."""
    device = JvcProjector(host, port=port, password=password)
    try:
        await asyncio.wait_for(
            device.connect(get_info=True), timeout=CONNECTION_TIMEOUT
        )
        return device.mac
    finally:
        await device.disconnect()


async def _validate(
    host: str, port: int, password: str | None
) -> tuple[str | None, str]:
    """Return (mac, error_key); error_key is empty on success."""
    try:
        if not is_host_valid(host):
            raise InvalidHost
        return await get_mac_address(host, port, password), ""
    except InvalidHost:
        return None, "invalid_host"
    except JvcProjectorAuthError:
        return None, "invalid_auth"
    except (TimeoutError, JvcProjectorConnectError) as err:
        _LOGGER.debug("Cannot connect to %s:%d: %s", host, port, err)
        return None, "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error connecting to %s:%d", host, port)
        return None, "unknown"


def _schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)
            ): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(
                CONF_PASSWORD,
                description={"suggested_value": defaults.get(CONF_PASSWORD)},
            ): str,
        }
    )


class JvcProjectorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for the JVC Projector integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (timing)."""
        return JvcOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user initiated device additions."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            password = user_input.get(CONF_PASSWORD) or None
            mac, error = await _validate(host, port, password)
            if error:
                errors["base"] = error
            else:
                assert mac
                await self.async_set_unique_id(format_mac(mac))
                data = {CONF_HOST: host, CONF_PORT: port, CONF_PASSWORD: password}
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(title=NAME, data=data)

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, port or password (e.g. after the projector's IP changed)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            password = user_input.get(CONF_PASSWORD) or None
            mac, error = await _validate(host, port, password)
            if error:
                errors["base"] = error
            else:
                assert mac
                await self.async_set_unique_id(format_mac(mac))
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or entry.data),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth on password authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the network password again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input.get(CONF_PASSWORD) or None
            _mac, error = await _validate(
                entry.data[CONF_HOST], entry.data[CONF_PORT], password
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: password}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_PASSWORD): str}),
            errors=errors,
        )


class JvcOptionsFlow(OptionsFlow):
    """Timing options: poll interval, timeouts and the recovery pause."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the timing options."""
        if user_input is not None:
            # Store only what differs from the default (clean options).
            values = vars(Timing.from_options(user_input))
            data = {k: v for k, v in values.items() if v != LIMITS[k][0]}
            return self.async_create_entry(data=data)

        current = vars(Timing.from_options(self.config_entry.options))
        fields: dict[Any, Any] = {}
        for key, (_default, low, high) in LIMITS.items():
            fields[vol.Required(key, default=current[key])] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=low,
                    max=high,
                    step=0.5 if high <= 60 else 1,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
