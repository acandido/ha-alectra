"""Data models for Green Button ESPI data."""

from __future__ import annotations

from dataclasses import dataclass, field


# ESPI Unit of Measure codes
UOM_WH = 72
UOM_KWH = 999  # Not standard; we normalize Wh -> kWh
UOM_CUBIC_METERS = 119
UOM_CURRENCY = 80

# ESPI Currency codes
CURRENCY_CAD = 124
CURRENCY_USD = 840

# ESPI Service Kind
SERVICE_ELECTRICITY = 0
SERVICE_GAS = 1

# Flow direction
FLOW_FORWARD = 1  # Delivered to customer (consumption)
FLOW_REVERSE = 19  # Received from customer (generation)

UOM_NAMES: dict[int, str] = {
    UOM_WH: "Wh",
    UOM_CUBIC_METERS: "m³",
    UOM_CURRENCY: "currency",
}

CURRENCY_NAMES: dict[int, str] = {
    CURRENCY_CAD: "CAD",
    CURRENCY_USD: "USD",
}

SERVICE_NAMES: dict[int, str] = {
    SERVICE_ELECTRICITY: "electricity",
    SERVICE_GAS: "gas",
}


@dataclass
class ReadingType:
    """Describes the type and units of meter readings."""

    id: str
    accumulation_behaviour: int | None = None
    commodity: int | None = None
    currency: int | None = None
    flow_direction: int | None = None
    interval_length: int = 0
    power_of_ten_multiplier: int = 0
    uom: int | None = None

    @property
    def unit_name(self) -> str:
        """Human-readable unit name."""
        if self.uom == UOM_CURRENCY and self.currency is not None:
            return CURRENCY_NAMES.get(self.currency, "currency")
        if self.uom is not None:
            return UOM_NAMES.get(self.uom, f"uom_{self.uom}")
        return "unknown"

    @property
    def multiplier(self) -> float:
        """The power-of-ten multiplier as a float."""
        return 10.0 ** self.power_of_ten_multiplier


@dataclass
class IntervalReading:
    """A single interval reading (one data point)."""

    start: int  # Unix timestamp
    duration: int  # Seconds
    value: int  # Raw value (apply ReadingType multiplier + UoM)
    cost: int | None = None  # Raw cost value (apply cost multiplier)
    quality: int | None = None


@dataclass
class IntervalBlock:
    """A block of interval readings over a time period."""

    start: int  # Unix timestamp
    duration: int  # Seconds
    readings: list[IntervalReading] = field(default_factory=list)


@dataclass
class MeterReading:
    """A collection of interval blocks with associated reading type."""

    id: str
    reading_type: ReadingType | None = None
    interval_blocks: list[IntervalBlock] = field(default_factory=list)


@dataclass
class UsageSummary:
    """A billing period usage summary."""

    billing_period_start: int  # Unix timestamp
    billing_period_duration: int  # Seconds
    overall_consumption_value: int | None = None
    overall_consumption_uom: int | None = None
    overall_consumption_power_of_ten: int = 0
    currency: int | None = None
    cost_value: int | None = None
    cost_power_of_ten: int = 0


@dataclass
class UsagePoint:
    """A metered service point (e.g., an electricity meter)."""

    id: str
    title: str = ""
    service_kind: int | None = None
    meter_readings: list[MeterReading] = field(default_factory=list)
    usage_summaries: list[UsageSummary] = field(default_factory=list)

    @property
    def service_name(self) -> str:
        """Human-readable service type."""
        if self.service_kind is not None:
            return SERVICE_NAMES.get(self.service_kind, f"service_{self.service_kind}")
        return "electricity"  # Default for Alectra
