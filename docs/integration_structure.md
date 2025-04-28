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
│       ├── icon.png
│       ├── const.py
│       ├── config_flow.py
│       ├── options_flow.py
│       ├── coordinator.py
│       ├── sensor.py
│       ├── storage.py
│       ├── utils.py
│       ├── api.py
│       ├── statistics_helper.py
│       ├── strings.json
│       ├── helpers/
│       │   └── translate.py
│       └── translations/
│           ├── el.json
│           └── en.json
│
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_config_flow.py
│   ├── test_coordinator.py
│   ├── test_flow_helpers.py
│   ├── test_init.py
│   ├── test_options_flow.py
│   ├── test_sensor.py
│   ├── test_statistics_helper.py
│   ├── test_storage.py
│   ├── test_translate.py
│   └── test_utils.py
│
├── images/
│   ├── configuration_el.png
│   ├── configuration_en.png
│   ├── dashboard-daily.png
│   ├── dashboard-monthly.png
│   ├── entity-details.png
│   ├── statistics-history.png
│   └── logo.png
│   ├── icon.png
│
└── .github/
    └── workflows/
        ├── release.yml
        ├── ci.yml
        ├── lint.yml
        └── validate.yml
```
