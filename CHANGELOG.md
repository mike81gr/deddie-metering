# Changelog

## v1.0.0 - Initial Release (2025-04-25)

- Consumption data retrieval from the HEDNO API.
- Sensor state restore after restart, with an initial “jump” from 0.0 on new installation.
- Batch-fetch for initial historical data and single-fetch for periodic updates.
- **Delete of sensor flat states after each update** to keep history UI accurate.
- **Gap detection**: if >7 days since last update, automatically switch to batch-fetch.
- **Options Flow enhancements**:
  - Renew token on-the-fly with persistent notification and token key validity check.
  - Change start date (`initial_time`) triggers re-batching.
  - Validation and error messages for interval and date inputs.
- Import of statistics into the recorder and sum correction of "future" records for data consistency.
- Multi-supply support.
- Internationalization (EN/EL) with complete strings and placeholders.
- Config Flow & Options Flow with credential validation and persistent notifications for token successes/errors.
- Comprehensive installation, configuration, and usage documentation in the README.

## v1.0.0 - Αρχική Έκδοση (25-04-2025)

- Ανάκτηση δεδομένων κατανάλωσης από το API της ΔΕΔΔΗΕ.
- Μηχανισμός επαναφοράς κατάστασης αισθητήρα μετά από επανεκκίνηση και αρχικό «jump» από 0.0 για νέα εγκατάσταση.
- Τμηματική ανάκτηση αρχικών ιστορικών δεδομένων και single-fetch για περιοδικές ενημερώσεις.
- **Διαγραφή ασυνεπών καταστάσεων αισθητήρα μετά από κάθε ενημέρωση** για σωστή απεικόνιση ιστορικού.
- **Ανίχνευση κενών δεδομένων (>7 ημερών)** με αυτόματη τμηματική ανάκτηση δεδομένων.
- **Βελτιώσεις Options Flow**:
  - Ανανέωση κλειδιού πρόσβασης “on-the-fly” με μόνιμη ειδοποίηση για επιτυχής ανανέωση και έλεγχο εγκυρότητας κλειδιού πρόσβασης.
  - Αλλαγή αρχικής ημερομηνίας `initial_time` τρέχει ξανά αρχική ενημέρωση.
  - Έλεγχοι και σφάλματα για συχνότητα ενημέρωσης και ημερομηνία.
- Εισαγωγή στατιστικών στο recorder και διόρθωση αθροίσματος "μελλοντικών" εγγραφών για συνέπεια στα στατιστικά.
- Υποστήριξη πολλαπλών παροχών (multi-supply).
- Διεθνής μετάφραση EN/EL με πλήρη strings και placeholders.
- Config Flow & Options Flow με validation των credentials και μόνιμες ειδοποιήσεις για επιτυχίες/σφάλματα κλειδιού πρόσβασης.
- Πλήρης τεκμηρίωση εγκατάστασης, ρυθμίσεων και χρήσης στο README.


## v1.1.0 - New features - add production/injection electric energy sensors (2025-07-07)

- Basic data retrieval from the HEDNO API by **creating three sensors connected to a virtual device/meter**.
- New production/injection sensors available, **only when photovoltaics are installed**.
- Display persistent notification when **no new energy production data is detected for >7 days**.
- Restructuring of all production code with clear separation into individual subfolders depending on the function of the files.
- Creating additional methods to eliminate complexity warnings in flake8 control and simplify code maintenance.
- Added new code file to display in Home Assistant **System Health**.
- **100%** production code coverage with testing.
- Updated README.md file after adding the integration to the HACS store directory.

## v1.1.0 - Νέα χαρακτηριστικά - Προσθήκη αισθητήρων παραγωγής/έγχυσης ηλεκτρικής ενέργειας (07-07-2025)

- Βασική ανάκτηση δεδομένων από το API της ΔΕΔΔΗΕ με δημιουργία τριών αισθητήρων συνδεδεμένους σε εικονική συσκευή/μετρητή.
- Νέοι αισθητήρες παραγωγής/έγχυσης διαθέσιμοι, μόνο όταν υπάρχουν εγκατεστημένα φωτοβολταϊκά.
- Εμφάνιση μόνιμης ειδοποίησης όταν **δεν ανιχνεύονται νέα δεδομένα παραγωγής ενέργειας για μέρες >7**.
- Ανασυγκρότηση όλου του παραγωγικού κώδικα με σαφή διαχωρισμό σε επιμέρους υποφακέλους ανάλογα τη λειτουργία των αρχείων.
- Δημιουργία επιπρόσθετων μεθόδων για εξάλειψη ειδοποιήσεων πολυπλοκότητας στον έλεγχο flake8 και απλοποίηση συντήρησης κώδικα.
- Προσθήκη νέου αρχείου κώδικα για εμφάνιση στην **Υγεία Συστήματος** του Home Assistant.
- Κάλυψη παραγωγικού κώδικα με δοκιμές στο **100%**.
- Ανανέωση αρχείου README.md μετά την προσθήκη της ενσωμάτωσης στον κατάλογο του HACS store.
