"""API client for Alectra Green Button ESPI endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.helpers import config_entry_oauth2_flow

from .model import UsagePoint
from .parsers.espi import parse_xml

_LOGGER = logging.getLogger(__name__)


class AlectraApiClient:
    """Client for the Green Button ESPI REST API."""

    def __init__(
        self,
        session: config_entry_oauth2_flow.OAuth2Session,
        subscription_uri: str,
        api_url: str,
    ) -> None:
        self._session = session
        self._subscription_uri = subscription_uri
        self._api_url = api_url

    async def async_get_usage_points(
        self,
        published_min: datetime | None = None,
        published_max: datetime | None = None,
    ) -> list[UsagePoint]:
        """Fetch usage data via the Batch Subscription endpoint.

        Uses the batch endpoint to get all usage data in a single request.
        Falls back to individual resource endpoints if batch fails.
        """
        await self._session.async_ensure_token_valid()

        # Build batch URL from subscription URI
        # Subscription URI format: .../espi/1_1/resource/Subscription/{id}
        # Batch URL format: .../espi/1_1/resource/Batch/Subscription/{id}
        batch_url = self._subscription_uri.replace(
            "/Subscription/", "/Batch/Subscription/"
        )

        params: dict[str, str] = {}
        if published_min:
            params["published-min"] = published_min.isoformat()
        if published_max:
            params["published-max"] = published_max.isoformat()

        _LOGGER.debug("Fetching batch data from %s", batch_url)

        resp = await self._session.async_request(
            "GET",
            batch_url,
            params=params if params else None,
            headers={"Accept": "application/atom+xml"},
        )

        if resp.status != 200:
            text = await resp.text()
            _LOGGER.error(
                "Error fetching Green Button data: %s %s", resp.status, text
            )
            raise AlectraApiError(
                f"API returned status {resp.status}: {text[:200]}"
            )

        xml_text = await resp.text()
        _LOGGER.debug("Received %d bytes of XML data", len(xml_text))

        return parse_xml(xml_text)

    async def async_get_recent_usage(
        self, hours: int = 48
    ) -> list[UsagePoint]:
        """Fetch recent usage data (default last 48 hours)."""
        now = datetime.now(tz=timezone.utc)
        return await self.async_get_usage_points(
            published_min=now - timedelta(hours=hours),
            published_max=now,
        )

    async def async_check_connection(self) -> bool:
        """Verify the API connection works."""
        await self._session.async_ensure_token_valid()
        try:
            # Try fetching the service status endpoint
            status_url = f"{self._api_url}/ReadServiceStatus"
            resp = await self._session.async_request("GET", status_url)
            return resp.status == 200
        except Exception:
            _LOGGER.exception("Connection check failed")
            return False


class AlectraApiError(Exception):
    """Error from the Alectra Green Button API."""
