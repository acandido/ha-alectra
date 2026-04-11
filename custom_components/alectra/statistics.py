"""Long-term statistics helper for Alectra Green Button data.

Injects historical hourly interval data into Home Assistant's external
statistics so it shows up in the Energy Dashboard with full hourly
resolution, going back as far as the data custodian provides (~40 days
of hourly intervals from Alectra).

External statistics are stored separately from entity state history and
are de-duplicated by (statistic_id, start), so it's safe to call this
every coordinator refresh — HA will just update/replace existing rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_instance,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .model import UOM_WH, MeterReading, UsagePoint

_LOGGER = logging.getLogger(__name__)


def _short_hash(text: str) -> str:
    """Generate a short, stable hash suffix for long ESPI ids."""
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def _stat_id(kind: str, usage_point_id: str, meter_reading_id: str) -> str:
    """Build a stable external statistic_id.

    Format: ``alectra:meter_<up_hash>_<mr_hash>_<kind>``
    """
    up_hash = _short_hash(usage_point_id)
    mr_hash = _short_hash(meter_reading_id)
    return f"{DOMAIN}:meter_{up_hash}_{mr_hash}_{kind}"


async def async_insert_statistics(
    hass: HomeAssistant,
    usage_points: list[UsagePoint],
) -> None:
    """Insert all historical hourly interval data as external statistics.

    Clears existing external statistics for our statistic_ids first so
    corrupted historical rows (e.g., from earlier parser bugs) are wiped,
    then reinserts fresh data from the current CMD response.
    """
    _LOGGER.warning(
        "[ALECTRA-STATS-V2] async_insert_statistics running with cost=rate*kwh fix"
    )
    # Diagnostic heartbeat — write to a synthetic state so we can verify
    # this code path runs from outside the integration. HACS/HA pycache
    # bugs have masked deploys before, so this gives an unambiguous signal.
    try:
        hass.states.async_set(
            "alectra.stats_heartbeat",
            datetime.now(tz=timezone.utc).isoformat(),
            {
                "version": "v2-cost-rate-fix",
                "usage_points": len(usage_points),
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Failed to write heartbeat state")

    # Collect all stat_ids we'll touch so we can clear them first
    stat_ids: list[str] = []
    for up in usage_points:
        for mr in up.meter_readings:
            if not mr.reading_type or mr.reading_type.interval_length != 3600:
                continue
            stat_ids.append(_stat_id("energy", up.id, mr.id))
            stat_ids.append(_stat_id("cost", up.id, mr.id))

    if stat_ids:
        try:
            get_instance(hass).async_clear_statistics(stat_ids)
            _LOGGER.info(
                "Cleared %d existing external statistic(s) for reinsertion",
                len(stat_ids),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to clear existing statistics")

    for up in usage_points:
        for mr in up.meter_readings:
            rt = mr.reading_type
            if not rt:
                continue
            # Only process hourly interval data (1-hour = 3600s).
            # Daily data could also be injected but HA Energy Dashboard
            # works best with hourly resolution.
            if rt.interval_length != 3600:
                continue
            _insert_meter_stats(hass, up, mr)


def _insert_meter_stats(
    hass: HomeAssistant,
    up: UsagePoint,
    mr: MeterReading,
) -> None:
    """Insert statistics for a single hourly MeterReading."""
    rt = mr.reading_type
    if not rt:
        return

    # Collect all readings across blocks, deduped by start timestamp.
    # The CMD batch response contains MANY duplicate IntervalBlocks
    # (overlapping time ranges, repeated hourly readings), so we
    # must dedupe to avoid multi-counting the same hour.
    # Only include per-reading duration == 3600 (1 hour). Some meter
    # readings include a daily cumulative odometer row mixed in with
    # the hourly data; those have duration=86400 and huge raw values
    # (e.g., 192,693 kWh), which would corrupt the stats.
    by_start: dict[int, object] = {}
    total_seen = 0
    for block in mr.interval_blocks:
        for reading in block.readings:
            total_seen += 1
            if reading.duration != 3600:
                continue
            # Keep the last occurrence for any given hour
            by_start[reading.start] = reading
    all_readings = [by_start[k] for k in sorted(by_start)]

    _LOGGER.info(
        "MeterReading %s: %d raw readings → %d unique hourly readings",
        mr.id,
        total_seen,
        len(all_readings),
    )

    if not all_readings:
        return

    # --- Energy statistics ---
    energy_stat_id = _stat_id("energy", up.id, mr.id)
    energy_meta: StatisticMetaData = {
        "source": DOMAIN,
        "statistic_id": energy_stat_id,
        "name": f"Alectra {up.title or 'Meter'} Hourly Energy".strip(),
        "unit_of_measurement": "kWh",
        "unit_class": "energy",
        "mean_type": StatisticMeanType.NONE,
        "has_mean": False,
        "has_sum": True,
    }
    energy_data: list[StatisticData] = []
    energy_running_sum = 0.0
    cost_data: list[StatisticData] = []
    cost_running_sum = 0.0
    has_cost = False

    for reading in all_readings:
        # Convert raw value to kWh
        energy_raw = reading.value * rt.multiplier
        if rt.uom == UOM_WH:
            kwh = energy_raw / 1000.0
        else:
            # Unknown uom; assume already in kWh
            kwh = energy_raw
        energy_running_sum += kwh

        # Hour-aligned UTC timestamp
        start_dt = datetime.fromtimestamp(reading.start, tz=timezone.utc)
        start_dt = start_dt.replace(minute=0, second=0, microsecond=0)

        energy_data.append(
            StatisticData(
                start=start_dt,
                state=round(kwh, 4),
                sum=round(energy_running_sum, 4),
            )
        )

        if reading.cost is not None:
            has_cost = True
            # NOTE: Per ESPI spec, the `cost` field should be the total cost
            # of the interval in 1/100000 of currency. In practice, Alectra
            # publishes the per-kWh RATE here instead (e.g., 9800 → $0.098/kWh
            # off-peak, 15700 → $0.157/kWh mid-peak, 20300 → $0.203/kWh on-peak).
            # We multiply the rate by the interval's energy to get real cost.
            rate_per_kwh = reading.cost / 100000.0
            cost_dollars = rate_per_kwh * kwh
            cost_running_sum += cost_dollars
            cost_data.append(
                StatisticData(
                    start=start_dt,
                    state=round(cost_dollars, 5),
                    sum=round(cost_running_sum, 5),
                )
            )

    _LOGGER.warning(
        "[ALECTRA-STATS-V2] Inserting %d hourly energy statistics for %s "
        "(total %.2f kWh); first cost sample: %s",
        len(energy_data),
        energy_stat_id,
        energy_running_sum,
        cost_data[0] if cost_data else "none",
    )
    # Also expose the first cost sample via state machine for remote inspection
    try:
        sample = cost_data[0] if cost_data else None
        if sample is not None:
            hass.states.async_set(
                "alectra.first_cost_sample",
                str(sample.get("state")),
                {
                    "start": str(sample.get("start")),
                    "sum": str(sample.get("sum")),
                    "first_kwh": round(all_readings[0].value * rt.multiplier / 1000.0, 4),
                    "first_raw_cost": all_readings[0].cost,
                    "stat_id": energy_stat_id,
                },
            )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Failed to write first_cost_sample state")
    async_add_external_statistics(hass, energy_meta, energy_data)

    if has_cost and cost_data:
        cost_stat_id = _stat_id("cost", up.id, mr.id)
        # Currency statistics have no unit converter in HA, so unit_class
        # is omitted entirely. Pre-2026.11 builds also accept it as None,
        # but newer recorder versions reject the key when there's no
        # matching converter, silently dropping the entire batch.
        cost_meta: StatisticMetaData = {
            "source": DOMAIN,
            "statistic_id": cost_stat_id,
            "name": f"Alectra {up.title or 'Meter'} Hourly Cost".strip(),
            "unit_of_measurement": "CAD",
            "mean_type": StatisticMeanType.NONE,
            "has_mean": False,
            "has_sum": True,
        }
        _LOGGER.warning(
            "[ALECTRA-STATS-V2] Inserting %d hourly cost statistics for %s "
            "(total $%.2f); first sample: %s",
            len(cost_data),
            cost_stat_id,
            cost_running_sum,
            cost_data[0],
        )
        try:
            async_add_external_statistics(hass, cost_meta, cost_data)
            hass.states.async_set(
                "alectra.cost_insert_status",
                "ok",
                {
                    "stat_id": cost_stat_id,
                    "rows": len(cost_data),
                    "total": round(cost_running_sum, 2),
                },
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("Cost statistics insertion failed")
            hass.states.async_set(
                "alectra.cost_insert_status",
                "error",
                {
                    "stat_id": cost_stat_id,
                    "error": str(exc),
                    "type": type(exc).__name__,
                },
            )
