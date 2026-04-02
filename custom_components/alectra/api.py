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

    async def async_fetch_meter_readings(
        self, usage_points: list[UsagePoint]
    ) -> None:
        """Fetch MeterReading data for UsagePoints that have none.

        The batch endpoint may only return top-level UsagePoint info with
        related links. This follows those links to get the actual readings.
        """
        await self._session.async_ensure_token_valid()

        for up in usage_points:
            if up.meter_readings:
                continue  # Already has data

            # Check for related MeterReading link
            related = getattr(up, "_related_links", [])
            mr_links = [l for l in related if "/MeterReading" in l]

            for mr_link in mr_links:
                _LOGGER.info("Fetching MeterReading from related link: %s", mr_link)

                # Try multiple Accept headers — some servers are picky
                accept_headers = [
                    "application/xml",
                    "application/atom+xml",
                    "text/xml",
                    "*/*",
                ]
                resp = None
                text = ""
                content_type = ""

                for accept in accept_headers:
                    try:
                        resp = await self._session.async_request(
                            "GET",
                            mr_link,
                            headers={"Accept": accept},
                        )
                        text = await resp.text()
                        content_type = resp.headers.get("Content-Type", "")

                        _LOGGER.info(
                            "MeterReading response (Accept: %s): "
                            "status=%s, content-type=%s, length=%d",
                            accept, resp.status, content_type, len(text),
                        )

                        if resp.status == 200:
                            break
                        if resp.status != 406:
                            break
                    except Exception:
                        _LOGGER.exception(
                            "Error with Accept: %s for %s", accept, mr_link
                        )
                        continue

                if resp is None or resp.status != 200 or "text/html" in content_type:
                    _LOGGER.warning(
                        "Could not fetch MeterReading from %s "
                        "(status=%s, content-type=%s)",
                        mr_link,
                        resp.status if resp else "no response",
                        content_type,
                    )
                    continue

                try:
                    if text.strip():
                        _LOGGER.debug("MeterReading XML: %s", text[:3000])
                        sub_points = parse_xml(text)
                        # Merge any meter readings found into this usage point
                        for sp in sub_points:
                            up.meter_readings.extend(sp.meter_readings)
                        if not up.meter_readings:
                            _LOGGER.info(
                                "No meter readings found in sub-feed"
                            )
                except Exception:
                    _LOGGER.exception(
                        "Error parsing MeterReading from %s", mr_link
                    )

    def _build_candidate_urls(self) -> list[str]:
        """Build a list of candidate API URLs to try."""
        sub_uri = self._subscription_uri
        api_url = self._api_url

        urls = []

        # If subscription URI is a full URL, try batch and direct variants
        if sub_uri.startswith("http"):
            # The resourceURI from the token might already be a Batch URL
            # or a plain Subscription URL. Try both forms.
            if "/Batch/Subscription/" in sub_uri:
                # Already a batch URL — use as-is first, then try without Batch
                urls.append(sub_uri)
                urls.append(sub_uri.replace("/Batch/Subscription/", "/Subscription/"))
            elif "/Subscription/" in sub_uri:
                # Plain subscription URL — try batch first, then direct
                urls.append(
                    sub_uri.replace("/Subscription/", "/Batch/Subscription/")
                )
                urls.append(sub_uri)
            else:
                urls.append(sub_uri)
            # UsagePoint under subscription
            plain_sub = sub_uri.replace("/Batch/Subscription/", "/Subscription/")
            urls.append(f"{plain_sub}/UsagePoint")
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
