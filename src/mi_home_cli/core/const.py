"""API constants.

These values come from observing the public behaviour of the Home Assistant Xiaomi
Home integration (XiaoMi/ha_xiaomi_home); they are not an API contract Xiaomi
promises to outsiders and may change at any time. They are kept in one place here
to make following changes easy.
"""
from __future__ import annotations

# The OAuth client Mi Home registered for the Home Assistant integration.
CLIENT_ID = "2882303761520251711"

OAUTH_AUTH_URL = "https://account.xiaomi.com/oauth2/authorize"
USER_PROFILE_URL = "https://open.account.xiaomi.com/user/profile"

# The Xiaomi account login pages (passport). QR-code login reproduces the API
# calls of the pages a browser lands on after opening the authorization page,
# and only ever talks to this host (independent of the region, which only
# affects the API host used later for the token exchange).
ACCOUNT_HOST = "account.xiaomi.com"
# The endpoint that returns the QR code + long-polling address; the serviceLogin address
# is not hard-coded, we follow the authorization page's 302.
LONG_POLLING_URL = f"https://{ACCOUNT_HOST}/longPolling/loginUrl"
# passport's JSON responses sometimes carry this prefix against JSON hijacking; strip it
# before parsing.
XIAOMI_JSON_PREFIX = "&&&START&&&"
# Default User-Agent of QR-code login requests. The name shown under Xiaomi's
# "logged-in devices" is parsed from this UA — the default is the tool name
# rather than a browser UA, so the account does not fill up with "Chrome"
# entries; users can customise it with `mi config set scan_device_name ...` or
# the MI_SCAN_DEVICE_NAME environment variable. (In testing the account page
# issues a QR code normally for any UA, so there is no need to pose as a browser.)
def _default_web_user_agent() -> str:
    from .. import __version__

    return f"mi-home-cli/{__version__}"


WEB_USER_AGENT = _default_web_user_agent()

# Xiaomi's OAuth server checks redirect_uri against an allowlist. Test findings:
#   * the host must be homeassistant.local:8123; another port, or localhost /
#     127.0.0.1, returns "invalid redirect uri";
#   * the scheme (http/https), path and query are not checked and can be custom.
# So the host here cannot be changed; only the path is ours.
# At token exchange the server compares once more against the information bound
# to the code; in testing, a custom path (/mi-home-cli/callback) + a custom
# device_id (cli.xxx) is rejected with 96002 invalid request, so both the
# callback path and the device_id follow Home Assistant's shape:
#   redirect_uri = http://homeassistant.local:8123/api/webhook/{webhook_id}
#   device_id    = ha.{32 hex chars}
REDIRECT_HOST = "homeassistant.local"
REDIRECT_PORT = 8123
REDIRECT_PATH_PREFIX = "/api/webhook/"
REDIRECT_ORIGIN = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}"
DEVICE_ID_PREFIX = "ha."


def redirect_url(webhook_id: str) -> str:
    return f"{REDIRECT_ORIGIN}{REDIRECT_PATH_PREFIX}{webhook_id}"

DEFAULT_API_HOST = "ha.api.io.mi.com"

CLOUD_SERVERS: dict[str, str] = {
    "cn": "Mainland China",
    "de": "Europe",
    "i2": "India",
    "ru": "Russia",
    "sg": "Singapore",
    "us": "United States",
}

DEFAULT_REGION = "cn"

HTTP_TIMEOUT = 30
# Refresh the access_token early once this share of its lifetime is used up, leaving
# enough margin.
TOKEN_REFRESH_RATIO = 0.7

USER_AGENT = "mi-home-cli"


def api_host(region: str) -> str:
    """The API host for a region."""
    if region == "cn":
        return DEFAULT_API_HOST
    return f"{region}.{DEFAULT_API_HOST}"


def api_base_url(region: str) -> str:
    return f"https://{api_host(region)}"
