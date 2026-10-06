"""The GL.iNet KVM integration."""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import ConfigType

from .cert_handler import format_url
from .const import (
    CONF_CERTIFICATE,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SERIAL,
    DEFAULT_HOST,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USERNAME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import GLKVMDataUpdateCoordinator, is_multiport_model
from .entity import GLKVMEntity

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button", "switch"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.url,
                vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the GLKVM component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GLKVM from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    stored_serial = entry.data.get(CONF_SERIAL, None)
    unique_id = entry.unique_id
    expected_unique_id = (
        f"{stored_serial}_port{port}" if CONF_PORT in entry.data else stored_serial
    )

    if expected_unique_id and unique_id != expected_unique_id:
        _LOGGER.debug("Updating unique ID from %s to %s", unique_id, expected_unique_id)
        hass.config_entries.async_update_entry(entry, unique_id=expected_unique_id)

    model = entry.data.get("model", "")
    coordinator = GLKVMDataUpdateCoordinator(
        hass,
        entry.data[CONF_HOST],
        DEFAULT_USERNAME,
        entry.data[CONF_PASSWORD],
        entry.data[CONF_CERTIFICATE],
        port=port,
        multiport=is_multiport_model(model),
    )
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Safely extract device info with fallbacks
    system = coordinator.data.get("system", {}) if coordinator.data else {}
    platform = system.get("platform", {})
    kvmd = system.get("kvmd", {})

    # Use base field for model (e.g., "Rockchip RV1126B-P EVB V14 Board")
    model_name = platform.get("base") or entry.data.get("model", "GLKVM")
    hw_version = platform.get("model")  # e.g., "v3"
    sw_version = kvmd.get("version")

    # For multi-port devices each config entry represents one target port,
    # so each gets its own HA device (named "<title> Port N").
    if CONF_PORT in entry.data:
        device_id = f"{entry.data[CONF_SERIAL]}_port{port}"
        device_name = f"{entry.title} (Port {port})"
    else:
        device_id = entry.data[CONF_SERIAL]
        device_name = entry.title

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        configuration_url=format_url(entry.data[CONF_HOST]),
        serial_number=entry.data[CONF_SERIAL],
        manufacturer=MANUFACTURER,
        name=device_name,
        model=model_name,
        hw_version=hw_version,
        sw_version=sw_version,
    )
    coordinator.device_info = device_info
    # Backwards-compat for any entity still reading the class attribute.
    GLKVMEntity.DEVICE_INFO = device_info

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a config entry."""
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)
