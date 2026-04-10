# Alectra Green Button Integration for Home Assistant

A Home Assistant custom integration for [Alectra Utilities](https://alectrautilities.com/) electricity usage data via the [Green Button](https://www.greenbuttondata.org/) Connect My Data (CMD) standard.

The integration pulls your hourly interval data, billing period summaries, time-of-use breakdowns, and cost information directly from Alectra's CMD API (hosted by Savage Data Systems) and backfills historical data into Home Assistant's long-term statistics so it shows up in the Energy Dashboard.

## Prerequisites

1. An Alectra Utilities account (Mississauga, Hamilton, St. Catharines, Vaughan, Barrie, or any other Alectra service area)
2. Enrollment in Alectra's **Green Button Connect My Data (CMD)** program via your Alectra customer portal
3. A Home Assistant instance reachable over HTTPS (Nabu Casa Cloud, reverse proxy, or similar)

> **Note:** This integration ships with pre-registered OAuth2 client credentials, so there's no need to register your own third-party application. You just need to be an Alectra customer with CMD enabled on your account.

## Installation

### HACS (Recommended)

1. In HACS, open the menu and choose **Custom repositories**
2. Add `https://github.com/acandido/ha-alectra` as an **Integration**
3. Find **Alectra Green Button** in the HACS integrations list and download it
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/alectra` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Alectra Green Button**
3. You'll be redirected to Alectra's Green Button portal (`AlectraDC.savagedata.com`) to sign in with your Alectra customer credentials and authorize data sharing
4. After authorization, Home Assistant will fetch your usage data and create sensors. On the first refresh, up to two years of historical hourly data is inserted into long-term statistics.

## Sensors

### Interval sensors (per meter)

| Sensor | Description | Unit | Device Class |
|---|---|---|---|
| Hourly Energy | Energy consumed in the most recent hour | kWh | energy |
| Hourly Average Power | Average power during the most recent hour | W | power |
| Hourly Interval Cost | Cost of the most recent hour | CAD | monetary |

The Hourly Energy sensor includes the Time-of-Use period (On-Peak / Mid-Peak / Off-Peak) as an attribute.

### Billing period sensors (per meter)

| Sensor | Description | Unit |
|---|---|---|
| Billing Period Consumption | Total energy consumed in the last completed billing period | kWh |
| Billing Period Cost | Total cost of the last completed billing period | CAD |
| Current Period Consumption | Energy consumed so far in the current billing period | kWh |
| Amount Due | Total amount due for the last billing period | CAD |
| Delivery Charge | Delivery portion of the last bill | CAD |
| Regulatory Charge | Regulatory portion of the last bill | CAD |
| HST | HST portion of the last bill | CAD |
| Ontario Electricity Rebate | Rebate applied on the last bill | CAD |

Additional line items are created dynamically based on what Alectra provides on your bill.

### Long-term statistics

In addition to the above entities, the integration injects hourly history into Home Assistant's external statistics as:

- `alectra:meter_<hash>_energy` — hourly kWh
- `alectra:meter_<hash>_cost` — hourly cost in CAD

These appear under **Developer Tools → Statistics** and can be added to the **Energy Dashboard** (Settings → Dashboards → Energy → Electricity grid → Add consumption) to get a full hourly breakdown going back as far as Alectra has data (typically 1–2 years).

## How It Works

- Uses OAuth2 (Authorization Code flow with `client_secret_basic`) to authenticate against Savage Data Systems' OIDC server at `https://AlectraDC.savagedata.com`
- Polls the ESPI Batch Subscription endpoint every hour to fetch the full subscription payload
- Parses the Atom XML feed containing ESPI (Energy Services Provider Interface) data: UsagePoints, MeterReadings, IntervalBlocks, ReadingTypes, and UsageSummaries
- Extracts hourly interval readings including value, cost, and Time-of-Use code
- Deduplicates overlapping interval blocks and filters out non-hourly readings
- Injects historical hourly data into Home Assistant's long-term statistics for use in the Energy Dashboard
- Also registers a webhook for CMD push notifications; any POST to `/api/webhook/alectra_greenbutton` triggers an immediate refresh

## Troubleshooting

- **No data appearing**: Alectra's Green Button data can have a delay of 24–48 hours after usage. The latest readings you see may lag by a day.
- **OAuth errors on setup**: Make sure your Home Assistant instance is reachable over HTTPS and that you can reach `https://AlectraDC.savagedata.com`.
- **"Implementation not available" on restart**: Usually fixed by fully restarting Home Assistant after an update.
- **Seeing old/incorrect statistics**: The integration clears and re-imports its external statistics on each refresh, so any fix deployed in a new version will self-heal on the next coordinator update.
- **Enable debug logging** for detailed parser output:

  ```yaml
  logger:
    logs:
      custom_components.alectra: debug
  ```

## License

MIT
