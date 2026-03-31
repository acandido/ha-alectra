# Alectra Green Button Integration for Home Assistant

A Home Assistant custom integration for [Alectra Utilities](https://alectrautilities.com/) electricity usage data via the [Green Button](https://www.greenbuttondata.org/) Connect My Data (CMD) standard.

## Prerequisites

1. An Alectra Utilities account (Mississauga, Hamilton, St. Catharines, or other Alectra service areas)
2. Registration in Alectra's **Green Button Connect My Data (CMD)** program
3. A registered Green Button third-party application with `client_id` and `client_secret`

### Registering as a Green Button Application

1. Go to the [Alectra Green Button Onboarding Portal](https://alectrautilitiesonboarding.savagedata.com/)
2. Complete the third-party application registration
3. Provide these URIs during registration:
   - **Redirect URI** (OAuth callback): `https://<your-ha-instance>/auth/external/callback`
   - **Notification URI** (push data updates): `https://<your-ha-instance>/api/webhook/alectra_greenbutton`
4. After approval, you'll receive your `client_id`, `client_secret`, and API endpoint URLs

> **Note:** Your Home Assistant instance must be accessible via HTTPS from the internet for both the OAuth redirect and the push notifications to work. If you use Nabu Casa, your URLs would be:
> - Redirect URI: `https://<your-nabu-casa-id>.ui.nabu.casa/auth/external/callback`
> - Notification URI: `https://<your-nabu-casa-id>.ui.nabu.casa/api/webhook/alectra_greenbutton`

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Alectra Green Button" and install
3. Restart Home Assistant

### Manual

1. Copy the `custom_components/alectra` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Alectra Green Button**
3. First, you'll be asked to enter your Application Credentials (client_id and client_secret)
4. You'll be redirected to Alectra's portal to authorize access to your data
5. After authorization, the integration will start fetching your electricity usage data

## Sensors

| Sensor | Description | Unit | Device Class |
|--------|-------------|------|-------------|
| Energy Consumption | Cumulative electricity usage | kWh | energy |
| Average Power | Average power for the most recent interval | W | power |
| Energy Cost | Cumulative electricity cost (if available) | CAD | monetary |

All energy sensors are compatible with the **Home Assistant Energy Dashboard**.

## How It Works

- Uses OAuth2 to authenticate with Alectra's Green Button API (hosted by Savage Data Systems)
- Receives **push notifications** from Alectra when new data is available, triggering an immediate fetch
- Also polls the ESPI Batch Subscription endpoint every hour as a fallback
- Parses Atom XML feeds containing ESPI (Energy Services Provider Interface) data
- Extracts 15-minute or hourly interval readings for electricity consumption

## Troubleshooting

- **No data appearing**: Alectra's Green Button data may have a delay of 24-48 hours
- **OAuth errors**: Ensure your redirect URI matches exactly what was registered
- **Connection errors**: Check that your HA instance can reach `alectrautilitiesgbportal.savagedata.com`

## License

MIT
