# Changelog

## v1.0.0 - Initial Release (2025-04-25)

- Basic data retrieval from the HEDNO API.
- Sensor state restore after restart, with an initial “jump” to 0.0 on fresh install.
- Batch-fetch for historical data and single-fetch for periodic updates.
- **Delete flat states after each update** to keep history UI accurate.
- **Gap detection**: if >7 days since last update, automatically switch to batch-fetch.
- **Options Flow enhancements**:
  - Renew token on-the-fly with persistent notification.
  - Change start date (`initial_time`) triggers re-batching and resets fresh-install flag.
  - Validation and error messages for interval and date inputs.
- Import of statistics into the recorder and correction of future records for data consistency.
- Multi-supply support.
- Internationalization (EN/EL) with complete strings and placeholders.
- Config Flow & Options Flow with credential validation and persistent notifications for token successes/errors.
- Comprehensive installation, configuration, and usage documentation in the README.

## v1.0.0 - Αρχική Έκδοση (25-04-2025)

- Βασική ανάκτηση δεδομένων από το API της ΔΕΔΔΗΕ.
- Μηχανισμός επαναφοράς κατάστασης αισθητήρα μετά από επανεκκίνηση και αρχική «jump» σε 0.0 για fresh install.
- Batch-fetch για ιστορικά δεδομένα και single-fetch για περιοδικές ενημερώσεις.
- **Διαγραφή flat states μετά από κάθε ενημέρωση** για σωστή απεικόνιση ιστορικού.
- **Ανίχνευση κενών δεδομένων (>7 ημερών)** με αυτόματο batch-fetch.
- **Βελτιώσεις Options Flow**:
  - Ανανέωση token “on-the-fly” με persistent notification.
  - Αλλαγή αρχικής ημερομηνίας `initial_time` τρέχει ξανά τα initial batches και επαναφέρει το fresh-install flag.
  - Έλεγχοι και σφάλματα για συχνότητα ενημέρωσης και ημερομηνία.
- Εισαγωγή στατιστικών στο recorder και διόρθωση μελλοντικών («future») εγγραφών για συνέπεια στα δεδομένα.
- Υποστήριξη πολλαπλών παροχών (multi-supply).
- Διεθνής μετάφραση EN/EL με πλήρη strings και placeholders.
- Config Flow & Options Flow με validation των credentials και persistent notifications για επιτυχίες/σφάλματα token.
- Πλήρης τεκμηρίωση εγκατάστασης, ρυθμίσεων και χρήσης στο README.
