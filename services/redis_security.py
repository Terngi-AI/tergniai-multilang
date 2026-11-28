"""
How safely REDIS_URL reaches Redis (#167)

Redis holds conversations, WhatsApp memory, feedback and cached translations, so a plain-text
connection over the internet exposes all of it, and the password too. The URL is classified as:

- local:   a unix socket, localhost or a loopback address
- private: a container or private-network host: a name without dots (e.g. the bundled
           compose stack's `redis`), a name under .internal/.local/.lan/.svc, or a private,
           link-local or unique-local IP address
- remote:  anything else

A remote URL without TLS (`redis://` instead of `rediss://`) refuses to start unless
ALLOW_INSECURE_REDIS=true. A non-local URL without a password, or a private one without TLS,
logs a warning. The URL itself is never logged: it can contain the password.
"""

import ipaddress
from dataclasses import dataclass
from typing import List
from urllib.parse import urlsplit

PRIVATE_SUFFIXES = (".internal", ".local", ".lan", ".svc", ".svc.cluster.local", ".localdomain")


@dataclass(frozen=True)
class RedisConnection:
    where: str  # "local", "private" or "remote"
    tls: bool
    auth: bool


def _where(scheme: str, host: str) -> str:
    if scheme == "unix" or not host:
        return "local"
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return "local"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith(PRIVATE_SUFFIXES):
            return "private"
        return "remote"
    if address.is_loopback:
        return "local"
    if address.is_private or address.is_link_local:
        return "private"
    return "remote"


def describe(url: str) -> RedisConnection:
    """Where a Redis URL points, and whether it uses TLS and a password"""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return RedisConnection(
        where=_where(scheme, parts.hostname or ""),
        tls=scheme == "rediss",
        auth=bool(parts.password),
    )


def warnings(connection: RedisConnection) -> List[str]:
    """What to warn about for a connection that is allowed to start"""
    found: List[str] = []
    if connection.where == "local":
        return found
    if not connection.tls:
        found.append(
            "REDIS_URL connects without TLS: use rediss:// so conversations and the "
            "password aren't sent in plain text"
        )
    if not connection.auth:
        found.append("REDIS_URL has no password: anyone who can reach Redis can read it")
    return found


def refused(connection: RedisConnection) -> bool:
    """A plain-text connection to a remote host is refused unless explicitly allowed"""
    return connection.where == "remote" and not connection.tls
