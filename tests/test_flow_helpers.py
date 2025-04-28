from unittest.mock import MagicMock
from deddie_metering.config_flow import DeddieConfigFlow
from deddie_metering.options_flow import DeddieOptionsFlowHandler


def test_config_flow_build_token_link_en():
    flow = DeddieConfigFlow()
    # simulate English locale
    flow.hass = MagicMock()
    flow.hass.config = MagicMock()
    flow.hass.config.language = "en"
    link = flow._build_token_link()
    assert link == '<a href="https://apps.deddie.gr/mdp/intro.html">HEDNO</a>'


def test_config_flow_build_token_link_el():
    flow = DeddieConfigFlow()
    # simulate Greek locale
    flow.hass = MagicMock()
    flow.hass.config = MagicMock()
    flow.hass.config.language = "el"
    link = flow._build_token_link()
    assert link == '<a href="https://apps.deddie.gr/mdp/intro.html">ΔΕΔΔΗΕ</a>'


def test_config_flow_build_help_link():
    flow = DeddieConfigFlow()
    # language doesn't affect help link
    flow.hass = MagicMock()
    flow.hass.config = MagicMock()
    flow.hass.config.language = "en"
    help_link = flow._build_help_link()
    assert "insomnia.gr" in help_link
    assert help_link.startswith('<a href="https://www.insomnia.gr')


def test_options_flow_build_token_link_en():
    handler = DeddieOptionsFlowHandler(MagicMock())
    handler.hass = MagicMock()
    handler.hass.config = MagicMock()
    handler.hass.config.language = "en"
    link = handler._build_token_link()
    assert link == '<a href="https://apps.deddie.gr/mdp/intro.html">HEDNO</a>'


def test_options_flow_build_token_link_el():
    handler = DeddieOptionsFlowHandler(MagicMock())
    handler.hass = MagicMock()
    handler.hass.config = MagicMock()
    handler.hass.config.language = "el"
    link = handler._build_token_link()
    assert link == '<a href="https://apps.deddie.gr/mdp/intro.html">ΔΕΔΔΗΕ</a>'


def test_options_flow_build_help_link():
    handler = DeddieOptionsFlowHandler(MagicMock())
    # help link does not depend on language
    help_link = handler._build_help_link()
    assert "insomnia.gr" in help_link
    assert help_link.startswith('<a href="https://www.insomnia.gr')
