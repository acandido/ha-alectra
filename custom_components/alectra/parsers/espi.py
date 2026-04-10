"""Parser for Green Button ESPI Atom XML feeds."""

from __future__ import annotations

import logging
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as dET

from ..model import (
    BillingLineItem,
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

        # Sort usage summaries by billing period start, newest first
        for up in self._usage_points.values():
            up.usage_summaries.sort(
                key=lambda s: s.billing_period_start, reverse=True
            )

        # If no MeterReadings were found in the feed, create placeholders
        # from the UsagePoint's related links so the caller knows to fetch them
        for up in self._usage_points.values():
            if not up.meter_readings:
                _LOGGER.debug(
                    "UsagePoint %s has no MeterReadings in feed, "
                    "checking related links",
                    up.id,
                )

        return list(self._usage_points.values())

    def _collect_entries(self) -> None:
        """Collect all Atom entries from the feed."""
        _LOGGER.debug(
            "Root tag: %s, children: %s",
            self._root.tag,
            [child.tag for child in self._root],
        )

        entries = self._root.findall("atom:entry", NS)
        if not entries:
            entries = self._root.findall(
                "{http://www.w3.org/2005/Atom}entry"
            )

        _LOGGER.debug("Found %d entries in feed", len(entries))

        for entry_elem in entries:
            entry = EspiEntry(entry_elem)
            self._entries.append(entry)

            _LOGGER.debug(
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

    def _find_parent_usage_point(self, entry_self_link: str) -> UsagePoint | None:
        """Find the parent UsagePoint for an entry, using flexible matching.

        The 'up' link might point to a collection URL (e.g., .../UsageSummary)
        rather than the UsagePoint directly, so we also check if the entry's
        URL contains a known UsagePoint ID.
        """
        # Try direct parent map lookup
        parent_link = self._parent_map.get(entry_self_link)
        if parent_link and parent_link in self._usage_points:
            return self._usage_points[parent_link]

        # Try matching by URL containment — if the entry URL contains
        # a UsagePoint ID path segment, it belongs to that UsagePoint
        for up_id, up in self._usage_points.items():
            # Extract the UsagePoint path portion
            if "/UsagePoint/" in up_id:
                up_path = up_id.split("/UsagePoint/")[0] + "/UsagePoint/" + up_id.split("/UsagePoint/")[1].split("/")[0]
                if up_path in entry_self_link:
                    return up

        # Fallback to first usage point
        if self._usage_points:
            return next(iter(self._usage_points.values()))

        return None

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

            # Store related links for later use (fetching sub-resources)
            up._related_links = entry.related_links

            _LOGGER.debug(
                "Parsed UsagePoint: %s (%s), related links: %s",
                up.id, up.title, entry.related_links,
            )

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
            parent = self._find_parent_usage_point(mr.id)
            if parent:
                parent.meter_readings.append(mr)

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
                tou = _int_text(ir_elem, "espi:tou")
                readings.append(
                    IntervalReading(
                        start=ir_start,
                        duration=ir_duration,
                        value=value,
                        cost=cost,
                        quality=quality,
                        tou=tou,
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
        """Parse all UsageSummary / ElectricPowerUsageSummary entries."""
        for entry in self._entries:
            content = entry.content
            if content is None:
                continue

            # Try both UsageSummary and ElectricPowerUsageSummary
            us_elem = content.find("espi:UsageSummary", NS)
            if us_elem is None:
                us_elem = content.find("espi:ElectricPowerUsageSummary", NS)
            if us_elem is None:
                continue

            _LOGGER.debug(
                "Found UsageSummary entry: %s, children: %s",
                entry.self_link,
                [child.tag for child in us_elem],
            )

            bp = us_elem.find("espi:billingPeriod", NS)
            bp_start = 0
            bp_duration = 0
            if bp is not None:
                bp_start = _int_text(bp, "espi:start") or 0
                bp_duration = _int_text(bp, "espi:duration") or 0

            # Overall consumption
            oc = us_elem.find("espi:overallConsumptionLastPeriod", NS)
            oc_value = None
            oc_uom = None
            oc_pot = 0
            if oc is not None:
                oc_value = _int_text(oc, "espi:value")
                oc_uom = _int_text(oc, "espi:ReadingTypeRef/espi:uom")
                oc_pot = _int_text(oc, "espi:powerOfTenMultiplier") or 0

            # Cost — try billLastPeriod first (total bill), then
            # costAdditionalLastPeriod, then totalCost.
            # Savage Data stores billLastPeriod in mills (10^-3 dollars).
            currency_val = _int_text(us_elem, "espi:currency")
            cost_value = _int_text(us_elem, "espi:billLastPeriod")
            cost_pot = -3  # billLastPeriod is in mills (thousandths of dollar)
            if cost_value is None:
                cost_elem = us_elem.find("espi:costAdditionalLastPeriod", NS)
                if cost_elem is None:
                    cost_elem = us_elem.find("espi:totalCost", NS)
                if cost_elem is not None:
                    cost_value = _int_text(cost_elem, "espi:value")
                    cost_pot = _int_text(cost_elem, "espi:powerOfTenMultiplier") or -3

            # Current billing period consumption
            cc = us_elem.find("espi:currentBillingPeriodOverAllConsumption", NS)
            cc_value = None
            cc_pot = 0
            if cc is not None:
                cc_value = _int_text(cc, "espi:value")
                cc_pot = _int_text(cc, "espi:powerOfTenMultiplier") or 0

            # Parse line items from costAdditionalDetailLastPeriod
            line_items: list[BillingLineItem] = []
            for detail in us_elem.findall(
                "espi:costAdditionalDetailLastPeriod", NS
            ):
                note_elem = detail.find("espi:note", NS)
                note = note_elem.text if note_elem is not None and note_elem.text else ""
                amount = _int_text(detail, "espi:amount")
                unit_cost = _int_text(detail, "espi:unitCost")
                item_kind = _int_text(detail, "espi:itemKind")
                if note:  # Only add items that have a description
                    line_items.append(BillingLineItem(
                        note=note,
                        amount=amount,
                        unit_cost=unit_cost,
                        item_kind=item_kind,
                    ))

            quality = _int_text(us_elem, "espi:qualityOfReading")
            status_ts = _int_text(us_elem, "espi:statusTimeStamp")

            summary = UsageSummary(
                billing_period_start=bp_start,
                billing_period_duration=bp_duration,
                overall_consumption_value=oc_value,
                overall_consumption_uom=oc_uom,
                overall_consumption_power_of_ten=oc_pot,
                currency=currency_val,
                cost_value=cost_value,
                cost_power_of_ten=cost_pot,
                current_consumption_value=cc_value,
                current_consumption_power_of_ten=cc_pot,
                quality_of_reading=quality,
                status_timestamp=status_ts,
                line_items=line_items,
            )

            _LOGGER.debug(
                "Parsed UsageSummary: bp_start=%s, "
                "consumption: value=%s uom=%s pot=%s (%.3f kWh), "
                "cost: value=%s pot=%s ($%.2f), "
                "current_consumption: value=%s pot=%s, "
                "line_items=%d, currency=%s",
                bp_start, oc_value, oc_uom, oc_pot,
                summary.consumption_kwh or 0,
                cost_value, cost_pot,
                summary.cost_dollars or 0,
                cc_value, cc_pot,
                len(line_items), currency_val,
            )
            for item in line_items:
                if item.amount is not None:
                    _LOGGER.debug(
                        "  Line item: %s = $%.2f",
                        item.note, item.amount_dollars or 0,
                    )

            # Link to parent UsagePoint using flexible matching
            parent = self._find_parent_usage_point(entry.self_link or "")
            if parent:
                parent.usage_summaries.append(summary)
                _LOGGER.debug(
                    "Linked UsageSummary to UsagePoint %s", parent.id
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


def _int_text(parent: Element, path: str) -> int | None:
    """Get integer text from a child element."""
    elem = parent.find(path, NS)
    if elem is not None and elem.text:
        try:
            return int(elem.text)
        except ValueError:
            return None
    return None
