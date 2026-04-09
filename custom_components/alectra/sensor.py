"""Sensor platform for Alectra Green Button integration."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlectraCoordinator
from .model import UOM_WH, MeterReading, UsagePoint

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alectra sensors from a config entry."""
    coordinator: AlectraCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    if coordinator.data:
        for usage_point in coordinator.data:
            _LOGGER.info(
                "Creating sensors for UsagePoint: %s (%s), "
                "meter_readings=%d, usage_summaries=%d",
                usage_point.id,
                usage_point.title,
                len(usage_point.meter_readings),
                len(usage_point.usage_summaries),
            )

            # Sensors from MeterReading/IntervalBlock data (detailed intervals)
            for meter_reading in usage_point.meter_readings:
                entities.append(
                    AlectraEnergySensor(
                        coordinator, entry, usage_point, meter_reading
                    )
                )
                if _has_cost_data(meter_reading):
                    entities.append(
                        AlectraCostSensor(
                            coordinator, entry, usage_point, meter_reading
                        )
                    )
                entities.append(
                    AlectraPowerSensor(
                        coordinator, entry, usage_point, meter_reading
                    )
                )

            # Sensors from UsageSummary data (billing period summaries)
            if usage_point.usage_summaries:
                entities.append(
                    AlectraBillingConsumptionSensor(
                        coordinator, entry, usage_point
                    )
                )
                entities.append(
                    AlectraBillingCostSensor(
                        coordinator, entry, usage_point
                    )
                )
                entities.append(
                    AlectraCurrentConsumptionSensor(
                        coordinator, entry, usage_point
                    )
                )

                # Create sensors for billing line items with amounts
                summary = usage_point.usage_summaries[-1]
                for item in summary.line_items:
                    if item.amount is not None:
                        entities.append(
                            AlectraBillingLineItemSensor(
                                coordinator, entry, usage_point, item.note
                            )
                        )

            # Always add a status sensor per usage point
            entities.append(
                AlectraStatusSensor(coordinator, entry, usage_point)
            )

    if not entities:
        _LOGGER.info(
            "No usage points found. Creating placeholder status sensor."
        )
        entities.append(AlectraStatusSensor(coordinator, entry))

    _LOGGER.info("Creating %d sensors total", len(entities))
    async_add_entities(entities)


def _has_cost_data(meter_reading: MeterReading) -> bool:
    """Check if any interval readings contain cost data."""
    for block in meter_reading.interval_blocks:
        for reading in block.readings:
            if reading.cost is not None:
                return True
    return False


def _make_device_info(entry: ConfigEntry, usage_point: UsagePoint) -> DeviceInfo:
    """Create device info for a usage point."""
    return DeviceInfo(
        identifiers={(DOMAIN, usage_point.id)},
        name=f"Alectra {usage_point.title}",
        manufacturer="Alectra Utilities",
        model="Green Button Meter",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://alectradc.savagedata.com/",
    )


