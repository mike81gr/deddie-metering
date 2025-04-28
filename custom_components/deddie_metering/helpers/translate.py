import logging

_LOGGER = logging.getLogger("deddie_metering")

TRANSLATIONS = {
    "el": {
        "config.success_notification": (
            "Τα credentials είναι έγκυρα!\n"
            "Περιμένετε να ολοκληρωθεί η ενημέρωση του αισθητήρα.\n"
            "Ελέγξτε τα logs για περισσότερες πληροφορίες."
        ),
        "config.success_title": "ΔΕΔΔΗΕ: Παροχή {supply}",
        "options.token_updated_notification": (
            "Το νέο κλειδί token είναι έγκυρο! "
            "Ελέγξτε τα logs για περισσότερες πληροφορίες."
        ),
        "options.token_updated_title": "ΔΕΔΔΗΕ: Παροχή {supply}",
        "api.token_expired_message": (
            "Tο token πρόσβασης έχει λήξει. Δεν λαμβάνονται νέα δεδομένα. "
            "Παρακαλώ ανανεώστε το στην ιστοσελίδα "
            "https://apps.deddie.gr/mdp/intro.html ."
        ),
        "api.token_expired_title": "ΔΕΔΔΗΕ: Παροχή {supply}",
        "sensor.attr_until": "Δεδομένα μέχρι:",
        "sensor.attr_last_fetch": "Τελευταία κλήση στο ΔΕΔΔΗΕ API:",
        "sensor.attr_info": "Info:",
        "sensor.attr_info_value": "Τα δεδομένα δεν είναι LIVE",
    },
    "en": {
        "config.success_notification": (
            "HEDSON (API) Credentials are valid!\n"
            "Please wait for the sensor update to complete.\n"
            "Check the logs for more information."
        ),
        "config.success_title": "DEDDIE: Supply {supply}",
        "options.token_updated_notification": (
            "The new token is valid! Check the logs " "for more information."
        ),
        "options.token_updated_title": "DEDDIE: Supply {supply}",
        "api.token_expired_message": (
            "The access token has expired. No new data is being "
            "received. Please update it at "
            "https://apps.deddie.gr/mdp/intro.html."
        ),
        "api.token_expired_title": "DEDDIE: Supply {supply}",
        "sensor.attr_until": "Data up to:",
        "sensor.attr_last_fetch": "Last API fetch:",
        "sensor.attr_info": "Info:",
        "sensor.attr_info_value": "The data is not LIVE",
    },
}


def translate(key: str, language: str = "en", **kwargs) -> str:
    """
    Επιστρέφει μεταφρασμένο string βάσει κλειδιού και γλώσσας.
    Υποστηρίζει format placeholders μέσω kwargs.
    """
    lang = language.lower()
    if lang.startswith("el"):
        language_key = "el"
    else:
        language_key = "en"

    value = TRANSLATIONS.get(language_key, TRANSLATIONS["en"]).get(key)
    if value is None:
        _LOGGER.warning(
            "🔍 Missing translation key: '%s' for language '%s'", key, language_key
        )
        return key

    try:
        return value.format(**kwargs)
    except Exception as e:
        _LOGGER.error("❌ Translation format error for key '%s': %s", key, e)
        return value  # return unformatted if error
