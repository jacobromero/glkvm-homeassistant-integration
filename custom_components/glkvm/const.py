"""Constants for the GLKVM integration."""

DOMAIN = "glkvm"
CONF_MODEL = "model"
CONF_HOST = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CERTIFICATE = "tls-certificate"
CONF_SERIAL = "serial"
CONF_PORT = "port"
DEFAULT_HOST = "glkvm.local"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
DEFAULT_PORT = 1
MANUFACTURER = "GLiNet"
MAX_PORTS = 4

# ATX Power Control Actions
ATX_ACTION_POWER_ON = "on"
ATX_ACTION_POWER_OFF = "off"
ATX_ACTION_POWER_OFF_HARD = "off_hard"
ATX_ACTION_RESET_HARD = "reset_hard"

# ATX Click Buttons (momentary press simulation)
ATX_BUTTON_POWER = "power"
ATX_BUTTON_POWER_LONG = "power_long"
ATX_BUTTON_RESET = "reset"

# ATX API Endpoints (single-device / legacy path)
API_ATX = "/api/atx"
API_ATX_POWER = "/api/atx/power"
API_ATX_CLICK = "/api/atx/click"
API_INFO = "/api/info"

# Switch API Endpoints (Comet-x multi-port path)
API_SWITCH = "/api/switch"
API_SWITCH_ATX_POWER = "/api/switch/atx/power"
API_SWITCH_ATX_CLICK = "/api/switch/atx/click"
API_SWITCH_ACTIVE = "/api/switch/set_active"

# Shutdown mode options (for switch turn_off behavior)
CONF_SHUTDOWN_MODE = "shutdown_mode"
SHUTDOWN_MODE_GRACEFUL = "graceful"
SHUTDOWN_MODE_FORCE = "force"
