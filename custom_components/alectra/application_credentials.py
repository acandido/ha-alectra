"""Application credentials for Alectra Green Button."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import BasicAuth

from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_AUTH_URL, DEFAULT_TOKEN_URL

_LOGGER = logging.getLogger(__name__)

ALECTRA_ONBOARDING_URL = "https://alectrautilitiesonboarding.savagedata.com/"


async def async_get_auth_implementation(
    hass: HomeAssistant,
    auth_domain: str,
    credential: ClientCredential,
) -> AlectraOAuth2Implementation:
    """Return a custom auth implementation using client_secret_basic."""
    return AlectraOAuth2Implementation(
        hass,
        auth_domain,
        credential,
        AuthorizationServer(
            authorize_url=DEFAULT_AUTH_URL,
            token_url=DEFAULT_TOKEN_URL,
        ),
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the credentials dialog."""
    return {"more_info_url": ALECTRA_ONBOARDING_URL}


class AlectraOAuth2Implementation(AuthImplementation):
    """OAuth2 implementation using client_secret_basic (HTTP Basic Auth).

    Savage Data's OIDC server expects credentials via Basic Auth header
    rather than in the POST body (client_secret_post).
    """

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        """Exchange auth code for tokens using Basic Auth."""
        session = async_get_clientsession(self.hass)

        token_data = {
            "grant_type": "authorization_code",
            "code": external_data["code"],
            "redirect_uri": external_data["state"]["redirect_uri"],
        }

        _LOGGER.debug(
            "Exchanging auth code at %s (using client_secret_basic)",
            self.token_url,
        )

        resp = await session.post(
            self.token_url,
            data=token_data,
            auth=BasicAuth(self.client_id, self.client_secret),
        )

        if resp.status >= 400:
            error_text = await resp.text()
            _LOGGER.error(
                "Token exchange failed: %s %s", resp.status, error_text[:500]
            )
            raise Exception(
                f"Token exchange failed ({resp.status}): {error_text[:200]}"
            )

        token_response = await resp.json()
        _LOGGER.info(
            "Token exchange successful. Response keys: %s",
            list(token_response.keys()),
        )

        if "resourceURI" in token_response:
            _LOGGER.info("resourceURI: %s", token_response["resourceURI"])
        if "authorizationURI" in token_response:
            _LOGGER.info("authorizationURI: %s", token_response["authorizationURI"])

        return {
            "access_token": token_response["access_token"],
            "token_type": token_response.get("token_type", "Bearer"),
            "refresh_token": token_response.get("refresh_token", ""),
            "expires_in": token_response.get("expires_in", 3600),
            "scope": token_response.get("scope", ""),
            # Preserve Green Button-specific fields
            "resourceURI": token_response.get("resourceURI", ""),
            "authorizationURI": token_response.get("authorizationURI", ""),
        }

    async def _async_refresh_token(self, token: dict) -> dict:
        """Refresh the access token using Basic Auth."""
        session = async_get_clientsession(self.hass)

        resp = await session.post(
            self.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
            },
            auth=BasicAuth(self.client_id, self.client_secret),
        )

        if resp.status >= 400:
            error_text = await resp.text()
            _LOGGER.error(
                "Token refresh failed: %s %s", resp.status, error_text[:500]
            )
            raise Exception(
                f"Token refresh failed ({resp.status}): {error_text[:200]}"
            )

        new_token = await resp.json()
        return {
            "access_token": new_token["access_token"],
            "token_type": new_token.get("token_type", "Bearer"),
            "refresh_token": new_token.get(
                "refresh_token", token.get("refresh_token", "")
            ),
            "expires_in": new_token.get("expires_in", 3600),
            "scope": new_token.get("scope", ""),
            "resourceURI": new_token.get(
                "resourceURI", token.get("resourceURI", "")
            ),
            "authorizationURI": new_token.get(
                "authorizationURI", token.get("authorizationURI", "")
            ),
        }
