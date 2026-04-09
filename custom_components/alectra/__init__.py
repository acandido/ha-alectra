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
    DEFAULT_API_URL,
    DEFAULT_WEBHOOK_ID,
    DOMAIN,
)
from .coordinator import AlectraCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alectra Green Button from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    subscription_uri = entry.data.get(CONF_SUBSCRIPTION_URI, "")
    api_url = entry.data.get(CONF_API_URL, DEFAULT_API_URL)

    _LOGGER.info("Subscription URI: %s", subscription_uri)
    _LOGGER.info("API URL: %s", api_url)
    _LOGGER.info("Token data keys: %s", list(entry.data.get("token", {}).keys()))

    if not subscription_uri:
        _LOGGER.error(
            "No subscription URI configured. "
            "The OAuth token response should have included a resourceURI"
        )
        return False

    client = AlectraApiClient(session, subscription_uri, api_url)
    coordinator = AlectraCoordinator(hass, client)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register webhook for Green Button push notifications
    webhook.async_register(
        hass,
        DOMAIN,
        "Alectra Green Button",
        DEFAULT_WEBHOOK_ID,
        _handle_webhook,
        allowed_methods=["POST"],
    )
    _LOGGER.info(
        "Alectra Green Button webhook registered at: %s",
        webhook.async_generate_url(hass, DEFAULT_WEBHOOK_ID),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Alectra Green Button config entry."""
    webhook.async_unregister(hass, DEFAULT_WEBHOOK_ID)
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
        _LOGGER.info(
            "Received Green Button notification (webhook_id=%s): %s",
            webhook_id,
            body[:1000],
        )
    except Exception:
        _LOGGER.exception("Error reading webhook body")
        return web.Response(status=400)

    # If we have coordinators, trigger a refresh
    for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
        if isinstance(coordinator, AlectraCoordinator):
            _LOGGER.info(
                "Green Button notification received, triggering data refresh "
                "for entry %s",
                entry_id,
            )
            await coordinator.async_request_refresh()

    return web.Response(status=200, text="OK")
