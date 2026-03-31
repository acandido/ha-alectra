"""Constants for the Alectra Green Button integration."""

DOMAIN = "alectra"

# Default Alectra Green Button endpoints (Savage Data Systems hosted)
# These are configurable because exact paths are provided after CMD registration.
DEFAULT_BASE_URL = "https://alectrautilitiesgbportal.savagedata.com"
DEFAULT_AUTH_URL = f"{DEFAULT_BASE_URL}/DataCustodian/oauth/authorize"
DEFAULT_TOKEN_URL = f"{DEFAULT_BASE_URL}/DataCustodian/oauth/token"
DEFAULT_API_URL = f"{DEFAULT_BASE_URL}/DataCustodian/espi/1_1/resource"

# Green Button scope: interval metering + usage summary with cost + retail customer
DEFAULT_SCOPE = "FB=4_16_51"

# Polling interval in seconds (1 hour) — fallback if push notifications aren't working
DEFAULT_SCAN_INTERVAL = 3600

# Stable webhook ID for Green Button push notifications.
# Using a fixed ID so the notification URI is known before CMD registration.
# Format: https://<your-ha>/api/webhook/alectra_greenbutton
DEFAULT_WEBHOOK_ID = "alectra_greenbutton"

CONF_AUTHORIZE_URL = "authorize_url"
CONF_TOKEN_URL = "token_url"
CONF_API_URL = "api_url"
CONF_SCOPE = "scope"
CONF_SUBSCRIPTION_URI = "subscription_uri"
CONF_AUTHORIZATION_URI = "authorization_uri"
CONF_WEBHOOK_ID = "webhook_id"
