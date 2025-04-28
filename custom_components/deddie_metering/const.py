"""Σταθερές για την ενσωμάτωση ΔΕΔΔΗΕ τηλεμετρία καταναλώσεων."""

DOMAIN = "deddie_metering"
DEFAULT_INTERVAL_HOURS = 8
DEFAULT_INITIAL_DAYS = 364  # Προεπιλογή: 1 έτος πριν το setup
API_URL = "https://apps.deddie.gr/mdp/rest/getCurves"
