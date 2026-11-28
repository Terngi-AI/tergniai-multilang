"""
Tests for the output checks on LLM translations (#144): changed numbers, lost links and
added commentary move to the next model; when nothing passes, the best is returned unverified
"""

import json

import httpx
import pytest
import respx

import config
import metrics
from services import quality
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"


# --- the checks ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, translation, problem",
    [
        ("Take 2 tablets twice a day.", "Mu ìwọ̀n 3 lẹ́ẹ̀mejì lójúmọ́.", True),  # 2 became 3
        ("You have 5,000 naira.", "O ní naira 500.", True),  # amount changed
        ("You have 5,000 naira.", "O ní naira 5000.", False),  # separators don't matter
        ("You have 5,000 naira.", "O ní naira 5 000.", False),
        ("Rest for five days.", "Sinmi fún ọjọ́ márùn-ún.", False),  # no digits in the source
        ("The bus leaves at 6.", "Bọ́ọ̀sì náà ń lọ ní aago mẹ́fà.", False),  # written as a word
        ("Room 4, from 9 to 5.", "Yàrá 4, láti 9.", True),  # digits kept but one dropped
        ("Pay 300 by 15 March.", "Sanwo ٣٠٠ ní 15 March.", False),  # Arabic-Indic digits
        ("Call 112 now.", "Pe 112 bayi, tabi 911.", True),  # a number was added
    ],
)
def test_number_check(source, translation, problem):
    assert quality.number_problem(source, translation) is problem


def test_links_and_emails_must_survive():
    source = "Apply at https://example.org/apply or write to help@example.org."
    assert not quality.link_problem(
        source, "Wa lori https://example.org/apply tabi help@example.org"
    )
    assert quality.link_problem(source, "Wa lori example.org tabi help@example.org")


@pytest.mark.parametrize(
    "translation",
    [
        "Here is the translation: Ẹ káàárọ̀",
        "Translation: Ẹ káàárọ̀",
        "Sure, here it is: Ẹ káàárọ̀",
        "Ẹ káàárọ̀\n(Note: this is the formal greeting)",
    ],
)
def test_commentary_is_caught(translation):
    assert quality.commentary_problem("Good morning to you all.", translation)


def test_commentary_in_the_source_itself_is_fine():
    source = "Translation: please read the note.\nNote: bring your card."
    assert not quality.commentary_problem(source, "Ìtumọ̀: ẹ ka àkíyèsí.\nNote: ẹ mú káàdì yín.")


def test_length_check_allows_dense_scripts():
    source = "Please bring your vaccination card when you come to the clinic with your child."
    assert quality.length_problem(source, "OK", "yo")
    assert not quality.length_problem(source, "带孩子来诊所时请带上疫苗接种卡。", "zh-Hans")
    assert quality.length_problem(source, source * 6, "yo")
    assert not quality.length_problem(
        "Hi", "Ẹ n lẹ́ o, ẹ káàbọ̀ sí ilé wa", "yo"
    )  # too short to judge


def test_checks_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_CHECKS", False)
    assert quality.problems("Take 2 tablets.", "Mu 3.", "yo") == []


# --- through the API -----------------------------------------------------------------------


@pytest.fixture
def two_models(monkeypatch):
    """LLM translation with one provider and two models, so a rejected answer moves on"""
    provider = config.LLM_PROVIDERS["groq"]
    monkeypatch.setattr(
        config,
        "LLM_PROVIDERS",
        {
            "groq": config.LLMProvider(
                name="groq",
                kind="openai",
                base_url=GROQ_URL,
                api_keys=provider.api_keys,
                models=("model-a", "model-b"),
            )
        },
    )
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["groq"])


def translations(*texts) -> httpx.Response:
    content = json.dumps({"translations": list(texts)}, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def translate(client, content="Take 2 tablets twice a day."):
    return client.post(
        "/v1/translate", json={"content": content, "from_language": "en", "to_language": "yo"}
    )


def models_called(route):
    return [json.loads(call.request.content)["model"] for call in route.calls]


@respx.mock
def test_a_changed_number_moves_to_the_next_model(client, two_models):
    before = metrics.TRANSLATION_CHECK_FAILURES.labels("number")._value.get()
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            translations("Mu ìwọ̀n 3 lẹ́ẹ̀mejì lójúmọ́."),
            translations("Mu ìwọ̀n 2 lẹ́ẹ̀mejì lójúmọ́."),
        ]
    )

    response = translate(client)

    assert response.json()["translated_text"] == "Mu ìwọ̀n 2 lẹ́ẹ̀mejì lójúmọ́."
    assert response.json()["verified"] is True
    assert models_called(route) == ["model-a", "model-b"]
    assert metrics.TRANSLATION_CHECK_FAILURES.labels("number")._value.get() == before + 1


@respx.mock
def test_a_preamble_moves_to_the_next_model(client, two_models):
    respx.post(CHAT_URL).mock(
        side_effect=[
            translations("Here is the translation: Ẹ káàárọ̀ gbogbo yín."),
            translations("Ẹ káàárọ̀ gbogbo yín."),
        ]
    )

    response = translate(client, "Good morning to you all.")

    assert response.json()["translated_text"] == "Ẹ káàárọ̀ gbogbo yín."


@respx.mock
def test_when_nothing_passes_the_best_is_returned_unverified_and_not_cached(client, two_models):
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            # two problems: a changed number and a preamble
            translations("Translation: Mu ìwọ̀n 3 lẹ́ẹ̀mejì."),
            # one problem: a changed number
            translations("Mu ìwọ̀n 3 lẹ́ẹ̀mejì lójúmọ́."),
            translations("Mu ìwọ̀n 2 lẹ́ẹ̀mejì lójúmọ́."),
        ]
    )

    first = translate(client)

    assert first.status_code == 200
    assert first.json()["translated_text"] == "Mu ìwọ̀n 3 lẹ́ẹ̀mejì lójúmọ́."
    assert first.json()["verified"] is False
    # Not cached: the next request asks the provider again, and this time gets a clean answer
    second = translate(client)
    assert second.json()["translated_text"] == "Mu ìwọ̀n 2 lẹ́ẹ̀mejì lójúmọ́."
    assert second.json()["verified"] is True
    assert route.call_count == 3


@respx.mock
def test_batch_reports_unverified_too(client, two_models):
    respx.post(CHAT_URL).mock(
        side_effect=[translations("Mu 3.", "Ẹ káàárọ̀"), translations("Mu 3.", "Ẹ káàárọ̀")]
    )

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["Take 2.", "Good morning"], "from_language": "en", "to_language": "yo"},
    )

    assert response.json()["verified"] is False
    assert response.json()["translations"] == ["Mu 3.", "Ẹ káàárọ̀"]


@respx.mock
def test_masked_values_are_restored_in_an_unverified_result(client, two_models, monkeypatch):
    monkeypatch.setattr(config, "PII_MASKING", True)
    respx.post(CHAT_URL).mock(
        side_effect=[
            translations("Pe [[P1]]. Mu 3."),  # 2 tablets became 3
            translations("Pe [[P1]]. Mu 3."),
        ]
    )

    response = translate(client, "Call +234 803 123 4567. Take 2 tablets.")

    assert response.json()["verified"] is False
    assert "+234 803 123 4567" in response.json()["translated_text"]


@respx.mock
def test_clean_translations_are_verified(client, two_models):
    respx.post(CHAT_URL).mock(return_value=translations("Mu ìwọ̀n 2 lẹ́ẹ̀mejì lójúmọ́."))
    assert translate(client).json()["verified"] is True
