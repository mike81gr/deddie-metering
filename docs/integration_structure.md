# 📁 Integration Structure

```
deddie_metering/
├── README.md
├── hacs.json
├── CHANGELOG.md
├── requirements-dev.txt
├── requirements-test.txt
├── .gitignore
├── .pre-commit-config.yaml
├── setup.cfg
├── LICENSE
├── docs/
│   └── integration_structure.md
│
├── custom_components/
│   └── deddie_metering/
│       ├── __init__.py
│       ├── manifest.json
│       ├── const.py
│       ├── config_flow.py
│       ├── options_flow.py
│       ├── coordinator.py
│       ├── sensor.py
│       ├── strings.json
│       ├── system_health.py
│       ├── api/
│       │	├── client.py
│       │	└── detection.py
│       │
│       ├── helpers/
│       │	├── statistics.py
│       │	├── storage.py
│       │	├── translate.py
│       │   └── utils.py
│       │
│       └── translations/
│           ├── el.json
│           └── en.json
│
├── tests/
│   ├── conftest.py
│   ├── test_client.py
│   ├── test_config_flow.py
│   ├── test_coordinator.py
│   ├── test_detection.py
│   ├── test_init.py
│   ├── test_options_flow.py
│   ├── test_sensor.py
│   ├── test_statistics.py
│   ├── test_storage.py
│   ├── test_system_health.py
│   ├── test_translate.py
│   └── test_utils.py
│
├── images/
│   ├── configuration_el.png
│   ├── configuration_en.png
│   ├── dashboard-daily.png
│   ├── dashboard-monthly.png
│   ├── dashboard-new-sensors.png
│   ├── entity-details.png
│   ├── statistics-history.png
│   ├── system-health.png
│   └── UI-history-stats.png
│
└── .github/
    └── workflows/
        ├── release.yml
        ├── ci.yml
        ├── lint.yml
        └── validate.yml
```
