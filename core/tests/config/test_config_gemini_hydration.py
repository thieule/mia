"""providers.gemini.api_key is filled from standard Google env names when JSON omits it."""

from mia.config.schema import Config


def test_gemini_key_from_google_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_from_google")
    c = Config()
    assert c.providers.gemini.api_key == "AIza_from_google"


def test_gemini_key_priority_gemini_first(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "explicit")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_other")
    c = Config()
    assert c.providers.gemini.api_key == "explicit"


def test_explicit_json_key_not_overwritten(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from_env")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_other")
    c = Config(providers={"gemini": {"apiKey": "from_json"}})
    assert c.providers.gemini.api_key == "from_json"
