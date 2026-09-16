import pytest

from llmlc.client import Completion


class FakeClient:
    """Scripted OpenAI-compatible client. Grading must be testable with no network."""

    def __init__(self, responses: list[str | None] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    def complete(self, model, prompt, **kw) -> Completion:
        self.calls.append((model, prompt))
        if not self.responses:
            return Completion(None, "no scripted response")
        nxt = self.responses.pop(0)
        return Completion(nxt, None if nxt is not None else "error", model=model)


class FakeBackTranslator:
    def __init__(self, mapping: dict[str, str] | None = None, default: str | None = None) -> None:
        self.mapping = mapping or {}
        self.default = default
        self.id = "fake:bt"

    def translate(self, text):
        from llmlc.bt import BackTranslation
        out = self.mapping.get(text.strip(), self.default)
        return BackTranslation(out, None if out else "no translation", "fake")


@pytest.fixture
def fake_client():
    return FakeClient


@pytest.fixture
def fake_bt():
    return FakeBackTranslator
