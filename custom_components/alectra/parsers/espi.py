"""Parser for Green Button ESPI Atom XML feeds."""

from __future__ import annotations

import logging
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as dET

from ..model import (
    IntervalBlock,
    IntervalReading,
    MeterReading,
    ReadingType,
    UsagePoint,
    UsageSummary,
)

_LOGGER = logging.getLogger(__name__)

# XML namespaces used in ESPI Atom feeds
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "espi": "http://naesb.org/espi",
}


def parse_xml(xml_string: str) -> list[UsagePoint]:
    """Parse a Green Button ESPI Atom XML feed into UsagePoint objects."""
    root = dET.fromstring(xml_string)
    feed = GreenButtonFeed(root)
    return feed.parse()


class GreenButtonFeed:
    """Parser for the top-level Atom feed."""

    def __init__(self, root: Element) -> None:
        self._root = root
        self._entries: list[EspiEntry] = []
        self._reading_types: dict[str, ReadingType] = {}
        self._usage_points: dict[str, UsagePoint] = {}
        self._meter_readings: dict[str, MeterReading] = {}
        # Map from entry self-link to parent entry href
        self._parent_map: dict[str, str] = {}

    def parse(self) -> list[UsagePoint]:
        """Parse all entries and assemble the hierarchy."""
        self._collect_entries()
        self._parse_reading_types()
        self._parse_usage_points()
        self._parse_meter_readings()
        self._parse_interval_blocks()
        self._parse_usage_summaries()
        return list(self._usage_points.values())

    def _collect_entries(self) -> None:
        """Collect all Atom entries from the feed."""
        _LOGGER.info(
            "Root tag: %s, children: %s",
            self._root.tag,
            [child.tag for child in self._root],
        )

        # Try with namespace prefix first, then without
        entries = self._root.findall("atom:entry", NS)
        if not entries:
            entries = self._root.findall(
                "{http://www.w3.org/2005/Atom}entry"
            )
        if not entries:
            # Try without namespace entirely
            entries = self._root.findall("entry")

        _LOGGER.info("Found %d entries in feed", len(entries))

        for entry_elem in entries:
            entry = EspiEntry(entry_elem)
            self._entries.append(entry)

            # Log each entry's content for debugging
            _LOGGER.info(
                "Entry: title=%s, self=%s, up=%s, related=%s, "
                "content_children=%s",
                entry.title,
                entry.self_link,
                entry.up_link,
                entry.related_links,
                [child.tag for child in (entry.content or [])],
            )

            # Build parent map from up links
            if entry.up_link and entry.self_link:
                self._parent_map[entry.self_link] = entry.up_link

    def _parse_reading_types(self) -> None:
        """Parse all ReadingType entries."""
        for entry in self._entries:
            content = entry.content
            if content is None:
                continue
            rt_elem = content.find("espi:ReadingType", NS)
            if rt_elem is None:
                continue
            rt = ReadingType(
                id=entry.self_link or "",
                accumulation_behaviour=_int_text(
                    rt_elem, "espi:accumulationBehaviour"
                ),
                commodity=_int_text(rt_elem, "espi:commodity"),
                currency=_int_text(rt_elem, "espi:currency"),
                flow_direction=_int_text(rt_elem, "espi:flowDirection"),
                interval_length=_int_text(rt_elem, "espi:intervalLength") or 0,
                power_of_ten_multiplier=_int_text(
                    rt_elem, "espi:powerOfTenMultiplier"
                )
                or 0,
                uom=_int_text(rt_elem, "espi:uom"),
            )
            self._reading_types[rt.id] = rt
            _LOGGER.debug("Parsed ReadingType: %s (uom=%s)", rt.id, rt.uom)

    def _parse_usage_points(self) -> None:
        """Parse all UsagePoint entries."""
        for entry in self._entries:
            content = entry.content
            if content is None:
                continue
            up_elem = content.find("espi:UsagePoint", NS)
            if up_elem is None:
                continue
            service_kind = None
            sk_elem = up_elem.find("espi:ServiceCategory/espi:kind", NS)
            if sk_elem is not None and sk_elem.text:
                service_kind = int(sk_elem.text)
            up = UsagePoint(
                id=entry.self_link or "",
                title=entry.title or "Usage Point",
                service_kind=service_kind,
            )
            self._usage_points[up.id] = up
            _LOGGER.debug("Parsed UsagePoint: %s (%s)", up.id, up.title)

    def _parse_meter_readings(self) -> None:
        """Parse all MeterReading entries and link to UsagePoints."""
        for entry in self._entries:
            content = entry.content
            if content is None:
                continue
            mr_elem = content.find("espi:MeterReading", NS)
            if mr_elem is None:
                continue
            mr = MeterReading(id=entry.self_link or "")
            # Link reading type via related link
            for link in entry.related_links:
                if link in self._reading_types:
                    mr.reading_type = self._reading_types[link]
                    break
            self._meter_readings[mr.id] = mr
            # Link to parent UsagePoint
            parent_link = self._parent_map.get(mr.id)
            if parent_link and parent_link in self._usage_points:
                self._usage_points[parent_link].meter_readings.append(mr)
            elif self._usage_points:
                # Fallback: attach to first usage point
                next(iter(self._usage_points.values())).meter_readings.append(mr)
            _LOGGER.debug("Parsed MeterReading: %s", mr.id)

    def _parse_interval_blocks(self) -> None:
        """Parse all IntervalBlock entries and link to MeterReadings."""
        for entry in self._entries:
            content = entry.content
            if content is None:
                continue
            ib_elem = content.find("espi:IntervalBlock", NS)
            if ib_elem is None:
                continue

            interval_elem = ib_elem.find("espi:interval", NS)
            start = 0
            duration = 0
            if interval_elem is not None:
                start = _int_text(interval_elem, "espi:start") or 0
                duration = _int_text(interval_elem, "espi:duration") or 0

            readings: list[IntervalReading] = []
            for ir_elem in ib_elem.findall("espi:IntervalReading", NS):
                tp = ir_elem.find("espi:timePeriod", NS)
                ir_start = 0
                ir_duration = 0
                if tp is not None:
                    ir_start = _int_text(tp, "espi:start") or 0
                    ir_duration = _int_text(tp, "espi:duration") or 0

                cost_elem = ir_elem.find("espi:cost", NS)
                cost = int(cost_elem.text) if cost_elem is not None and cost_elem.text else None

                quality = _int_text(ir_elem, "espi:ReadingQuality/espi:quality")

                value = _int_text(ir_elem, "espi:value") or 0
                readings.append(
                    IntervalReading(
                        start=ir_start,
                        duration=ir_duration,
                        value=value,
                        cost=cost,
                        quality=quality,
                    )
                )

            ib = IntervalBlock(start=start, duration=duration, readings=readings)

            # Link to parent MeterReading
            parent_link = self._parent_map.get(entry.self_link or "")
            if parent_link and parent_link in self._meter_readings:
                self._meter_readings[parent_link].interval_blocks.append(ib)
            elif self._meter_readings:
                next(iter(self._meter_readings.values())).interval_blocks.append(ib)

    def _parse_usage_summaries(self) -> None:
        """Parse all ElectricPowerUsageSummary entries."""
        for entry in self._entries:
            content = entry.content
            if content is None:
                continue
            us_elem = content.find("espi:ElectricPowerUsageSummary", NS)
            if us_elem is None:
                continue

            bp = us_elem.find("espi:billingPeriod", NS)
            bp_start = 0
            bp_duration = 0
            if bp is not None:
                bp_start = _int_text(bp, "espi:start") or 0
                bp_duration = _int_text(bp, "espi:duration") or 0

            # Overall consumption
            oc = us_elem.find(
                "espi:overallConsumptionLastPeriod", NS
            )
            oc_value = None
            oc_uom = None
            oc_pot = 0
            if oc is not None:
                oc_value = _int_text(oc, "espi:value")
                oc_uom = _int_text(oc, "espi:ReadingTypeRef/espi:uom")
                oc_pot = _int_text(oc, "espi:powerOfTenMultiplier") or 0

            # Cost
            currency_val = _int_text(us_elem, "espi:currency")
            cost_elem = us_elem.find(
                "espi:costAdditionalLastPeriod", NS
            )
            if cost_elem is None:
                cost_elem = us_elem.find("espi:totalCost", NS)
            cost_value = None
            cost_pot = 0
            if cost_elem is not None:
                cost_value = _int_text(cost_elem, "espi:value")
                cost_pot = _int_text(cost_elem, "espi:powerOfTenMultiplier") or 0

            summary = UsageSummary(
                billing_period_start=bp_start,
                billing_period_duration=bp_duration,
                overall_consumption_value=oc_value,
                overall_consumption_uom=oc_uom,
                overall_consumption_power_of_ten=oc_pot,
                currency=currency_val,
                cost_value=cost_value,
                cost_power_of_ten=cost_pot,
            )

            # Link to parent UsagePoint
            parent_link = self._parent_map.get(entry.self_link or "")
            if parent_link and parent_link in self._usage_points:
                self._usage_points[parent_link].usage_summaries.append(summary)
            elif self._usage_points:
                next(iter(self._usage_points.values())).usage_summaries.append(
                    summary
                )


class EspiEntry:
    """Wrapper around an Atom entry element."""

    def __init__(self, entry: Element) -> None:
        self._entry = entry

    @property
    def title(self) -> str | None:
        """Entry title."""
        elem = self._entry.find("atom:title", NS)
        return elem.text if elem is not None else None

    @property
    def self_link(self) -> str | None:
        """The self link (canonical URL) of this entry."""
        for link in self._entry.findall("atom:link", NS):
            if link.get("rel") == "self":
                return link.get("href")
        return None

    @property
    def up_link(self) -> str | None:
        """The parent link of this entry."""
        for link in self._entry.findall("atom:link", NS):
            if link.get("rel") == "up":
                return link.get("href")
        return None

    @property
    def related_links(self) -> list[str]:
        """All related links of this entry."""
        links = []
        for link in self._entry.findall("atom:link", NS):
            if link.get("rel") == "related":
                href = link.get("href")
                if href:
                    links.append(href)
        return links

    @property
    def content(self) -> Element | None:
        """The content element of this entry."""
        return self._entry.find("atom:content", NS)
