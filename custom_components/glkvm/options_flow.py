"""Config flow to configure GL.iNet KVM."""

import logging

from homeassistant import config_entries

from .cert_handler import fetch_serialized_cert, is_glkvm_device
from .const import (
    CONF_CERTIFICATE,
    CONF_HOST,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SERIAL,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    MAX_PORTS,
)
from .utils import (
    create_data_schema,
    create_port_schema,
    format_url,
    get_translations,
    update_existing_entry,
)

_LOGGER = logging.getLogger(__name__)


class GLKVMOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle GL.iNet KVM options."""

    def __init__(self, config_entry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.translate = None

    async def async_step_init(self, user_input=None):
        """Manage the GLKVM options."""
        errors = {}
        self.translate = await get_translations(
            self.hass, self.hass.config.language, DOMAIN
        )
        _LOGGER.debug("Entered async_step_init with data: %s", user_input)

        is_port_entry = CONF_PORT in self.config_entry.data

        if user_input is not None:
            url = format_url(user_input[CONF_HOST])
            username = DEFAULT_USERNAME
            password = user_input.get(CONF_PASSWORD, DEFAULT_PASSWORD)

            _LOGGER.debug("Manual setup with URL %s, username %s", url, username)

            serialized_cert = await fetch_serialized_cert(self.hass, url)
            if not serialized_cert:
                errors["base"] = "cannot_fetch_cert"
                _LOGGER.error("Cannot fetch cert from URL: %s", url)
            else:
                _LOGGER.debug("Serialized certificate fetched successfully")
                user_input[CONF_CERTIFICATE] = serialized_cert

                response = await is_glkvm_device(
                    self.hass, url, username, password, serialized_cert
                )

                if response.error:
                    errors["base"] = response.error
                elif response.success:
                    _LOGGER.debug(
                        "KVM device successfully found at %s with serial %s",
                        url,
                        response.serial,
                    )

                    # Match on serial (+port for port entries) rather than
                    # unique_id, which is serial_portN for Comet-x entries.
                    raw_port = user_input.get(CONF_PORT)
                    port = (
                        int(raw_port)
                        if raw_port is not None
                        else self.config_entry.data.get(CONF_PORT)
                    )
                    existing_entry = None
                    for entry in self.hass.config_entries.async_entries(DOMAIN):
                        if (entry.data.get(CONF_SERIAL) or "").lower() != (
                            response.serial or ""
                        ).lower():
                            continue
                        if is_port_entry or port is not None:
                            if entry.data.get(CONF_PORT, DEFAULT_PORT) != port:
                                continue
                        existing_entry = entry
                        break

                    if existing_entry and existing_entry.entry_id != self.config_entry.entry_id:
                        update_existing_entry(self.hass, existing_entry, user_input)
                        return self.async_create_entry(title="", data={})

                    new_data = {**self.config_entry.data, **user_input}
                    if is_port_entry:
                        new_data[CONF_PORT] = port
                        new_unique_id = f"{response.serial}_port{port}"
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data=new_data,
                            unique_id=new_unique_id,
                        )
                    else:
                        self.hass.config_entries.async_update_entry(
                            self.config_entry, data=new_data
                        )
                    return self.async_create_entry(title="", data={})
                else:
                    errors["base"] = "cannot_connect"
                    _LOGGER.error(
                        "Cannot connect to KVM device at %s with provided credentials",
                        url,
                    )

        default_url = self.config_entry.data.get(CONF_HOST, "")
        default_password = self.config_entry.data.get(CONF_PASSWORD, DEFAULT_PASSWORD)

        data_schema = create_data_schema(
            {
                CONF_HOST: default_url,
                CONF_PASSWORD: default_password,
            }
        )

        placeholders = {
            "url": self.translate(
                "config.step.user.data.url", "URL or IP address of the KVM device"
            ),
            "password": self.translate(
                "config.step.user.data.password", "Password for KVM"
            ),
        }

        if is_port_entry:
            current_port = self.config_entry.data.get(CONF_PORT, DEFAULT_PORT)
            port_count = self.config_entry.data.get("port_count", MAX_PORTS)
            taken = {
                e.data.get(CONF_PORT, DEFAULT_PORT)
                for e in self.hass.config_entries.async_entries(DOMAIN)
                if (e.data.get(CONF_SERIAL) or "").lower()
                == (self.config_entry.data.get(CONF_SERIAL) or "").lower()
                and e.entry_id != self.config_entry.entry_id
            }
            available = [
                p
                for p in range(1, min(port_count, MAX_PORTS) + 1)
                if p not in taken or p == current_port
            ]
            data_schema = data_schema.extend(
                dict(create_port_schema(available, default=current_port).schema)
            )
            placeholders["port"] = self.translate(
                "config.step.port.data.port", "Target port (device) to manage"
            )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=placeholders,
        )
