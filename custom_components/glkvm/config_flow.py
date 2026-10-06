"""Config flow for GL.iNet KVM integration."""

import logging
import re

from homeassistant import config_entries
from homeassistant.core import callback

from .cert_handler import fetch_serialized_cert, is_glkvm_device
from .const import (
    CONF_CERTIFICATE,
    CONF_HOST,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SERIAL,
    DEFAULT_HOST,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    MANUFACTURER,
    MAX_PORTS,
)
from .options_flow import GLKVMOptionsFlowHandler
from .utils import (
    create_data_schema,
    create_port_schema,
    find_existing_entry,
    get_translations,
    port_labels,
    update_existing_entry,
)

_LOGGER = logging.getLogger(__name__)


async def perform_device_setup(flow_handler, user_input):
    """Handle initial configuration setup for the configuration."""
    errors = {}
    host = user_input[CONF_HOST]
    username = DEFAULT_USERNAME
    password = user_input[CONF_PASSWORD]

    _LOGGER.debug(
        "Entered perform_device_setup with URL %s, username %s", host, username
    )

    try:
        serialized_cert = await fetch_serialized_cert(flow_handler.hass, host)
        if not serialized_cert:
            errors["base"] = "cannot_fetch_cert"
            return None, errors

        user_input[CONF_CERTIFICATE] = serialized_cert

        response = await is_glkvm_device(
            flow_handler.hass, host, username, password, serialized_cert
        )

        if response.error:
            errors["base"] = response.error
            return None, errors

        if not response.success:
            _LOGGER.error(
                "Error detected while connecting to KVM device. Error: %s",
                response.error,
            )
            errors["base"] = "cannot_connect"
            return None, errors

        _LOGGER.debug(
            "KVM device detected: Model=%s, Serial=%s, Name=%s, Ports=%s",
            response.model,
            response.serial,
            response.name,
            getattr(response, "port_count", None),
        )

        port_count = getattr(response, "port_count", None)

        # Multi-port device (Comet-x): if all ports are already configured,
        # refresh credentials on the first entry and abort with a clear reason.
        if port_count and port_count > 1:
            entries_for_serial = [
                e
                for e in flow_handler._async_current_entries()
                if (e.data.get("serial") or "").lower() == response.serial.lower()
            ]
            configured = {
                e.data.get(CONF_PORT, DEFAULT_PORT) for e in entries_for_serial
            }
            if len(configured) >= min(port_count, MAX_PORTS):
                if entries_for_serial:
                    update_existing_entry(
                        flow_handler.hass,
                        min(
                            entries_for_serial,
                            key=lambda e: e.data.get(CONF_PORT, 1),
                        ),
                        {CONF_HOST: host, CONF_PASSWORD: password},
                    )
                return flow_handler.async_abort(reason="all_ports_configured"), None
            # Stash for the port picker step.
            flow_handler._device_info = {
                "host": host,
                "password": password,
                "cert": serialized_cert,
                "model": response.model.lower() if response.model else "unknown",
                "serial": response.serial,
                "name": response.name,
                "port_count": port_count,
            }
            return await flow_handler.async_step_port(), None

        # Single-device path (unchanged).
        existing_entry = find_existing_entry(flow_handler, response.serial)
        if existing_entry:
            update_existing_entry(
                flow_handler.hass,
                existing_entry,
                {CONF_HOST: host, CONF_PASSWORD: password},
            )
            return flow_handler.async_abort(reason="already_configured"), None

        device_name = response.name
        if device_name == "localhost.localdomain" or not device_name:
            device_name = MANUFACTURER

        user_input[CONF_MODEL] = response.model.lower() if response.model else "unknown"
        user_input[CONF_SERIAL] = response.serial
        await flow_handler.async_set_unique_id(response.serial)

        config_flow_result = flow_handler.async_create_entry(
            title=device_name if device_name else "GL.iNet KVM", data=user_input
        )
        return config_flow_result, None

    except (ConnectionError, TimeoutError, ValueError) as e:
        _LOGGER.error("Unexpected error during device setup: %s", e)
        errors["base"] = "unknown_error"

    return None, errors


class GLKVMConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GL.iNet KVM."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the GLKVMConfigFlow."""
        self._errors: dict[str, str] = {}
        self.translations = None
        self._discovery_info: dict[str, str] = {}
        self._device_info: dict | None = None

    async def async_step_import(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Handle import."""
        return await self.async_step_user(user_input=user_input)

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors = self._errors
        self._errors = {}

        translations = await get_translations(
            self.hass, self.hass.config.language, DOMAIN
        )
        if translations and not callable(translations):

            def translate(key: str, default: str) -> str:
                return translations.get(key, default)

            self.translations = translate
        else:
            self.translations = translations

        if user_input is not None:
            _LOGGER.debug(
                "Entered async_step_user with data: host=%s, password=%s",
                user_input[CONF_HOST],
                re.sub(r'.', '*', user_input[CONF_PASSWORD]),
            )
            entry, setup_errors = await perform_device_setup(self, user_input)
            if setup_errors:
                errors.update(setup_errors)
            if entry:
                return entry

        if user_input is None:
            _LOGGER.debug("Entered async_step_user with data: None")
            user_input = self._discovery_info or {
                CONF_HOST: DEFAULT_HOST,
                CONF_PASSWORD: DEFAULT_PASSWORD,
            }
            if self._discovery_info:
                user_input[CONF_PASSWORD] = ""

        data_schema = create_data_schema(user_input)

        def _translate(key: str, default: str) -> str:
            if self.translations:
                return self.translations(key, default)
            return default

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "url": _translate(
                    "step.user.data.url", "URL or IP address of the KVM device"
                ),
                "password": _translate(
                    "step.user.data.password", "Password for KVM"
                ),
            },
        )

    async def async_step_port(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Pick which target port (device) this entry will manage."""
        info = self._device_info
        if not info:
            return self.async_abort(reason="unknown_error")

        configured = {
            e.data.get(CONF_PORT, DEFAULT_PORT)
            for e in self._async_current_entries()
            if (e.data.get("serial") or "").lower() == info["serial"].lower()
        }
        available = [
            p for p in range(1, min(info["port_count"], MAX_PORTS) + 1)
            if p not in configured
        ]
        if not available:
            return self.async_abort(reason="all_ports_configured")

        if user_input is not None:
            port = int(user_input[CONF_PORT])
            if port not in available:
                self._errors[CONF_PORT] = "port_unavailable"
                return await self._show_port_form(available)

            await self.async_set_unique_id(f"{info['serial']}_port{port}")
            self._abort_if_unique_id_configured()

            base_name = info["name"]
            if base_name == "localhost.localdomain" or not base_name:
                base_name = MANUFACTURER

            data = {
                CONF_HOST: info["host"],
                CONF_PASSWORD: info["password"],
                CONF_CERTIFICATE: info["cert"],
                CONF_MODEL: info["model"],
                CONF_SERIAL: info["serial"],
                CONF_PORT: port,
                "port_count": info["port_count"],
            }
            title = f"{base_name} (Port {port})"
            return self.async_create_entry(title=title, data=data)

        return await self._show_port_form(available)

    async def _show_port_form(self, available: list[int]):
        labels = port_labels(self._device_info)
        return self.async_show_form(
            step_id="port",
            data_schema=create_port_schema(available, default=available[0]),
            errors=self._errors,
            description_placeholders={
                "ports": ", ".join(labels[p] for p in available),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return GLKVMOptionsFlowHandler(config_entry)
