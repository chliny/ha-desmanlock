"""Constants for the Desman Lock integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "desmanlock"

CONF_PHONE = "phone"
CONF_LOCK_ID = "lock_id"
CONF_REGION_ID = "region_id"

DEFAULT_REGION_ID = "1"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

PLATFORMS = ["lock", "sensor"]

BASE_URL = "https://nyuwa.dsmxp.com"
APP_VERSION = "6.14.0"
APP_VERSION_CODE = "20828"
USER_AGENT = f"desmanlock/{APP_VERSION}"

ATTR_LOCK_ID = "lock_id"
ATTR_LOCK_MAC = "lock_mac"
ATTR_LOCK_TYPE = "lock_type"
ATTR_OPEN_CONTENT = "open_content"
ATTR_OPEN_LOG_TYPE = "open_log_type"
ATTR_OPEN_TIME = "open_time"
ATTR_OPEN_USER = "open_user"

# RecordType values mapped to DataLockOpenLockDetail.logTypeInt in the app.
LOG_TYPE_OPEN_DOOR = 1
LOG_TYPE_ALARM = 2
LOG_TYPE_ACTION = 3

SERVICE_GET_DYNAMIC_PASSWORD = "get_dynamic_password"
SERVICE_GET_DIGIT_PASSWORDS = "get_digit_passwords"
SERVICE_ADD_DIGIT_PASSWORD = "add_digit_password"
SERVICE_UPDATE_DIGIT_PASSWORD = "update_digit_password"
