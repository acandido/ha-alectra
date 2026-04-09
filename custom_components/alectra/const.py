"""Constants for the Alectra Green Button integration."""

DOMAIN = "alectra"

# Alectra Green Button endpoints (Savage Data Systems hosted)
# Sandbox environment (used during registration/testing)
SANDBOX_BASE_URL = "https://sandboxdc.savagedata.com:4243"
# Production environment
PROD_BASE_URL = "https://alectrautilitiesgbportal.savagedata.com"

# Default to sandbox during development; switch to PROD_BASE_URL for production
DEFAULT_BASE_URL = SANDBOX_BASE_URL
DEFAULT_AUTH_URL = f"{DEFAULT_BASE_URL}/connect/authorize"
DEFAULT_TOKEN_URL = f"{DEFAULT_BASE_URL}/connect/token"
DEFAULT_API_URL = f"{DEFAULT_BASE_URL}/espi/1_1/resource"

# Green Button scope: interval metering (4) + usage summary with cost (16)
DEFAULT_SCOPE = "FB=4_16"

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
