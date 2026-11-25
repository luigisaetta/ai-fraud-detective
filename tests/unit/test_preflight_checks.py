"""
Author: L. Saetta
Date Last Modified: 2026-11-25
License: MIT
Description: Unit tests of the project and model checks of the preflight:
    server-side conversation settings of the project, and a model call that
    continues on the server with previous_response_id; the hints for calls
    refused by the service, for example for missing IAM policies. No OCI or
    model call is made.
"""

# pylint: disable=missing-function-docstring

import dataclasses
from pathlib import Path
from types import SimpleNamespace

from oci.exceptions import ServiceError

from fraud_detective.config import ModelProvider, Settings
from fraud_detective.preflight import checks
from fraud_detective.preflight.base import PreflightContext, Status


def _project(conversation=True, memory=True):
    """A project as returned by get_generative_ai_project."""
    networking = SimpleNamespace(
        network_mode="MANAGED", network_policy=SimpleNamespace(mode="DENY_ALL")
    )
    return SimpleNamespace(
        display_name="proj-test",
        lifecycle_state="ACTIVE",
        conversation_config=(
            SimpleNamespace(conversations_retention_in_hours=720)
            if conversation
            else None
        ),
        short_term_memory_optimization_config=SimpleNamespace(
            is_enabled=memory,
            condenser_config=SimpleNamespace(
                llm_selection=SimpleNamespace(model_id="openai.gpt-oss-120b")
            ),
        ),
        sandbox_config=SimpleNamespace(
            is_enabled=True, sandbox_outbound_networking_config=networking
        ),
    )


def _context(monkeypatch, project=None):
    """A context whose OCI clients return ``project``."""
    monkeypatch.delenv("OCI_GENAI_API_KEY", raising=False)
    settings = Settings.load(
        settings_file=Path("/nonexistent/settings.toml"),
        env_file=Path("/nonexistent/.env"),
    )
    context = PreflightContext(settings=settings)
    generative_ai = SimpleNamespace(
        get_generative_ai_project=lambda project_id: SimpleNamespace(data=project)
    )
    context.__dict__["clients"] = SimpleNamespace(generative_ai=generative_ai)
    return context


class FakeResponses:
    """Scripted ``client.responses``; records the arguments of each call."""

    def __init__(self, second_call_error=None):
        self.calls = []
        self._second_call_error = second_call_error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            call = SimpleNamespace(
                type="function_call", name="get_utc_time", call_id="call_1"
            )
            return SimpleNamespace(id="resp_1", output=[call])
        if self._second_call_error:
            raise self._second_call_error
        return SimpleNamespace(id="resp_2", output=[SimpleNamespace(type="message")])


def _fake_model(monkeypatch, responses):
    client = SimpleNamespace(responses=responses)
    factory = SimpleNamespace(create=lambda: client)
    monkeypatch.setattr(checks, "ModelClientFactory", lambda settings: factory)


def test_project_with_conversation_and_memory_passes(monkeypatch):
    result = checks.ProjectCheck().run(_context(monkeypatch, _project()))
    assert result.status is Status.PASS
    assert "conversations 720 h" in result.detail
    assert "openai.gpt-oss-120b" in result.detail


def test_project_without_conversation_fails_without_blocking(monkeypatch):
    result = checks.ProjectCheck().run(
        _context(monkeypatch, _project(conversation=False))
    )
    assert result.status is Status.FAIL and not result.blocking
    assert "conversations are not configured" in result.detail


def test_project_without_short_term_memory_fails(monkeypatch):
    result = checks.ProjectCheck().run(_context(monkeypatch, _project(memory=False)))
    assert result.status is Status.FAIL
    assert "short-term memory" in result.detail


def test_model_check_continues_the_conversation_on_the_server(monkeypatch):
    responses = FakeResponses()
    _fake_model(monkeypatch, responses)
    result = checks.ModelCheck().run(_context(monkeypatch))
    assert result.status is Status.PASS
    assert len(responses.calls) == 2
    first, second = responses.calls[0], responses.calls[1]
    assert first["store"] is True and "previous_response_id" not in first
    assert second["store"] is True
    assert second["previous_response_id"] == "resp_1"
    assert second["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": checks.TIME_TOOL_OUTPUT,
        }
    ]


def test_model_check_reports_a_failed_server_side_conversation(monkeypatch):
    _fake_model(monkeypatch, FakeResponses(second_call_error=RuntimeError("404")))
    result = checks.ModelCheck().run(_context(monkeypatch))
    assert result.status is Status.FAIL
    assert "server-side conversation failed" in result.detail


class FakeApiError(Exception):
    """A refused model call, with the HTTP status as in the openai package."""

    def __init__(self, status_code):
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code


class FailingResponses:
    """``client.responses`` whose first call is refused."""

    def __init__(self, error):
        self._error = error

    def create(self, **kwargs):
        raise self._error


def test_service_hints_point_to_the_policies_page():
    for status in (403, 404):
        hint = checks._hint(ServiceError(status, "NotAuthorized", {}, "refused"))
        assert checks.POLICIES_PAGE in hint
        assert "generative-ai-" not in hint


def test_model_check_refused_on_oci_points_to_the_policies(monkeypatch):
    _fake_model(monkeypatch, FailingResponses(FakeApiError(404)))
    result = checks.ModelCheck().run(_context(monkeypatch))
    assert result.status is Status.FAIL
    assert "model.model_id" in result.hint
    assert checks.POLICIES_PAGE in result.hint


def test_model_check_refused_on_openai_does_not_mention_oci_policies(monkeypatch):
    _fake_model(monkeypatch, FailingResponses(FakeApiError(403)))
    context = _context(monkeypatch)
    context.settings = dataclasses.replace(
        context.settings, model_provider=ModelProvider.OPENAI
    )
    result = checks.ModelCheck().run(context)
    assert result.status is Status.FAIL
    assert checks.POLICIES_PAGE not in result.hint


def test_model_check_with_a_refused_api_key(monkeypatch):
    _fake_model(monkeypatch, FailingResponses(FakeApiError(401)))
    result = checks.ModelCheck().run(_context(monkeypatch))
    assert result.status is Status.FAIL
    assert "API key in .env was refused" in result.hint


class RefusingSession:
    """A test sandbox where every call is refused by the service."""

    sandbox_id = "ocid1.sandbox.test"

    def _refuse(self, *args, **kwargs):
        raise ServiceError(404, "NotAuthorizedOrNotFound", {}, "refused")

    write_file = read_file = run = close = _refuse


def test_sandbox_check_refused_by_the_service_fails_with_a_hint(monkeypatch):
    context = _context(monkeypatch)
    context.session = RefusingSession()
    result = checks.FileTransferCheck().run(context)
    assert result.status is Status.FAIL
    assert result.detail == "HTTP 404: NotAuthorizedOrNotFound"
    assert checks.POLICIES_PAGE in result.hint


def test_cleanup_refused_by_the_service_names_the_leftover_sandbox(monkeypatch):
    context = _context(monkeypatch)
    context.session = RefusingSession()
    result = checks.CleanupCheck().run(context)
    assert result.status is Status.FAIL and not result.blocking
    assert "ocid1.sandbox.test was not deleted" in result.detail
    assert "fraud_detective.cleanup --delete" in result.hint
