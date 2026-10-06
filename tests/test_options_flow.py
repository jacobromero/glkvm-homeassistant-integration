"""Tests for the GLKVM options flow."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glkvm.const import (
    CONF_CERTIFICATE,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SERIAL,
    DEFAULT_PASSWORD,
    DOMAIN,
)
from custom_components.glkvm.cert_handler import GLKVMResponse


def _port_entry(hass, port=1):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"comet-serial_port{port}",
        data={
            CONF_HOST: "https://192.168.0.40",
            CONF_PASSWORD: DEFAULT_PASSWORD,
            CONF_SERIAL: "comet-serial",
            CONF_PORT: port,
            CONF_CERTIFICATE: "old-cert",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.asyncio
async def test_options_flow_updates_credentials(hass, glkvm_cert):
    """Options flow updates host/password/cert on the entry."""
    entry = _port_entry(hass, port=1)

    response = GLKVMResponse(True, "RM4PE", "comet-serial", "comet.local", None, 4)

    with (
        patch(
            "custom_components.glkvm.options_flow.fetch_serialized_cert",
            new=AsyncMock(return_value=glkvm_cert),
        ),
        patch(
            "custom_components.glkvm.options_flow.is_glkvm_device",
            new=AsyncMock(return_value=response),
        ),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        # Port entries get a port selector in the options form.
        assert CONF_PORT in {str(k) for k in result["data_schema"].schema}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_HOST: "https://192.168.0.40", CONF_PASSWORD: "newpw", CONF_PORT: "1"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_PASSWORD] == "newpw"
    assert entry.data[CONF_CERTIFICATE] == glkvm_cert
    assert entry.data[CONF_PORT] == 1


@pytest.mark.asyncio
async def test_options_flow_repicks_port(hass, glkvm_cert):
    """An entry can move from port 1 to a free port."""
    entry = _port_entry(hass, port=1)

    response = GLKVMResponse(True, "RM4PE", "comet-serial", "comet.local", None, 4)

    with (
        patch(
            "custom_components.glkvm.options_flow.fetch_serialized_cert",
            new=AsyncMock(return_value=glkvm_cert),
        ),
        patch(
            "custom_components.glkvm.options_flow.is_glkvm_device",
            new=AsyncMock(return_value=response),
        ),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_HOST: "https://192.168.0.40", CONF_PASSWORD: DEFAULT_PASSWORD, CONF_PORT: "3"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_PORT] == 3
    assert entry.unique_id == "comet-serial_port3"


@pytest.mark.asyncio
async def test_options_flow_single_device_no_port_field(hass):
    """Single-device entries keep the plain url+password options form."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="glkvm-serial",
        data={
            CONF_HOST: "https://glkvm.local",
            CONF_PASSWORD: DEFAULT_PASSWORD,
            CONF_SERIAL: "glkvm-serial",
            CONF_CERTIFICATE: "old-cert",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert CONF_PORT not in {str(k) for k in result["data_schema"].schema}
