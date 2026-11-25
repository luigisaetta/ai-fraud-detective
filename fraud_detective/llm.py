"""
Author: L. Saetta
Date Last Modified: 2026-11-25
License: MIT
Description: Builds the OpenAI client for the configured model provider. The
    application always uses the official openai library and the Responses API;
    only the endpoint, the API key and the project change:

    - oci: the OpenAI-compatible endpoint of OCI Generative AI, an OCI
      Generative AI API key and the project OCID.
    - openai: the default OpenAI endpoint and an OpenAI API key.

    The Decisions API (Lab 4) has its own provider and model in the settings,
    and refuses the project header, so it gets a client of its own.

Usage:

    client = ModelClientFactory(settings).create()
    response = client.responses.create(model=settings.model_id, input="Hello")

    client = DecisionsClientFactory(settings).create()
    decision = client.decisions.create(model=settings.decisions_model_id, ...)
"""

from openai import OpenAI

from fraud_detective.config import ModelProvider, Settings

#: The OpenAI-compatible endpoint of OCI Generative AI, per region.
OCI_OPENAI_BASE_URL = (
    "https://inference.generativeai.{region}.oci.oraclecloud.com/openai/v1"
)


class ModelClientFactory:
    """Creates an OpenAI client pointed at the configured provider.

    Args:
        settings: The application settings.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> OpenAI:
        """Create the client.

        Returns:
            An ``openai.OpenAI`` client ready for ``client.responses.create``.
        """
        settings = self._settings
        if settings.model_provider is ModelProvider.OCI:
            return OpenAI(
                base_url=OCI_OPENAI_BASE_URL.format(region=settings.oci_region),
                api_key=settings.oci_genai_api_key,
                project=settings.oci_project_id,
            )
        return OpenAI(api_key=settings.openai_api_key)


class DecisionsClientFactory:
    """Creates an OpenAI client for the Decisions API (Lab 4).

    It follows ``[decisions] provider`` instead of ``[model] provider``. On
    OCI it sends no project: the Decisions API refuses the project and
    conversation-store headers.

    Args:
        settings: The application settings.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> OpenAI:
        """Create the client.

        Returns:
            An ``openai.OpenAI`` client ready for ``client.decisions.create``.
        """
        settings = self._settings
        if settings.decisions_provider is ModelProvider.OCI:
            return OpenAI(
                base_url=OCI_OPENAI_BASE_URL.format(region=settings.oci_region),
                api_key=settings.oci_genai_api_key,
            )
        return OpenAI(api_key=settings.openai_api_key)
