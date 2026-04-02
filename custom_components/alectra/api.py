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
        """Fetch usage data, trying multiple endpoint patterns."""
        await self._session.async_ensure_token_valid()

        params: dict[str, str] = {}
        if published_min:
            params["published-min"] = published_min.isoformat()
        if published_max:
            params["published-max"] = published_max.isoformat()

        # Try multiple URL patterns since Savage Data may use non-standard paths
        urls_to_try = self._build_candidate_urls()

        last_error: Exception | None = None
        for url in urls_to_try:
            try:
                result = await self._fetch_and_parse(url, params)
                if result is not None:
                    return result
            except AlectraApiError as err:
                _LOGGER.debug("URL %s failed: %s", url, err)
                last_error = err
                continue

        if last_error:
            raise last_error
        return []

    def _build_candidate_urls(self) -> list[str]:
        """Build a list of candidate API URLs to try."""
        sub_uri = self._subscription_uri
        api_url = self._api_url

        urls = []

        # If subscription URI is a full URL, try batch and direct variants
        if sub_uri.startswith("http"):
            # Standard Green Button: /Batch/Subscription/{id}
            if "/Subscription/" in sub_uri:
                urls.append(
                    sub_uri.replace("/Subscription/", "/Batch/Subscription/")
                )
            # Direct subscription URI
            urls.append(sub_uri)
            # UsagePoint under subscription
            urls.append(f"{sub_uri}/UsagePoint")
        else:
            # subscription URI is just an ID, build full URLs
            sub_id = sub_uri.rstrip("/").split("/")[-1] if "/" in sub_uri else sub_uri
            urls.extend([
                f"{api_url}/Batch/Subscription/{sub_id}",
                f"{api_url}/Subscription/{sub_id}",
                f"{api_url}/Subscription/{sub_id}/UsagePoint",
            ])

        _LOGGER.info("Candidate API URLs: %s", urls)
        return urls

    async def _fetch_and_parse(
        self, url: str, params: dict[str, str]
    ) -> list[UsagePoint] | None:
        """Fetch a URL and parse the XML response.

        Returns None if the response is HTML (wrong endpoint).
        Raises AlectraApiError on real errors.
        """
        _LOGGER.info("Trying URL: %s", url)

        resp = await self._session.async_request(
            "GET",
            url,
            params=params if params else None,
            headers={"Accept": "application/atom+xml"},
        )

        text = await resp.text()
        content_type = resp.headers.get("Content-Type", "")
        _LOGGER.info(
            "Response from %s: status=%s, content-type=%s, length=%d",
            url, resp.status, content_type, len(text),
        )

        # If we got HTML back, this isn't the right endpoint
        if "text/html" in content_type or text.strip().startswith("<!DOCTYPE"):
            _LOGGER.warning(
                "Got HTML response from %s (probably Blazor SPA catch-all), skipping",
                url,
            )
            return None

        if resp.status == 401:
            raise AlectraApiError(f"Unauthorized (401) from {url}")

        if resp.status == 403:
            raise AlectraApiError(f"Forbidden (403) from {url}")

        if resp.status == 404:
            _LOGGER.warning("Not found (404) from %s", url)
            return None

        if resp.status != 200:
            _LOGGER.error(
                "Error fetching Green Button data: %s %s", resp.status, text[:500]
            )
            raise AlectraApiError(
                f"API returned status {resp.status}: {text[:200]}"
            )

        if not text.strip():
            _LOGGER.warning("Empty response from %s", url)
            return []

        _LOGGER.debug("Response first 2000 chars: %s", text[:2000])

        try:
            result = parse_xml(text)
            _LOGGER.info(
                "Successfully parsed %d usage points from %s", len(result), url
            )
            return result
        except Exception as err:
            _LOGGER.error(
                "Failed to parse XML from %s: %s\nFirst 1000 chars:\n%s",
                url, err, text[:1000],
            )
            raise AlectraApiError(
                f"Failed to parse API response from {url}: {err}"
            ) from err

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
            status_url = f"{self._api_url}/ReadServiceStatus"
            resp = await self._session.async_request("GET", status_url)
            return resp.status == 200
        except Exception:
            _LOGGER.exception("Connection check failed")
            return False


class AlectraApiError(Exception):
    """Error from the Alectra Green Button API."""
