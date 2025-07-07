"""Σταθερές για την ενσωμάτωση ΔΕΔΔΗΕ τηλεμετρία καταναλώσεων."""

from datetime import timedelta

DOMAIN = "deddie_metering"
DEFAULT_INTERVAL_HOURS = 8
DEFAULT_INITIAL_DAYS = 364  # Προεπιλογή: 1 έτος πριν το setup
API_URL = "https://apps.deddie.gr/mdp/rest/getCurves"
CONF_HAS_PV = "has_pv"
CONF_FRESH_SETUP = "fresh_setup"

# Number of consecutive days without PV production
DEFAULT_PV_THRESHOLD = 7

# Period of time for PV detection
DEFAULT_PV_INTERVAL = timedelta(days=1)

# Attribute names
ATTR_PRODUCTION = "produced"
ATTR_INJECTION = "injected"
ATTR_CONSUMPTION = "active"
ATTR_PV_DETECTION = "pv_detection"
