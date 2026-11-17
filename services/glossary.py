"""
Glossary helpers shared by the translation providers

A glossary maps a source term to either one target-language string (used for every target
language) or a mapping of target language codes to strings. Only entries that apply to the
requested target language participate in a request.

Providers use the glossary in different ways:

- Azure Translator gets its documented ``mstrans:dictionary`` markup.
- OpenAI-compatible models get the glossary in the system prompt.
- MORENA is small, so terms are replaced with placeholders before the call and restored
  afterwards.
"""

import html
import json
import re
from typing import Dict, List, Optional, Tuple, Union

Glossary = Dict[str, Union[str, Dict[str, str]]]
# A (source term, target term) pair that applies to the requested target language
Entry = Tuple[str, str]

# Private-use characters are very unlikely to occur in user text and are preserved by
# providers more often than words such as "TERM".
_PLACEHOLDER = "\ue000{}\ue001"


def entries_for(glossary: Optional[Glossary], target_language: str) -> List[Entry]:
    """Return the glossary entries that apply to one target language, longest term first"""
    if not glossary:
        return []

    entries: List[Entry] = []
    for source, translation in glossary.items():
        target: Optional[str]
        if isinstance(translation, str):
            target = translation
        else:
            target = translation.get(target_language)
        if source and target:
            entries.append((source, target))

    # Longest first so "mobile money" wins over "money" when both are in the glossary.
    return sorted(entries, key=lambda entry: (-len(entry[0]), entry[0]))


def _term_pattern(entries: List[Entry]) -> Optional[re.Pattern[str]]:
    if not entries:
        return None
    alternatives = "|".join(re.escape(source) for source, _ in entries)
    return re.compile(alternatives)


def protect(text: str, entries: List[Entry]) -> Tuple[str, Dict[str, str]]:
    """Replace glossary terms with placeholders, returning the text and a restore map"""
    pattern = _term_pattern(entries)
    if pattern is None:
        return text, {}

    targets = dict(entries)
    replacements: Dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = _PLACEHOLDER.format(len(replacements))
        replacements[marker] = targets[match.group(0)]
        return marker

    return pattern.sub(replace, text), replacements


def restore(text: str, replacements: Dict[str, str]) -> str:
    """Put the requested target terms back after a provider call"""
    for marker, target in replacements.items():
        text = text.replace(marker, target)
    return text


def azure_markup(text: str, entries: List[Entry]) -> str:
    """Wrap matching terms in Azure Translator's dynamic-dictionary markup"""
    pattern = _term_pattern(entries)
    if pattern is None:
        return text

    targets = dict(entries)

    def replace(match: re.Match[str]) -> str:
        source = match.group(0)
        target = html.escape(targets[source], quote=True)
        return (
            f'<mstrans:dictionary translation="{target}">'
            f"{html.escape(source, quote=False)}</mstrans:dictionary>"
        )

    return pattern.sub(replace, text)


def prompt_instruction(entries: List[Entry]) -> str:
    """Instruction block for an LLM prompt, or an empty string when there is no glossary"""
    if not entries:
        return ""
    terms = "\n".join(f"- {source} => {target}" for source, target in entries)
    return (
        "\n\nGlossary (use these translations exactly and keep the source terms unchanged "
        f"where the translation is the same):\n{terms}"
    )


def cache_signature(entries: List[Entry]) -> str:
    """Stable representation of the effective glossary for cache keys"""
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
