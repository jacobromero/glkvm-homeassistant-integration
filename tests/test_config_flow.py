"""Tests for the GLKVM config flow (single-device and Comet-x multiport)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.glkvm import config_flow
from custom_components.glkvm.cert_handler import GLKVMResponse
from custom_components.glkvm.const import (
    CONF_CERTIFICATE,
    CONF_HOST,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SERIAL,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    DOMAIN,
    MANUFACTURER,
)
from custom_components.glkvm.options_flow import GLKVMOptionsFlowHandler

COMET_SERIAL = "comet-serial"


def _comet_response(port_count=4):
    return GLKVMResponse(
        True, "RM4PE", COMET_SERIAL, "comet.local", None, port_count
    )


def _single_response():
    return GLKVMResponse(True, "v3", "glkvm-1234", "My GLKVM", None, None)


@pytest.mark.asyncio
async def test_config_flow_single_device_success(hass, glkvm_cert):
    """Single-device flow creates one entry with no port key."""
    user_input = {
        CONF_HOST: "https://glkvm.local",
        CONF_PASSWORD: "secret",
    }

    with patch(
        "custom_components.glkvm.config_flow.fetch_serialized_cert",
        new=AsyncMock(return_value=glkvm_cert),
    ), patch(
        "custom_components.glkvm.config_flow.is_glkvm_device",
        new=AsyncMock(return_value=_single_response()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=user_input,
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "My GLKVM"
    assert result["data"][CONF_CERTIFICATE] == glkvm_cert
    assert result["data"][CONF_SERIAL] == "glkvm-1234"
    assert result["data"][CONF_MODEL] == "v3"
    assert CONF_PORT not in result["data"]


@pytest.mark.asyncio
async def test_config_flow_cometx_shows_port_picker(hass, glkvm_cert):
    """Comet-x (port_count>1) proceeds to a port selection step."""
    user_input = {
        CONF_HOST: "https://192.168.0.40",
        CONF_PASSWORD: "secret",
    }

    with patch(
        "custom_components.glkvm.config_flow.fetch_serialized_cert",
        new=AsyncMock(return_value=glkvm_cert),
    ), patch(
        "custom_components.glkvm.config_flow.is_glkvm_device",
        new=AsyncMock(return_value=_comet_response()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=user_input,
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "port"


async def _start_comet_flow(hass, glkvm_cert):
    """Run the user step against a Comet-x and return (flow_id, port_form)."""
    with patch(
        "custom_components.glkvm.config_flow.fetch_serialized_cert",
        new=AsyncMock(return_value=glkvm_cert),
    ), patch(
        "custom_components.glkvm.config_flow.is_glkvm_device",
        new=AsyncMock(return_value=_comet_response()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "https://192.168.0.40", CONF_PASSWORD: "secret"},
        )
    return result["flow_id"], result


@pytest.mark.asyncio
async def test_config_flow_cometx_creates_port_entry(hass, glkvm_cert):
    """Selecting a port creates an entry keyed serial_portN."""
    flow_id, port_form = await _start_comet_flow(hass, glkvm_cert)
    assert port_form["step_id"] == "port"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PORT: "2"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "comet.local (Port 2)"
    assert result["data"][CONF_PORT] == 2
    assert result["data"][CONF_SERIAL] == COMET_SERIAL


@pytest.mark.asyncio
async def test_config_flow_cometx_skips_configured_ports(hass, glkvm_cert):
    """Already-configured ports are not offered again."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{COMET_SERIAL}_port1",
        data={
            CONF_HOST: "https://192.168.0.40",
            CONF_PASSWORD: "secret",
            CONF_SERIAL: COMET_SERIAL,
            CONF_PORT: 1,
        },
    ).add_to_hass(hass)

    _, port_form = await _start_comet_flow(hass, glkvm_cert)
    assert port_form["type"] == FlowResultType.FORM
    schema = port_form["data_schema"]
    key = next(k for k in schema.schema if str(k) == CONF_PORT)
    options = list(schema.schema[key].container)
    assert "1" not in options
    assert set(options) == {"2", "3", "4"}


