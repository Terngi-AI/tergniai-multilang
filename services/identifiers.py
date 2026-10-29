"""
Keyed hashes for personal identifiers (WhatsApp phone numbers, IP-based owners)

A plain SHA-256 hash of a phone number or an IPv4 address is reversible by brute force:
those are small spaces (roughly 10^11 and 2^32 values), so an unsalted hash is
pseudonymous at best. We therefore always key the hashes with HMAC-SHA256 under
HASH_SECRET, so a leaked database does not reveal the underlying values.

Changing HASH_SECRET makes every previously stored key unrecoverable, i.e. WhatsApp
memory and conversations are forgotten. That is acceptable: both expire on their own.
"""

import hashlib
import hmac

import config


def keyed_hash(value: str) -> str:
    """HMAC-SHA256 of `value` under HASH_SECRET, hex-encoded"""
    return hmac.new(
        config.HASH_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()
