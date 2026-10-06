"""Manages fetching data from the GLKVM API."""

import asyncio
from datetime import timedelta
import functools
import logging
import os
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cert_handler import create_session_with_cert
from .const import (
    API_ATX,
    API_ATX_CLICK,
    API_ATX_POWER,
    API_INFO,
    API_SWITCH,
    API_SWITCH_ATX_CLICK,
    API_SWITCH_ATX_POWER,
    DOMAIN,
    MAX_PORTS,
)

_LOGGER = logging.getLogger(__name__)

# How long to wait after an ATX command before refreshing state.
# ATX ops are momentary (the board simulates a physical button press)
# and the state settles a few seconds later.
ATX_SETTLE_SECONDS = 4
# 409 AtxIsBusyError means another ATX op is in flight; back off and retry.
ATX_BUSY_RETRIES = 2
ATX_BUSY_BACKOFF_SECONDS = 3


def format_url(input_url):
    """Ensure the URL is properly formatted."""
    if not input_url.startswith("http"):
        input_url = f"https://{input_url}"
    return input_url.rstrip("/")


def is_multiport_model(model: str | None) -> bool:
    """Return True if the model is a Comet-x style multi-port KVM."""
    if not model:
        return False
    m = str(model).lower()
    return "rm4pe" in m or "comet" in m


def port_to_index(port: int) -> int:
    """Map a 1-based port id to the 0-based index used by the switch API arrays."""
    return (port - 1) % MAX_PORTS


class AuthenticationFailed(Exception):
    """Custom exception for authentication failures."""


class GLKVMDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the GLKVM API."""

    url: str = ""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        username: str,
        password: str,
        cert: str,
        port: int = 1,
        multiport: bool = False,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.url = format_url(url)
        self.username = username
        self.password = password
        self.cert = cert
        self.port = port
        self.multiport = multiport
        self.session = None
        self.cert_file_path = None
        self.device_info = None
        self.auth = HTTPBasicAuth(self.username, self.password)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )

    async def async_setup(self) -> None:
        """Async setup method to create session and handle async code."""
        await self._create_session()

    async def _create_session(self):
        """Create the session with the certificate."""
        self.auth = HTTPBasicAuth(self.username, self.password)
        session_with_cert = await create_session_with_cert(self.cert)
        self.session, self.cert_file_path = session_with_cert
        if not self.session:
            _LOGGER.error("Failed to create session with certificate")
        else:
            _LOGGER.debug("Session created successfully")

    async def _async_update_data(self):
        """Fetch data from GLKVM API."""
        max_retries = 5
        backoff_time = 2

        retries = 0
        while retries < max_retries:
            try:
                _LOGGER.debug("Fetching GLKVM Info at %s", self.url)

                if not self.session:
                    await self._create_session()

                # Fetch device info
                response = await self.hass.async_add_executor_job(
                    functools.partial(
                        self.session.get,
                        f"{self.url}{API_INFO}",
                        auth=self.auth,
                        timeout=10,
                    )
                )

                if response.status_code == 401:
                    raise AuthenticationFailed("Invalid username or password")

                response.raise_for_status()
                data_info = response.json().get("result", {})

                # Fetch ATX status (single-device path; reflects the ACTIVE port)
                try:
                    response_atx = await self.hass.async_add_executor_job(
                        functools.partial(
                            self.session.get,
                            f"{self.url}{API_ATX}",
                            auth=self.auth,
                            timeout=10,
                        )
                    )
                    if response_atx.status_code == 200:
                        data_atx = response_atx.json().get("result", {})
                        _LOGGER.debug("ATX status: %s", data_atx)
                    else:
                        _LOGGER.debug(
                            "ATX endpoint not available (status %s)",
                            response_atx.status_code,
                        )
                        data_atx = {}
                except Exception as atx_err:
                    _LOGGER.debug("Could not fetch ATX status: %s", atx_err)
                    data_atx = {}

                # Fetch switch state for multi-port devices (routing, links,
                # per-unit ATX LED arrays once channels are registered).
                data_switch = None
                if self.multiport:
                    try:
                        response_switch = await self.hass.async_add_executor_job(
                            functools.partial(
                                self.session.get,
                                f"{self.url}{API_SWITCH}",
                                auth=self.auth,
                                timeout=10,
                            )
                        )
                        if response_switch.status_code == 200:
                            data_switch = response_switch.json().get("result", {})
                        else:
                            _LOGGER.debug(
                                "Switch endpoint not available (status %s)",
                                response_switch.status_code,
                            )
                    except Exception as switch_err:
                        _LOGGER.debug("Could not fetch switch state: %s", switch_err)

                data_info["atx"] = self._normalize_atx(data_atx, data_switch)
                if data_switch is not None:
                    data_info["switch"] = {
                        "active_port": data_switch.get("summary", {}).get(
                            "active_port", -1
                        ),
                        "active_id": data_switch.get("summary", {}).get("active_id"),
                        "video_links": data_switch.get("video", {}).get("links", []),
                        "usb_otg_links": data_switch.get("usb_otg", {}).get(
                            "links", []
                        ),
                        "ports": [
                            {
                                "id": p.get("id"),
                                "name": p.get("name"),
                                "unit": p.get("unit"),
                                "channel": p.get("channel"),
                            }
                            for p in data_switch.get("model", {}).get("ports", [])
                        ],
                    }
                data_info["port"] = self.port

                _LOGGER.debug("Received GLKVM Info from %s", self.url)
                return data_info

            except AuthenticationFailed as auth_err:
                _LOGGER.error("Authentication failed: %s", auth_err)
                raise UpdateFailed(f"Authentication failed: {auth_err}") from auth_err
            except requests.exceptions.RequestException as err:
                retries += 1
                if retries < max_retries:
                    _LOGGER.warning(
                        "Error communicating with API: %s. Retrying in %s seconds",
                        err,
                        backoff_time,
                    )
                    await asyncio.sleep(backoff_time)
                    backoff_time *= 2
                else:
                    _LOGGER.error(
                        "Max retries exceeded. Error communicating with API: %s", err
                    )
                    raise UpdateFailed(f"Error communicating with API: {err}") from err
            except (ValueError, KeyError) as e:
                _LOGGER.error("Data processing error: %s", e)
                raise UpdateFailed(f"Data processing error: {e}") from e
            finally:
                if self.cert_file_path and os.path.exists(self.cert_file_path):
                    os.remove(self.cert_file_path)
        return None

    def _normalize_atx(self, data_atx: dict, data_switch: dict | None) -> dict:
        """Produce the per-port ATX view entities consume.

        Priority:
        1. Per-unit ATX LED arrays from /api/switch (populated once the
           Comet-x has channels registered): port N -> index N-1.
        2. The single-device /api/atx state — authoritative, but it only
           reflects the CURRENTLY ACTIVE port. Only attribute it to this
           entry when this entry's port is the active one.
        """
        if data_switch:
            atx = data_switch.get("atx", {}) or {}
            leds = atx.get("leds", {}) or {}
            power_arr = leds.get("power") or []
            hdd_arr = leds.get("hdd") or []
            busy_arr = atx.get("busy") or []
            idx = port_to_index(self.port)
            if idx < len(power_arr):
                normalized = {
                    "power": "on" if power_arr[idx] else "off",
                    "leds": {
                        "power": power_arr[idx],
                        "hdd": hdd_arr[idx] if idx < len(hdd_arr) else None,
                    },
                    "busy": busy_arr[idx] if idx < len(busy_arr) else False,
                    "enabled": True,
                    "source": "switch",
                }
                return normalized

        # Fall back to the legacy single-device view.
        if data_atx and self.multiport:
            active_port = (data_switch or {}).get("summary", {}).get("active_port", -1)
            if active_port != port_to_index(self.port):
                # /api/atx describes a different port; not ours to report.
                return {}
        return data_atx or {}

    async def _post(self, path: str, params: dict[str, Any]) -> requests.Response:
        """POST to the device API."""
        if not self.session:
            await self._create_session()
        return await self.hass.async_add_executor_job(
            functools.partial(
                self.session.post,
                f"{self.url}{path}",
                params=params,
                auth=self.auth,
                timeout=10,
            )
        )

    async def async_atx(
        self,
        *,
        action: str | None = None,
        button: str | None = None,
    ) -> bool:
        """Run an ATX operation for this entry's port.

        Multi-port (Comet-x): use the port-scoped /api/switch/atx routes —
        they target the given port directly (confirmed against firmware:
        the port is translated and the ATX click is per-port; no
        set_active needed for control).
        Single-device: use the legacy /api/atx routes.

        Returns True on success. Handles 409 AtxIsBusyError with backoff
        and schedules a delayed refresh since ATX ops are momentary.
        """
        if action is None and button is None:
            raise ValueError("async_atx requires action or button")

        params: dict[str, Any] = {}
        if self.multiport:
            path = API_SWITCH_ATX_POWER if action else API_SWITCH_ATX_CLICK
            params["port"] = self.port
        else:
            path = API_ATX_POWER if action else API_ATX_CLICK
            params = {}
        if action:
            params["action"] = action
        else:
            params["button"] = button

        attempt = 0
        while True:
            try:
                response = await self._post(path, params)
            except requests.exceptions.RequestException as err:
                _LOGGER.error("Error sending ATX command %s: %s", params, err)
                return False

            if response.status_code == 200:
                _LOGGER.info("ATX command %s sent successfully", params)
                break

            if (
                response.status_code == 409
                and attempt < ATX_BUSY_RETRIES
            ):
                # AtxIsBusyError: another ATX op is in flight. Back off.
                attempt += 1
                _LOGGER.warning(
                    "ATX busy (409) for %s; retrying in %ss (attempt %d)",
                    params,
                    ATX_BUSY_BACKOFF_SECONDS,
                    attempt,
                )
                await asyncio.sleep(ATX_BUSY_BACKOFF_SECONDS)
                continue

            _LOGGER.error(
                "ATX command %s failed with status %s: %s",
                params,
                response.status_code,
                response.text,
            )
            return False

        # ATX transitions take a few seconds to settle; refresh after a delay.
        self._schedule_settled_refresh()
        return True

    def _schedule_settled_refresh(self) -> None:
        """Refresh state after the ATX operation has had time to settle."""

        async def _refresh_later() -> None:
            await asyncio.sleep(ATX_SETTLE_SECONDS)
            await self.async_request_refresh()

        self.hass.async_create_task(_refresh_later())
