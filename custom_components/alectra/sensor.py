"""Sensor platform for Alectra Green Button integration."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

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
            for meter_reading in usage_point.meter_readings:
                entities.append(
                    AlectraEnergySensor(
                        coordinator, entry, usage_point, meter_reading
                    )
                )
                # Add a cost sensor if cost data is available
                if _has_cost_data(meter_reading):
                    entities.append(
                        AlectraCostSensor(
                            coordinator, entry, usage_point, meter_reading
                        )
                    )
            # Add power sensor showing current interval's power
            for meter_reading in usage_point.meter_readings:
                entities.append(
                    AlectraPowerSensor(
                        coordinator, entry, usage_point, meter_reading
                    )
                )

    if not entities:
        # No data yet; create a placeholder that will appear after first update
        _LOGGER.info("No usage data available yet. Sensors will appear after first data fetch")
        entities.append(AlectraStatusSensor(coordinator, entry))

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
        configuration_url="https://alectrautilitiesgbportal.savagedata.com/",
    )


class AlectraEnergySensor(CoordinatorEntity[AlectraCoordinator], SensorEntity):
    """Sensor for electricity consumption in kWh."""

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
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the cumulative energy in kWh."""
        return self.coordinator.get_cumulative_kwh(self._key)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return additional attributes."""
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
        """Calculate average power in watts from the latest interval."""
        reading = self.coordinator.get_latest_reading(self._key)
        if not reading or reading.duration == 0:
            return None

        rt = self._meter_reading.reading_type
        if not rt:
            return None

        # value in Wh (or raw units)
        energy_wh = reading.value * rt.multiplier
        if rt.uom == UOM_WH:
            # Convert Wh over interval to average W
            hours = reading.duration / 3600.0
            if hours > 0:
                return round(energy_wh / hours, 1)
        return None


class AlectraCostSensor(CoordinatorEntity[AlectraCoordinator], SensorEntity):
    """Sensor for electricity cost."""

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
        """Return cumulative cost in CAD."""
        if not self.coordinator.data:
            return None

        total_cost = 0
        found = False
        for up in self.coordinator.data:
            for mr in up.meter_readings:
                if f"{up.id}_{mr.id}" != self._key:
                    continue
                # Default Alectra cost multiplier: 10^-5
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
    """Status sensor shown when no meter data is available yet."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:information-outline"

    def __init__(
        self,
        coordinator: AlectraCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_name = "Alectra Green Button Status"

    @property
    def native_value(self) -> str:
        """Return the connection status."""
        if self.coordinator.data:
            return "Connected"
        if self.coordinator.last_update_success is False:
            return "Error"
        return "Waiting for data"
