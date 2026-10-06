"""Switch platform for GL.iNet KVM power control."""

import logging

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATX_ACTION_POWER_OFF,
    ATX_ACTION_POWER_OFF_HARD,
    ATX_ACTION_POWER_ON,
    CONF_PORT,
    CONF_SHUTDOWN_MODE,
    DEFAULT_PORT,
    DOMAIN,
    SHUTDOWN_MODE_FORCE,
)
from .entity import GLKVMEntity

_LOGGER = logging.getLogger(__name__)


class GLKVMPowerSwitch(GLKVMEntity, SwitchEntity):
    """Switch to control computer power state."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator,
        unique_id_base: str,
        device_name: str,
        shutdown_mode: str = "graceful",
    ) -> None:
        """Initialize the power switch."""
        super().__init__(coordinator, unique_id_base)
        self._attr_unique_id = f"{unique_id_base}_power_switch"
        self._attr_name = f"{device_name} Power"
        self._attr_icon = "mdi:power"
        self._shutdown_mode = shutdown_mode

    @property
    def available(self) -> bool:
        """Return True if the switch data is available."""
        atx = self.coordinator.data.get("atx", {}) if self.coordinator.data else {}
        return "power" in atx

    @property
    def is_on(self) -> bool | None:
        """Return True if the system is powered on."""
        atx = self.coordinator.data.get("atx", {}) if self.coordinator.data else {}
        if "power" not in atx:
            return None
        power_value = atx["power"]
        return self._parse_power_value(power_value)

    def _parse_power_value(self, value) -> bool:
        """Parse various power value formats and return boolean."""
        if isinstance(value, str):
            return value.lower() in ("on", "true", "1", "yes")
        return bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the system (only if currently off)."""
        if not self.is_on:
            _LOGGER.debug("System is off, sending power on command")
            await self.coordinator.async_atx(action=ATX_ACTION_POWER_ON)
        else:
            _LOGGER.debug("System is already on, skipping power on command")

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the system (graceful shutdown by default)."""
        if self.is_on:
            action = (
                ATX_ACTION_POWER_OFF_HARD
                if self._shutdown_mode == SHUTDOWN_MODE_FORCE
                else ATX_ACTION_POWER_OFF
            )
            _LOGGER.debug("System is on, sending %s command", action)
            await self.coordinator.async_atx(action=action)
        else:
            _LOGGER.debug("System is already off, skipping power off command")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GLKVM power switch from a config entry."""
    _LOGGER.debug("Setting up GLKVM power switch from config entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    serial = config_entry.data.get("serial", config_entry.entry_id)
    port = config_entry.data.get(CONF_PORT, DEFAULT_PORT)
    unique_id_base = (
        f"{config_entry.entry_id}_{serial}_port{port}"
        if CONF_PORT in config_entry.data
        else f"{config_entry.entry_id}_{serial}"
    )

    device_name = config_entry.title or "GLKVM"
    shutdown_mode = config_entry.options.get(CONF_SHUTDOWN_MODE, "graceful")

    switches = [
        GLKVMPowerSwitch(coordinator, unique_id_base, device_name, shutdown_mode),
    ]

    async_add_entities(switches, True)
    _LOGGER.debug("%d GLKVM switch(es) added to Home Assistant", len(switches))
