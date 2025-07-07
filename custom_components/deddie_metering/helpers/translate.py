import logging

_LOGGER = logging.getLogger("deddie_metering")

TRANSLATIONS = {
    "el": {
        "config.success_notification": (
            "✅ Τα credentials είναι έγκυρα!\n"
            "🔄 Περιμένετε να ολοκληρωθεί η ενημέρωση της συσκευής.\n"
            "📄 Ελέγξτε τα logs για περισσότερες πληροφορίες."
        ),
        "config.success_title": "⚡ ΔΕΔΔΗΕ: Παροχή {supply}",
        "options.token_updated_notification": (
            "✅ Το νέο κλειδί token είναι έγκυρο! \n"
            "📄 Ελέγξτε τα logs για περισσότερες πληροφορίες."
        ),
        "options.token_updated_title": "⚡ ΔΕΔΔΗΕ: Παροχή {supply}",
        "api.token_expired_message": (
            "❌ Tο token πρόσβασης έχει λήξει. Δεν λαμβάνονται νέα δεδομένα. \n"
            "🔑 Παρακαλώ ανανεώστε το στην ιστοσελίδα "
            "https://apps.deddie.gr/mdp/intro.html ."
        ),
        "api.token_expired_title": "⚡ ΔΕΔΔΗΕ: Παροχή {supply}",
        "init.pv_detected_message": (
            "☀ Εντοπίστηκαν εγκατεστημένα φωτοβολταϊκά! \n"
            "🛠 Ενεργοποίηση αισθητήρων Παραγωγής & Έγχυσης.\n"
            "🔄 Περιμένετε να ολοκληρωθεί η ενημέρωση της συσκευής. \n"
            "📄 Ελέγξτε τα logs για περισσότερες πληροφορίες."
        ),
        "init.pv_detected_title": "⚡ ΔΕΔΔΗΕ: Παροχή {supply}",
        "coordinator.pv_warning_message": (
            "❗ Δεν ανιχνεύθηκε παραγωγή από τα "
            "φωτοβολταϊκά σας εδώ και {days} ημέρες.\n"
            "🛠 Ελέγξτε τη λειτουργία του συστήματος για τυχόν βλάβη."
        ),
        "coordinator.pv_warning_title": "⚠ ΔΕΔΔΗΕ: Παροχή {supply}",
        "sensor.attr_until": "Δεδομένα μέχρι:",
        "sensor.attr_last_fetch": "Τελευταία κλήση στο ΔΕΔΔΗΕ API:",
        "sensor.attr_info": "Info:",
        "sensor.attr_info_value": "Τα δεδομένα δεν είναι LIVE",
    },
    "en": {
        "config.success_notification": (
            "✅ HEDNO (API) Credentials are valid!\n"
            "⏳ Please wait for the device update to complete.\n"
            "📄 Check the logs for more information."
        ),
        "config.success_title": "⚡ HEDNO: Supply {supply}",
        "options.token_updated_notification": (
            "✅ The new token is valid! \n " "📄 Check the logs for more information."
        ),
        "options.token_updated_title": "⚡ HEDNO: Supply {supply}",
        "api.token_expired_message": (
            "❌ The access token has expired. No new data is being received. "
            "🔑 Please update it at https://apps.deddie.gr/mdp/intro.html."
        ),
        "api.token_expired_title": "⚡ HEDNO: Supply {supply}",
        "init.pv_detected_message": (
            "☀ Installed photovoltaic panels detected!\n"
            "🛠 Activating Production & Injection sensors.\n"
            "🔄 Please wait for the device update to complete.\n"
            "📄 Check the logs for more information."
        ),
        "init.pv_detected_title": "⚡ HEDNO: Supply {supply}",
        "coordinator.pv_warning_message": (
            "❗ No PV production detected for {days} days.\n"
            "🛠 Please check your system for any faults."
        ),
        "coordinator.pv_warning_title": "⚠ HEDNO: Supply {supply}",
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
