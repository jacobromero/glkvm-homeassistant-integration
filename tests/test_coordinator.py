"""Tests for the GLKVM coordinator (multiport routing, ATX normalization)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.glkvm.const import (
    API_ATX_CLICK,
    API_ATX_POWER,
    API_SWITCH_ATX_CLICK,
    API_SWITCH_ATX_POWER,
    ATX_ACTION_POWER_OFF,
    ATX_BUTTON_POWER,
)
from custom_components.glkvm.coordinator import (
    GLKVMDataUpdateCoordinator,
    is_multiport_model,
    port_to_index,
)


def _make_coordinator(multiport: bool, port: int = 1):
    hass = MagicMock()
    # async_add_executor_job(fn) -> run fn inline so the mocked session is hit
    async def _run(fn, *args):
        if args:
            return fn(*args)
        return fn()

    hass.async_add_executor_job = AsyncMock(side_effect=_run)
    coord = GLKVMDataUpdateCoordinator(
        hass, "https://192.168.0.40", "admin", "pw", "cert", port=port, multiport=multiport
    )
    coord.session = MagicMock()
    return coord


def test_is_multiport_model():
    assert is_multiport_model("RM4PE")
    assert is_multiport_model("GL-RM4PE")
    assert is_multiport_model("Comet X")
    assert not is_multiport_model("v3")
    assert not is_multiport_model(None)


def test_port_to_index():
    assert port_to_index(1) == 0
    assert port_to_index(4) == 3


def test_normalize_atx_switch_arrays_take_priority():
    coord = _make_coordinator(multiport=True, port=2)
    switch = {
        "atx": {
            "busy": [False, True, False, False],
            "leds": {"power": [True, False, True, True], "hdd": [False, False, False, False]},
        },
        "summary": {"active_port": 0},
    }
    atx = coord._normalize_atx({"power": "on", "leds": {"power": True, "hdd": False}}, switch)
    assert atx["power"] == "off"  # port 2 -> index 1 -> False
    assert atx["busy"] is True
    assert atx["source"] == "switch"


def test_normalize_atx_empty_arrays_fall_back_to_active_port():
    """Empty switch arrays (no channels registered) -> use /api/atx only
    when this entry's port is the active one."""
    coord = _make_coordinator(multiport=True, port=1)
    switch = {
        "atx": {"busy": [], "leds": {"power": [], "hdd": []}},
        "summary": {"active_port": 0, "active_id": "1.1"},
    }
    legacy = {"power": "on", "enabled": True, "busy": False, "leds": {"power": True, "hdd": False}}
    atx = coord._normalize_atx(legacy, switch)
    assert atx == legacy

    # Port 2 entry while port 1 is active: /api/atx describes another
    # machine, so report nothing rather than wrong state.
    coord2 = _make_coordinator(multiport=True, port=2)
    atx2 = coord2._normalize_atx(legacy, switch)
    assert atx2 == {}


def test_normalize_atx_single_device_passthrough():
    coord = _make_coordinator(multiport=False)
    legacy = {"power": "off", "enabled": True}
    assert coord._normalize_atx(legacy, None) == legacy


@pytest.mark.asyncio
async def test_async_atx_multiport_uses_switch_routes():
    coord = _make_coordinator(multiport=True, port=3)
    coord.session.post.return_value = MagicMock(status_code=200)
    coord._schedule_settled_refresh = MagicMock()

    ok = await coord.async_atx(action=ATX_ACTION_POWER_OFF)
    assert ok
    url = coord.session.post.call_args.args[0]
    params = coord.session.post.call_args.kwargs["params"]
    assert url.endswith(API_SWITCH_ATX_POWER)
    assert params == {"port": 3, "action": "off"}

    ok = await coord.async_atx(button=ATX_BUTTON_POWER)
    assert ok
    url = coord.session.post.call_args.args[0]
    params = coord.session.post.call_args.kwargs["params"]
    assert url.endswith(API_SWITCH_ATX_CLICK)
    assert params == {"port": 3, "button": "power"}


@pytest.mark.asyncio
async def test_async_atx_single_device_uses_legacy_routes():
    coord = _make_coordinator(multiport=False)
    coord.session.post.return_value = MagicMock(status_code=200)
    coord._schedule_settled_refresh = MagicMock()

    ok = await coord.async_atx(action=ATX_ACTION_POWER_OFF)
    assert ok
    url = coord.session.post.call_args.args[0]
    params = coord.session.post.call_args.kwargs["params"]
    assert url.endswith(API_ATX_POWER)
    assert params == {"action": "off"}


@pytest.mark.asyncio
async def test_async_atx_retries_on_409():
    coord = _make_coordinator(multiport=True, port=1)
    busy = MagicMock(status_code=409, text="AtxIsBusyError")
    good = MagicMock(status_code=200)
    coord.session.post.side_effect = [busy, busy, good]
    coord._schedule_settled_refresh = MagicMock()

    with patch("custom_components.glkvm.coordinator.asyncio.sleep", new=AsyncMock()):
        ok = await coord.async_atx(action=ATX_ACTION_POWER_OFF)
    assert ok
    assert coord.session.post.call_count == 3


@pytest.mark.asyncio
async def test_async_atx_fails_after_busy_retries():
    coord = _make_coordinator(multiport=True, port=1)
    busy = MagicMock(status_code=409, text="AtxIsBusyError")
    coord.session.post.return_value = busy
    coord._schedule_settled_refresh = MagicMock()

    with patch("custom_components.glkvm.coordinator.asyncio.sleep", new=AsyncMock()):
        ok = await coord.async_atx(action=ATX_ACTION_POWER_OFF)
    assert not ok
    # 1 initial + 2 retries
    assert coord.session.post.call_count == 3


@pytest.mark.asyncio
async def test_async_atx_requires_action_or_button():
    coord = _make_coordinator(multiport=True)
    with pytest.raises(ValueError):
        await coord.async_atx()
