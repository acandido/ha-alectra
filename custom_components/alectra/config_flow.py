"""Config flow for Alectra Green Button integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .auth import AlectraOAuth2Implementation
from .const import (
    CONF_API_URL,
    CONF_AUTHORIZATION_URI,
    CONF_SCOPE,
    CONF_SUBSCRIPTION_URI,
    CONF_WEBHOOK_ID,
    DEFAULT_API_URL,
    DEFAULT_SCOPE,
    DEFAULT_WEBHOOK_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AlectraFlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Handle the Alectra Green Button OAuth2 config flow."""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data to include in the authorize URL."""
        return {"scope": DEFAULT_SCOPE}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        # Register OAuth2 implementation so it's available for the flow
        config_entry_oauth2_flow.async_register_implementation(
            self.hass,
            DOMAIN,
            AlectraOAuth2Implementation(self.hass),
        )
        return await super().async_step_user(user_input)

    async def async_step_endpoints(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow user to configure API endpoints."""
        if user_input is not None:
            self.context["api_url"] = user_input.get(CONF_API_URL, DEFAULT_API_URL)
            self.context["scope"] = user_input.get(CONF_SCOPE, DEFAULT_SCOPE)
            return await super().async_step_user()

        return self.async_show_form(
            step_id="endpoints",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_URL, default=DEFAULT_API_URL): str,
                    vol.Required(CONF_SCOPE, default=DEFAULT_SCOPE): str,
                }
            ),
        )

    async def async_oauth_create_entry(
        self, data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create the config entry after successful OAuth2 auth.

        The Green Button token response includes extra fields:
        - resourceURI: the Subscription endpoint for this customer
        - authorizationURI: the Authorization resource URL
        """
        token = data.get("token", {})
        subscription_uri = token.get("resourceURI", "")
        authorization_uri = token.get("authorizationURI", "")

        if not subscription_uri:
            _LOGGER.warning(
                "Token response did not include resourceURI. "
                "You may need to configure the subscription URI manually"
            )

        data[CONF_SUBSCRIPTION_URI] = subscription_uri
        data[CONF_AUTHORIZATION_URI] = authorization_uri
        data[CONF_API_URL] = self.context.get("api_url", DEFAULT_API_URL)
        data[CONF_SCOPE] = self.context.get("scope", DEFAULT_SCOPE)
        data[CONF_WEBHOOK_ID] = DEFAULT_WEBHOOK_ID

        await self.async_set_unique_id(subscription_uri or DOMAIN)
        self._abort_if_unique_id_configured()

        title = "Alectra Green Button"
        if subscription_uri:
            # Extract a short identifier from the subscription URI
            parts = subscription_uri.rstrip("/").split("/")
            if len(parts) >= 2:
                title = f"Alectra ({parts[-1]})"

        return self.async_create_entry(title=title, data=data)
