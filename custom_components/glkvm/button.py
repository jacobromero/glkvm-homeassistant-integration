"""Button platform for GL.iNet KVM ATX controls."""

import logging

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATX_BUTTON_POWER,
    ATX_BUTTON_RESET,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)
from .entity import GLKVMEntity

_LOGGER = logging.getLogger(__name__)


class GLKVMButtonEntity(GLKVMEntity, ButtonEntity):
    """Base class for GLKVM button entities."""

    def __init__(
        self,
        coordinator,
        unique_id_base: str,
        button_type: str,
        name: str,
        button: str,
        icon: str,
        device_class: ButtonDeviceClass | None = None,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, unique_id_base)
        self._attr_unique_id = f"{unique_id_base}_{button_type}"
        self._attr_name = name
        self._attr_icon = icon
        self._button = button
        if device_class:
            self._attr_device_class = device_class

    async def async_press(self) -> None:
        """Handle the button press (momentary ATX click)."""
        await self.coordinator.async_atx(button=self._button)


class GLKVMPowerButton(GLKVMButtonEntity):
    """Button to press the power button on the connected system."""

    def __init__(self, coordinator, unique_id_base: str, device_name: str) -> None:
        """Initialize the power button."""
        super().__init__(
            coordinator,
            unique_id_base,
            "power_button",
            f"{device_name} Power Button",
            ATX_BUTTON_POWER,
            "mdi:power",
        )


class GLKVMResetButton(GLKVMButtonEntity):
    """Button to press the reset button on the connected system."""

    def __init__(self, coordinator, unique_id_base: str, device_name: str) -> None:
        """Initialize the reset button."""
        super().__init__(
            coordinator,
            unique_id_base,
            "reset_button",
            f"{device_name} Reset Button",
            ATX_BUTTON_RESET,
            "mdi:restart",
            ButtonDeviceClass.RESTART,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GLKVM buttons from a config entry."""
    _LOGGER.debug("Setting up GLKVM ATX buttons from config entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    serial = config_entry.data.get("serial", config_entry.entry_id)
    port = config_entry.data.get(CONF_PORT, DEFAULT_PORT)
    unique_id_base = (
        f"{config_entry.entry_id}_{serial}_port{port}"
        if CONF_PORT in config_entry.data
        else f"{config_entry.entry_id}_{serial}"
    )

    device_name = config_entry.title or "GLKVM"

    buttons = [
        GLKVMPowerButton(coordinator, unique_id_base, device_name),
        GLKVMResetButton(coordinator, unique_id_base, device_name),
    ]

    async_add_entities(buttons, True)
    _LOGGER.debug("%d GLKVM ATX buttons added to Home Assistant", len(buttons))
