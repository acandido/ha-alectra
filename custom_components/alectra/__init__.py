"""The Alectra Green Button integration."""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import AlectraApiClient
from .const import (
    CONF_API_URL,
    CONF_SUBSCRIPTION_URI,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DEFAULT_WEBHOOK_ID,
    DOMAIN,
)
from .coordinator import AlectraCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alectra Green Button from a config entry."""
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    subscription_uri = entry.data.get(CONF_SUBSCRIPTION_URI, "")
    api_url = entry.data.get(CONF_API_URL, DEFAULT_API_URL)

    if not subscription_uri:
        _LOGGER.error(
            "No subscription URI configured. "
            "The OAuth token response should have included a resourceURI"
        )
        return False

    client = AlectraApiClient(session, subscription_uri, api_url)
    coordinator = AlectraCoordinator(hass, client)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register webhook for Green Button push notifications
    webhook_id = entry.data.get(CONF_WEBHOOK_ID, DEFAULT_WEBHOOK_ID)
    webhook.async_register(
        hass,
        DOMAIN,
        "Alectra Green Button",
        webhook_id,
        _handle_webhook,
        allowed_methods=["POST"],
    )
    _LOGGER.info(
        "Registered Green Button notification webhook: %s",
        webhook.async_generate_url(hass, webhook_id),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Alectra Green Button config entry."""
    webhook_id = entry.data.get(CONF_WEBHOOK_ID, DEFAULT_WEBHOOK_ID)
    webhook.async_unregister(hass, webhook_id)

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle incoming Green Button push notification.

    When Alectra has new data available, it POSTs a notification to this
    endpoint containing a resource URI. We trigger an immediate data refresh.
    """
    try:
        body = await request.text()
        _LOGGER.debug("Received Green Button notification: %s", body[:500])
    except Exception:
        _LOGGER.exception("Error reading webhook body")
        return web.Response(status=400)

    # Find the coordinator for this webhook and trigger a refresh
    for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
        if isinstance(coordinator, AlectraCoordinator):
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.data.get(CONF_WEBHOOK_ID, DEFAULT_WEBHOOK_ID) == webhook_id:
                _LOGGER.info(
                    "Green Button notification received, triggering data refresh"
                )
                await coordinator.async_request_refresh()
                break

    # Green Button spec expects a 200 OK response
    return web.Response(status=200, text="OK")
