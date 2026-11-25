"""
Tests for the native-speaker evaluation set and its scorer (#14)

The chrF++ expectations were computed with sacrebleu 2.4.3 (CHRF(word_order=2)), which the
scorer matches without depending on it.
"""

import json

import httpx
import pytest
import respx

import config
from scripts import eval_translation as ev
from services.pii import redact

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"

# --- chrF++ matches sacrebleu ------------------------------------------------------


@pytest.mark.parametrize(
    "hypotheses, references, expected",
    [
        (["Ẹ káàbọ̀ sí ilé wa."], ["Ẹ káàbọ̀ sí ilé wa."], 100.0),
        (
            ["Take one tablet twice a day."],
            ["Take a tablet two times daily, after food."],
            27.0329,
        ),
        (
            ["Mo fẹ́ ra búrẹ́dì àti ẹyin.", "(Hello) world!", "a"],
            ["Mo fẹ́ ra búrẹ́dì, ẹyin.", "Hello, world", "b c"],
            63.5523,
        ),
        (
            ["Ka sha magani sau biyu a rana bayan abinci."],
            ["A sha kwaya ɗaya sau biyu a rana bayan cin abinci."],
            58.9459,
        ),
        ([""], ["something"], 0.0),
        (
            ["Abeg, how far with di delivery?", "Una well done o!"],
            ["Abeg, how far with the delivery?", "Well done o!"],
            77.2484,
        ),
    ],
)
def test_chrf_matches_sacrebleu(hypotheses, references, expected):
    assert ev.corpus_chrf(hypotheses, references) == pytest.approx(expected, abs=1e-4)


# --- the data ---------------------------------------------------------------------

SOURCES = ev.load_sources()
LANGUAGES = ev.load_languages()


def test_sources_cover_every_domain_evenly():
    domains = {}
    for row in SOURCES.values():
        domains[row["domain"]] = domains.get(row["domain"], 0) + 1
    assert len(SOURCES) >= 80
    assert len(domains) >= 10
    assert set(domains.values()) == {8}


def test_sources_contain_no_personal_data():
    for row in SOURCES.values():
        assert redact(row["text"]) == row["text"], row["id"]
        assert len(row["text"]) <= config.MAX_CONTENT_LENGTH


def test_languages_match_what_the_api_supports():
    nigerian_beyond_the_big_three = {"pcm", "ff", "tiv", "efi", "knc", "ibb"}
    assert {"yo", "ha", "ig"} | nigerian_beyond_the_big_three <= set(LANGUAGES)
    for code, info in LANGUAGES.items():
        supported = code in config.SUPPORTED_LANGUAGES
        assert info["status"] == ("supported" if supported else "collecting"), code


@pytest.mark.parametrize("code", sorted(LANGUAGES))
def test_committed_references_are_valid_and_free_of_personal_data(code):
    for row in ev.load_references(code, SOURCES):
        assert redact(row["text"]) == row["text"], f"{code}/{row['id']}"
        if row["reviewed"]:
            assert row.get("reviewed_by"), f"{code}/{row['id']} needs reviewed_by"
            assert row.get("reviewed_by") != row.get("translator"), "no self-review"


def test_references_must_match_a_source(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "sources.jsonl").write_text(
        json.dumps({"id": "a-01", "domain": "a", "text": "Hello"}) + "\n", encoding="utf-8"
    )
    (tmp_path / "references" / "yo.jsonl").write_text(
        json.dumps({"id": "zz-99", "text": "Bawo", "reviewed": True}) + "\n", encoding="utf-8"
    )
    sources = ev.load_sources(tmp_path)

    with pytest.raises(ValueError, match="unknown source id"):
        ev.load_references("yo", sources, tmp_path)


# --- a run through the real app ----------------------------------------------------


@pytest.fixture
def dataset(tmp_path):
    """Two sources, Yoruba references (one unreviewed) and a 'collecting' language"""
    (tmp_path / "references").mkdir()
    sources = [
        {"id": "greetings-01", "domain": "greetings", "text": "Good morning."},
        {"id": "health-01", "domain": "health", "text": "Drink clean water."},
    ]
    (tmp_path / "sources.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in sources), encoding="utf-8"
    )
    (tmp_path / "languages.json").write_text(
        json.dumps(
            [
                {"code": "yo", "name": "Yoruba", "status": "supported"},
                {"code": "ha", "name": "Hausa", "status": "supported"},
                {"code": "tiv", "name": "Tiv", "status": "collecting"},
            ]
        ),
        encoding="utf-8",
    )
    references = [
        {"id": "greetings-01", "text": "Ẹ káàárọ̀.", "reviewed": True, "reviewed_by": "b"},
        {"id": "health-01", "text": "Ẹ mu omi tó mọ́.", "reviewed": False},
    ]
    (tmp_path / "references" / "yo.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in references),
        encoding="utf-8",
    )
    return tmp_path


def azure_echo(table):
    """Azure mock that translates through a lookup table"""

    def respond(request):
        texts = [item["text"] for item in json.loads(request.content)]
        return httpx.Response(
            200, json=[{"translations": [{"text": table.get(t, t)}]} for t in texts]
        )

    return respond


@respx.mock
def test_scores_both_directions_and_skips_what_it_cant_score(client, dataset):
    respx.post(TRANSLATE_URL).mock(
        side_effect=azure_echo({"Good morning.": "Ẹ káàárọ̀.", "Ẹ káàárọ̀.": "Good morning."})
    )

    report = ev.evaluate(client, ["yo", "ha", "tiv", "xx"], data=dataset)

    yoruba = report["languages"]["yo"]
    assert yoruba["references"] == 1  # the unreviewed one is left out
    assert yoruba["en-x"]["chrf++"] == 100.0
    assert yoruba["x-en"]["chrf++"] == 100.0
    assert yoruba["en-x"]["by_domain"] == {"greetings": 100.0}
    assert report["skipped"] == {
        "ha": "no reviewed references yet",
        "tiv": "collecting references; not supported by the API yet",
        "xx": "not in languages.json",
    }


@respx.mock
def test_unreviewed_references_can_be_included(client, dataset):
    respx.post(TRANSLATE_URL).mock(side_effect=azure_echo({}))

    report = ev.evaluate(client, ["yo"], ["en-x"], include_unreviewed=True, data=dataset)

    assert report["languages"]["yo"]["references"] == 2
    assert "x-en" not in report["languages"]["yo"]


@respx.mock
def test_a_failed_batch_is_counted_not_scored(client, dataset):
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(500))

    report = ev.evaluate(client, ["yo"], ["en-x"], data=dataset)

    result = report["languages"]["yo"]["en-x"]
    assert result["failed_batches"] == 1
    assert result["scored"] == 0
    assert result["chrf++"] is None


def test_main_needs_a_base_url(monkeypatch):
    monkeypatch.delenv("EVAL_API_URL", raising=False)
    with pytest.raises(SystemExit):
        ev.main([])
