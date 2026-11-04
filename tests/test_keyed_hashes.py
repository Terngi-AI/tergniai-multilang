"""
Tests for keyed (HMAC-SHA256) hashes of personal identifiers (issue #84)

Phone numbers and IPv4 addresses are small spaces, so a plain unsalted SHA-256 hash of
them can be reversed by brute force. The stored keys must therefore depend on
HASH_SECRET, and the app must refuse to start without it.
"""

import hashlib

import pytest

import config
import main
from services import conversations, identifiers, whatsapp


def test_phone_key_is_hmac_under_hash_secret(monkeypatch):
    monkeypatch.setattr(config, "HASH_SECRET", "test-hash-secret")

    phone = "+14155552671"
    assert whatsapp._key(phone) == identifiers.keyed_hash(phone)
    assert whatsapp._key(phone) != hashlib.sha256(phone.encode()).hexdigest()


def test_ip_owner_key_is_hmac_under_hash_secret(monkeypatch):
    monkeypatch.setattr(config, "HASH_SECRET", "test-hash-secret")

    owner = "ip:203.0.113.7"
    assert conversations._owner_hash(owner) == identifiers.keyed_hash(owner)
    assert conversations._owner_hash(owner) != hashlib.sha256(owner.encode()).hexdigest()


def test_keys_depend_on_the_secret(monkeypatch):
    phone = "+14155552671"
    owner = "ip:203.0.113.7"

    monkeypatch.setattr(config, "HASH_SECRET", "secret-one")
    key_one_phone = whatsapp._key(phone)
    key_one_owner = conversations._owner_hash(owner)

    monkeypatch.setattr(config, "HASH_SECRET", "secret-two")
    assert whatsapp._key(phone) != key_one_phone
    assert conversations._owner_hash(owner) != key_one_owner


def test_startup_refuses_without_hash_secret(monkeypatch):
    monkeypatch.setattr(config, "HASH_SECRET", "")

    with pytest.raises(SystemExit) as exc:
        main.check_hash_secret()

    assert "HASH_SECRET is empty" in str(exc.value)


def test_startup_accepts_a_configured_hash_secret(monkeypatch):
    monkeypatch.setattr(config, "HASH_SECRET", "test-hash-secret")

    main.check_hash_secret()  # must not raise
