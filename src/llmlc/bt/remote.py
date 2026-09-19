"""Back-translation via a remote model.

The back-translator is the one component that must *read* the target language.
Two rules from docs/01 apply and are enforced by the caller:

  independence   never the model under test, preferably not the same family --
                 otherwise we measure self-consistency, the flaw in the original
                 round-trip design
  qualification  validated per language against known-good text before trusted;
                 where it cannot read the language the result is `unverified`
                 rather than a bad score

S1 uses this remote path. The local MADLAD/NLLB back-translator arrives in S3.
"""
from __future__ import annotations

from dataclasses import dataclass

from llmlc.client import OpenAICompatClient

PROMPT = """Translate the following text into {pivot_name}.
Reply with the translation only — no commentary, no notes, no original text.

TEXT:
{text}"""

#: Named rather than passed as a tag: "Translate into de" is a worse prompt than
#: "Translate into German", and the fallback pivots must all be present here.
PIVOT_NAMES = {"en": "English", "ru": "Russian", "es": "Spanish", "de": "German",
               "fr": "French", "ar": "Arabic", "hi": "Hindi", "pt": "Portuguese",
               "it": "Italian", "zh": "Chinese", "ja": "Japanese"}


@dataclass
class BackTranslation:
    text: str | None
    error: str | None
    model: str

    @property
    def ok(self) -> bool:
        return self.text is not None and self.error is None


class RemoteBackTranslator:
    def __init__(self, client: OpenAICompatClient, model: str, pivot: str = "en") -> None:
        self.client = client
        self.model = model
        self.pivot = pivot

    @property
    def id(self) -> str:
        """Identity of the *instrument*, which includes what it translates into.

        The same model translating into German is not the same instrument as it
        translating into English, so the pivot rides in the id whenever it is not
        the default. That one detail does three jobs: qualification is cached per
        pivot rather than shared across them, two results for the same language
        measured through different pivots occupy separate rows under the existing
        uniqueness constraint instead of overwriting each other, and the pivot is
        visible wherever the back-translator is shown.

        English stays unsuffixed so every row measured before this existed keeps
        its identity, and no cache is invalidated.
        """
        return f"remote:{self.model}" if self.pivot == "en" else f"remote:{self.model}@{self.pivot}"

    def translate(self, text: str) -> BackTranslation:
        prompt = PROMPT.format(pivot_name=PIVOT_NAMES.get(self.pivot, self.pivot), text=text.strip())
        c = self.client.complete(self.model, prompt, max_tokens=500)
        return BackTranslation(c.text, c.error, self.model)