def _slugify(text: str) -> str:
    """Create a slug from text for use in unique IDs."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


class AlectraBillingConsumptionSensor(
    CoordinatorEntity[AlectraCoordinator], SensorEntity
):
    """Sensor for billing period energy consumption from UsageSummary."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_has_entity_name = True
    _attr_icon = "mdi:meter-electric"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point_id = usage_point.id
        self._attr_unique_id = f"{entry.entry_id}_billing_energy_{usage_point.id}"
        self._attr_name = "Billing Period Consumption"
        self._attr_device_info = _make_device_info(entry, usage_point)

    @property
    def native_value(self) -> float | None:
        """Return the billing period consumption in kWh."""
        up = self._find_usage_point()
        if not up or not up.usage_summaries:
            return None
        summary = up.usage_summaries[-1]
        return summary.consumption_kwh

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return billing period details."""
        up = self._find_usage_point()
        if not up or not up.usage_summaries:
            return None
        summary = up.usage_summaries[-1]
        attrs = {}
        if summary.billing_period_start:
            attrs["billing_period_start"] = datetime.fromtimestamp(
                summary.billing_period_start, tz=timezone.utc
            ).isoformat()
        if summary.billing_period_duration:
            attrs["billing_period_days"] = round(
                summary.billing_period_duration / 86400, 1
            )
        if summary.overall_consumption_value is not None:
            attrs["raw_value"] = summary.overall_consumption_value
            attrs["power_of_ten"] = summary.overall_consumption_power_of_ten
        attrs["total_summaries"] = len(up.usage_summaries)
        return attrs

    def _find_usage_point(self) -> UsagePoint | None:
        if not self.coordinator.data:
            return None
        for up in self.coordinator.data:
            if up.id == self._usage_point_id:
                return up
        return None


class AlectraBillingCostSensor(
    CoordinatorEntity[AlectraCoordinator], SensorEntity
):
    """Sensor for billing period total cost from UsageSummary."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "CAD"
    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-usd"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point_id = usage_point.id
        self._attr_unique_id = f"{entry.entry_id}_billing_cost_{usage_point.id}"
        self._attr_name = "Billing Period Cost"
        self._attr_device_info = _make_device_info(entry, usage_point)

    @property
    def native_value(self) -> float | None:
        """Return the billing period cost in dollars."""
        up = self._find_usage_point()
        if not up or not up.usage_summaries:
            return None
        summary = up.usage_summaries[-1]
        cost = summary.cost_dollars
        return round(cost, 2) if cost is not None else None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return cost details."""
        up = self._find_usage_point()
        if not up or not up.usage_summaries:
            return None
        summary = up.usage_summaries[-1]
        attrs = {}
        if summary.cost_value is not None:
            attrs["raw_value"] = summary.cost_value
            attrs["power_of_ten"] = summary.cost_power_of_ten
        if summary.currency is not None:
            from .model import CURRENCY_NAMES
            attrs["currency"] = CURRENCY_NAMES.get(
                summary.currency, str(summary.currency)
            )
        if summary.billing_period_start:
            attrs["billing_period_start"] = datetime.fromtimestamp(
                summary.billing_period_start, tz=timezone.utc
            ).isoformat()
        if summary.billing_period_duration:
            attrs["billing_period_days"] = round(
                summary.billing_period_duration / 86400, 1
            )
        return attrs

    def _find_usage_point(self) -> UsagePoint | None:
        if not self.coordinator.data:
            return None
        for up in self.coordinator.data:
            if up.id == self._usage_point_id:
                return up
        return None


class AlectraCurrentConsumptionSensor(
    CoordinatorEntity[AlectraCoordinator], SensorEntity
):
    """Sensor for current billing period consumption (updated mid-cycle)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_has_entity_name = True
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point_id = usage_point.id
        self._attr_unique_id = (
            f"{entry.entry_id}_current_energy_{usage_point.id}"
        )
        self._attr_name = "Current Period Consumption"
        self._attr_device_info = _make_device_info(entry, usage_point)

    @property
    def native_value(self) -> float | None:
        """Return current billing period consumption in kWh."""
        up = self._find_usage_point()
        if not up or not up.usage_summaries:
            return None
        summary = up.usage_summaries[-1]
        return summary.current_consumption_kwh

    def _find_usage_point(self) -> UsagePoint | None:
        if not self.coordinator.data:
            return None
        for up in self.coordinator.data:
            if up.id == self._usage_point_id:
                return up
        return None