@pytest.mark.asyncio
async def test_config_flow_cometx_all_ports_configured(hass, glkvm_cert):
    """Adding a 5th port aborts with all_ports_configured."""
    for port in (1, 2, 3, 4):
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{COMET_SERIAL}_port{port}",
            data={
                CONF_HOST: "https://192.168.0.40",
                CONF_PASSWORD: "secret",
                CONF_SERIAL: COMET_SERIAL,
                CONF_PORT: port,
            },
        ).add_to_hass(hass)

    with patch(
        "custom_components.glkvm.config_flow.fetch_serialized_cert",
        new=AsyncMock(return_value=glkvm_cert),
    ), patch(
        "custom_components.glkvm.config_flow.is_glkvm_device",
        new=AsyncMock(return_value=_comet_response()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "https://192.168.0.40", CONF_PASSWORD: "secret"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "all_ports_configured"


@pytest.mark.asyncio
async def test_config_flow_cometx_bad_port_rejected(hass, glkvm_cert):
    """A port outside the available set is rejected by the schema."""
    from homeassistant.data_entry_flow import InvalidData

    flow_id, port_form = await _start_comet_flow(hass, glkvm_cert)
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(flow_id, {CONF_PORT: "9"})


@pytest.mark.asyncio
async def test_config_flow_user_cannot_connect(hass, glkvm_cert):
    """Unreachable device re-shows the user form with an error."""
    failure = GLKVMResponse(False, None, None, None, "cannot_connect", None)

    with patch(
        "custom_components.glkvm.config_flow.fetch_serialized_cert",
        new=AsyncMock(return_value=glkvm_cert),
    ), patch(
        "custom_components.glkvm.config_flow.is_glkvm_device",
        new=AsyncMock(return_value=failure),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_HOST: "https://glkvm.local", CONF_PASSWORD: "secret"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_perform_device_setup_missing_certificate(hass):
    """No cert -> cannot_fetch_cert."""
    flow = config_flow.GLKVMConfigFlow()
    flow.hass = hass

    with patch(
        "custom_components.glkvm.config_flow.fetch_serialized_cert",
        new=AsyncMock(return_value=None),
    ):
        entry, errors = await config_flow.perform_device_setup(
            flow, {CONF_HOST: "https://glkvm.local", CONF_PASSWORD: "secret"}
        )

    assert entry is None
    assert errors["base"] == "cannot_fetch_cert"


@pytest.mark.asyncio
async def test_perform_device_setup_existing_single_entry_updates(hass, glkvm_cert):
    """Existing single-device entries are updated and the flow aborts."""
    flow = config_flow.GLKVMConfigFlow()
    flow.hass = hass
    flow.async_abort = MagicMock(return_value={"type": FlowResultType.ABORT})

    existing_entry = MagicMock()
    existing_entry.data = {
        CONF_PASSWORD: "s3cret",
        "serial": "glkvm-serial",
    }

    with (
        patch(
            "custom_components.glkvm.config_flow.fetch_serialized_cert",
            new=AsyncMock(return_value=glkvm_cert),
        ),
        patch(
            "custom_components.glkvm.config_flow.is_glkvm_device",
            new=AsyncMock(
                return_value=GLKVMResponse(True, "V3", "glkvm-serial", "My GLKVM", None)
            ),
        ),
        patch(
            "custom_components.glkvm.config_flow.find_existing_entry",
            return_value=existing_entry,
        ),
        patch(
            "custom_components.glkvm.config_flow.update_existing_entry",
            autospec=True,
        ) as update_mock,
    ):
        entry, errors = await config_flow.perform_device_setup(
            flow, {CONF_HOST: "https://glkvm.local", CONF_PASSWORD: "secret"}
        )

    assert entry == {"type": FlowResultType.ABORT}
    assert errors is None
    update_mock.assert_called_once()


@pytest.mark.asyncio
async def test_perform_device_setup_localhost_name(hass, glkvm_cert):
    """localhost device names fall back to the manufacturer label."""
    flow = config_flow.GLKVMConfigFlow()
    flow.hass = hass
    flow.async_abort = MagicMock()
    flow.async_set_unique_id = AsyncMock()
    flow.async_create_entry = MagicMock(
        return_value={"type": FlowResultType.CREATE_ENTRY}
    )

    with (
        patch(
            "custom_components.glkvm.config_flow.fetch_serialized_cert",
            new=AsyncMock(return_value=glkvm_cert),
        ),
        patch(
            "custom_components.glkvm.config_flow.is_glkvm_device",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    success=True,
                    model="RM4PE",
                    serial="glkvm-9999",
                    name="localhost.localdomain",
                    error=None,
                    port_count=None,
                )
            ),
        ),
        patch(
            "custom_components.glkvm.config_flow.find_existing_entry",
            return_value=None,
        ),
    ):
        entry, errors = await config_flow.perform_device_setup(
            flow, {CONF_HOST: "https://glkvm.local", CONF_PASSWORD: "secret"}
        )

    assert entry == {"type": FlowResultType.CREATE_ENTRY}
    kwargs = flow.async_create_entry.call_args.kwargs
    assert kwargs["title"] == MANUFACTURER
    assert kwargs["data"][CONF_MODEL] == "rm4pe"
    assert errors is None


def test_async_get_options_flow_returns_handler():
    """Validate the options flow factory."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    handler = config_flow.GLKVMConfigFlow.async_get_options_flow(entry)
    assert isinstance(handler, GLKVMOptionsFlowHandler)
