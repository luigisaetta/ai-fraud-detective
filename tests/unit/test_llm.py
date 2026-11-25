"""
Author: L. Saetta
Date Last Modified: 2026-11-25
License: MIT
Description: Unit tests of the model client factories: the endpoint, the key
    and the project header for each provider, without network calls.
"""

from dataclasses import replace

from fraud_detective.config import ModelProvider
from fraud_detective.llm import (
    OCI_OPENAI_BASE_URL,
    DecisionsClientFactory,
    ModelClientFactory,
)
from tests.lab3.fakes import settings as base_settings


def _settings(**changes):
    """Settings with both keys set, so every client can be built."""
    return replace(
        base_settings(),
        oci_genai_api_key="oci-key",
        openai_api_key="openai-key",
        oci_region="eu-frankfurt-1",
        **changes,
    )


def test_model_client_on_oci_sends_the_project() -> None:
    """The Responses API on OCI needs the project of the conversations."""
    client = ModelClientFactory(_settings(model_provider=ModelProvider.OCI)).create()
    assert str(client.base_url).rstrip("/") == OCI_OPENAI_BASE_URL.format(
        region="eu-frankfurt-1"
    )
    assert client.project == _settings().oci_project_id


def test_decisions_client_on_oci_sends_no_project() -> None:
    """The Decisions API refuses the project header."""
    settings = _settings(decisions_provider=ModelProvider.OCI)
    client = DecisionsClientFactory(settings).create()
    assert str(client.base_url).rstrip("/") == OCI_OPENAI_BASE_URL.format(
        region="eu-frankfurt-1"
    )
    assert client.project is None
    assert client.api_key == "oci-key"


def test_decisions_client_on_openai_uses_the_openai_key() -> None:
    """With the default provider the client uses OpenAI and its key."""
    settings = _settings(model_provider=ModelProvider.OCI)
    client = DecisionsClientFactory(settings).create()
    assert "api.openai.com" in str(client.base_url)
    assert client.api_key == "openai-key"
