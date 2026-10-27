"""FR-43: an optional "suggest wording" button. Claude proposes a clearer version of the
analyst's text; nothing changes until the analyst accepts the suggestion."""

from pydantic import BaseModel

from apps.core import llm

LANGUAGES = {"fr": "French", "en": "English"}

SYSTEM = """You help an analyst word the findings of a land due-diligence report for buyers \
in Cameroon. Rewrite the text you are given so it is clearer and plainer for a non-specialist. \
Keep its language. Keep every number, unit, place name, rating meaning, recommendation and \
caveat; add no fact, number or advice that is not in the text; do not make it longer than \
needed. Return only the rewritten text."""


class Suggestion(BaseModel):
    text: str


def suggest(text, language):
    language_name = LANGUAGES.get(language, "French")
    prompt = f"Language: {language_name}\n\n<finding>\n{text}\n</finding>"
    return llm.parse(system=SYSTEM, prompt=prompt, schema=Suggestion, effort="low").text.strip()
