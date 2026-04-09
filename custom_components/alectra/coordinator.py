"""DataUpdateCoordinator for Alectra Green Button."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AlectraApiClient, AlectraApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .model import IntervalReading, UsagePoint

_LOGGER = logging.getLogger(__name__)


class AlectraCoordinator(DataUpdateCoordinator[list[UsagePoint]]):
    """Coordinator to fetch Alectra Green Button data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AlectraApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self._latest_readings: dict[str, IntervalReading] = {}
        self._cumulative_kwh: dict[str, float] = {}

    async def _async_update_data(self) -> list[UsagePoint]:
        """Fetch data from the Green Button API."""
        try:
            # Fetch all available data without time filters.
            # The Batch endpoint returns IntervalBlocks only when
            # no published-min/published-max is specified.
            usage_points = await self.client.async_get_usage_points()

            # If batch didn't include MeterReadings, follow related links
            needs_fetch = any(
                not up.meter_readings for up in usage_points
            )
            if needs_fetch:
                _LOGGER.info(
                    "Some UsagePoints have no MeterReadings, "
                    "fetching from related links"
                )
                await self.client.async_fetch_meter_readings(usage_points)

        except AlectraApiError as err:
            raise UpdateFailed(f"Error fetching Alectra data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

        # Process and cache latest readings for each meter
        for up in usage_points:
            for mr in up.meter_readings:
                latest = self._find_latest_reading(mr.interval_blocks)
                if latest:
                    key = f"{up.id}_{mr.id}"
                    self._latest_readings[key] = latest

                    # Calculate cumulative energy from all interval blocks
                    if mr.reading_type:
                        total = self._calculate_total_energy(mr, up.id)
                        self._cumulative_kwh[key] = total

        # Detailed logging of parsed data structure
        for up in usage_points:
            _LOGGER.info(
                "UsagePoint: id=%s, title=%s, service=%s, "
                "meter_readings=%d, usage_summaries=%d",
                up.id, up.title, up.service_name,
                len(up.meter_readings), len(up.usage_summaries),
            )
            for mr in up.meter_readings:
                total_readings = sum(
                    len(b.readings) for b in mr.interval_blocks
                )
                _LOGGER.info(
                    "  MeterReading: id=%s, reading_type=%s, "
                    "interval_blocks=%d, total_readings=%d",
                    mr.id,
                    mr.reading_type.unit_name if mr.reading_type else "none",
                    len(mr.interval_blocks),
                    total_readings,
                )
            for us in up.usage_summaries:
                _LOGGER.info(
                    "  UsageSummary: consumption=%.3f kWh, cost=$%.2f, "
                    "current=%.3f kWh, line_items=%d",
                    us.consumption_kwh or 0,
                    us.cost_dollars or 0,
                    us.current_consumption_kwh or 0,
                    len(us.line_items),
                )

        _LOGGER.info(
            "Updated %d usage points with %d meter readings, %d usage summaries",
            len(usage_points),
            sum(len(up.meter_readings) for up in usage_points),
            sum(len(up.usage_summaries) for up in usage_points),
        )
        return usage_points

    def _find_latest_reading(
        self, interval_blocks: list,
    ) -> IntervalReading | None:
        """Find the most recent interval reading across all blocks."""
        latest: IntervalReading | None = None
        for block in interval_blocks:
            for reading in block.readings:
                if latest is None or reading.start > latest.start:
                    latest = reading
        return latest

    def _calculate_total_energy(self, mr, usage_point_id: str) -> float:
        """Calculate total energy in kWh from all interval readings."""
        from .model import UOM_WH

        total_raw = 0
        for block in mr.interval_blocks:
            for reading in block.readings:
                total_raw += reading.value

        if mr.reading_type:
            multiplier = mr.reading_type.multiplier
            value = total_raw * multiplier
            # Convert Wh to kWh if needed
            if mr.reading_type.uom == UOM_WH:
                value /= 1000.0
            return value
        return float(total_raw)

    def get_latest_reading(self, key: str) -> IntervalReading | None:
        """Get the latest reading for a meter key."""
        return self._latest_readings.get(key)

    def get_cumulative_kwh(self, key: str) -> float | None:
        """Get cumulative kWh for a meter key."""
        return self._cumulative_kwh.get(key)