class AlectraBillingLineItemSensor(
    CoordinatorEntity[AlectraCoordinator], SensorEntity
):
    """Sensor for an individual billing line item (e.g., Delivery Charge)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "CAD"
    _attr_has_entity_name = True
    _attr_icon = "mdi:receipt-text"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
        item_note: str,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point_id = usage_point.id
        self._item_note = item_note
        slug = _slugify(item_note)
        self._attr_unique_id = (
            f"{entry.entry_id}_line_{slug}_{usage_point.id}"
        )
        self._attr_name = item_note
        self._attr_device_info = _make_device_info(entry, usage_point)

    @property
    def native_value(self) -> float | None:
        """Return the line item amount in dollars."""
        up = self._find_usage_point()
        if not up or not up.usage_summaries:
            return None
        summary = up.usage_summaries[-1]
        for item in summary.line_items:
            if item.note == self._item_note and item.amount is not None:
                return item.amount_dollars
        return None

    def _find_usage_point(self) -> UsagePoint | None:
        if not self.coordinator.data:
            return None
        for up in self.coordinator.data:
            if up.id == self._usage_point_id:
                return up
        return None


class AlectraEnergySensor(CoordinatorEntity[AlectraCoordinator], SensorEntity):
    """Sensor for electricity consumption in kWh from interval data."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_has_entity_name = True
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
        meter_reading: MeterReading,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point = usage_point
        self._meter_reading = meter_reading
        self._key = f"{usage_point.id}_{meter_reading.id}"
        self._attr_unique_id = f"{entry.entry_id}_energy_{self._key}"
        self._attr_name = "Energy Consumption"
        self._attr_device_info = _make_device_info(entry, usage_point)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self.coordinator.get_cumulative_kwh(self._key)

    @property
    def extra_state_attributes(self) -> dict | None:
        reading = self.coordinator.get_latest_reading(self._key)
        if not reading:
            return None
        return {
            "last_interval_start": datetime.fromtimestamp(
                reading.start, tz=timezone.utc
            ).isoformat(),
            "last_interval_duration_seconds": reading.duration,
            "last_interval_raw_value": reading.value,
        }


class AlectraPowerSensor(CoordinatorEntity[AlectraCoordinator], SensorEntity):
    """Sensor showing average power (W) for the most recent interval."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_has_entity_name = True
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
        meter_reading: MeterReading,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point = usage_point
        self._meter_reading = meter_reading
        self._key = f"{usage_point.id}_{meter_reading.id}"
        self._attr_unique_id = f"{entry.entry_id}_power_{self._key}"
        self._attr_name = "Average Power"
        self._attr_device_info = _make_device_info(entry, usage_point)

    @property
    def native_value(self) -> float | None:
        reading = self.coordinator.get_latest_reading(self._key)
        if not reading or reading.duration == 0:
            return None
        rt = self._meter_reading.reading_type
        if not rt:
            return None
        energy_wh = reading.value * rt.multiplier
        if rt.uom == UOM_WH:
            hours = reading.duration / 3600.0
            if hours > 0:
                return round(energy_wh / hours, 1)
        return None


class AlectraCostSensor(CoordinatorEntity[AlectraCoordinator], SensorEntity):
    """Sensor for electricity cost from interval data."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "CAD"
    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-usd"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint,
        meter_reading: MeterReading,
    ) -> None:
        super().__init__(coordinator)
        self._usage_point = usage_point
        self._meter_reading = meter_reading
        self._key = f"{usage_point.id}_{meter_reading.id}"
        self._attr_unique_id = f"{entry.entry_id}_cost_{self._key}"
        self._attr_name = "Energy Cost"
        self._attr_device_info = _make_device_info(entry, usage_point)

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        total_cost = 0
        found = False
        for up in self.coordinator.data:
            for mr in up.meter_readings:
                if f"{up.id}_{mr.id}" != self._key:
                    continue
                cost_multiplier = 1e-5
                if mr.reading_type and mr.reading_type.currency is not None:
                    cost_multiplier = mr.reading_type.multiplier
                for block in mr.interval_blocks:
                    for reading in block.readings:
                        if reading.cost is not None:
                            total_cost += reading.cost * cost_multiplier
                            found = True
        return round(total_cost, 2) if found else None


class AlectraStatusSensor(CoordinatorEntity[AlectraCoordinator], SensorEntity):
    """Status sensor for the usage point / integration."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:information-outline"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
        usage_point: UsagePoint | None = None,
    ) -> None:
        super().__init__(coordinator)
        if usage_point:
            self._attr_unique_id = (
                f"{entry.entry_id}_status_{usage_point.id}"
            )
            self._attr_name = "Connection Status"
            self._attr_device_info = _make_device_info(entry, usage_point)
        else:
            self._attr_unique_id = f"{entry.entry_id}_status"
            self._attr_name = "Alectra Green Button Status"

    @property
    def native_value(self) -> str:
        if self.coordinator.data:
            return "Connected"
        if self.coordinator.last_update_success is False:
            return "Error"
        return "Waiting for data"
