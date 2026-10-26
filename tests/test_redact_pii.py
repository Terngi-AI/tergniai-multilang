"""
Tests for scripts/redact_pii.py — the redaction gate for anything published under data/
"""

import io

import pytest

from scripts.redact_pii import main, redact, redact_names

# --- e-mails and URLs ---------------------------------------------------------


def test_redacts_e_mails():
    text = "Contact amina.yusuf+work@gmail.com or chidi_okeke@yahoo.co.uk soon"
    assert redact(text) == "Contact [EMAIL] or [EMAIL] soon"


def test_redacts_urls():
    text = "See https://terngi.example/ng/chat and www.mafand.example/tz for details"
    assert redact(text) == "See [URL] and [URL] for details"


def test_url_is_masked_before_its_digits():
    assert redact("See https://example.com/123-456-789 ok") == "See [URL] ok"


# --- phone numbers (African formats) -------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "+234 803 123 4567",  # Nigeria mobile, spaced
        "+2348031234567",  # Nigeria mobile, no separators
        "+234-803-123-4567",  # Nigeria mobile, dashed
        "+233 24 123 4567",  # Ghana mobile
        "+254 712 345 678",  # Kenya mobile
        "+27 82 123 4567",  # South Africa mobile
        "+211 91 123 4567",  # Sudan mobile
        "+221 77 123 4567",  # Senegal mobile
        "0803 123 4567",  # Nigeria local, no country code
        "024 123 4567",  # Lagos landline
        "(0803) 123-4567",  # parenthesised prefix
    ],
)
def test_redacts_african_phone_formats(raw):
    assert redact(f"Call {raw} today") == "Call [PHONE] today"


def test_does_not_mask_dates_or_small_numbers():
    text = "On 2026-10-25 we sent 12,500 messages in 3 languages"
    assert redact(text) == text


def test_redacts_long_digit_strings():
    text = "His BVN is 22140012345 and the reference is 98765432101"
    assert redact(text) == "His BVN is [ID] and the reference is [ID]"


# --- known names ----------------------------------------------------------------


def test_redacts_known_names_case_insensitively():
    text = "Thank you Amina Yusuf Ibrahim. See you, AMINA!"
    names = ["Amina", "Amina Yusuf Ibrahim"]
    assert redact(text, names) == "Thank you [NAME]. See you, [NAME]!"


def test_full_name_masks_before_first_name():
    # "Chidi Okeke" is masked as a whole, and the single name "Chidi" masks the other
    # occurrence, not just the first word of "Chidi Okeke"
    assert (
        redact_names("Hello Chidi Okeke and Chidi Ekemini", ["Chidi Okeke", "Chidi"])
        == "Hello [NAME] and [NAME] Ekemini"
    )


def test_name_needs_a_word_boundary():
    assert redact_names("I know Aminata too", ["Amina"]) == "I know Aminata too"


# --- misc -------------------------------------------------------------------------


def test_redaction_is_stable():
    once = redact("Call +234 803 123 4567 at amina@example.com", ["Amina"])
    assert redact(once) == once


# --- CLI --------------------------------------------------------------------------


def test_cli_redacts_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("Email chidi@example.com please"))
    assert main([]) == 0
    assert capsys.readouterr().out == "Email [EMAIL] please"


def test_cli_redacts_a_file(tmp_path, capsys):
    path = tmp_path / "transcript.txt"
    path.write_text("Call 0803 123 4567\n", encoding="utf-8")
    assert main([str(path)]) == 0
    assert capsys.readouterr().out == "Call [PHONE]\n"


def test_cli_reads_the_names_file(tmp_path, monkeypatch, capsys):
    names = tmp_path / "names.txt"
    names.write_text("Chidi Okeke\n\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("Hello Chidi Okeke!"))
    assert main(["--names", str(names), "-"]) == 0
    assert capsys.readouterr().out == "Hello [NAME]!"
