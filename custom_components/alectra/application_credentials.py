"""Application credentials for Alectra Green Button."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import DEFAULT_AUTH_URL, DEFAULT_TOKEN_URL

ALECTRA_ONBOARDING_URL = "https://alectrautilitiesonboarding.savagedata.com/"


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the authorization server for Alectra Green Button."""
    return AuthorizationServer(
        authorize_url=DEFAULT_AUTH_URL,
        token_url=DEFAULT_TOKEN_URL,
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the credentials dialog."""
    return {"more_info_url": ALECTRA_ONBOARDING_URL}
