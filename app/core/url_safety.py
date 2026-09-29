import ipaddress
import socket
from urllib.parse import urlsplit


def _base_identity(url: str) -> tuple:
    """Match an exact HTTPS origin and base path (optional trailing slash).

    No encoded path, dot segments, credentials, query or fragment is accepted;
    the allowlist contains API bases, not URL prefixes or arbitrary endpoints.
    """
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError("Invalid URL")
    if any(c in url for c in ("\\", "%", "?", "#")):
        raise ValueError("Ambiguous URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname.endswith(".")
        or parsed.netloc.endswith(":")
        or "//" in parsed.path
        or any(part in (".", "..") for part in parsed.path.split("/"))
    ):
        raise ValueError("Invalid API base")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = 443 if parsed.port is None else parsed.port
    if port < 1:
        raise ValueError("Invalid port")
    return parsed.scheme, host, port, parsed.path.rstrip("/")


def is_safe_base_url(url: str, allowlist: list) -> bool:
    """Check structured allowlist membership and every resolved address."""
    try:
        identity = _base_identity(url)
        allowed = []
        for base in allowlist:
            try:
                allowed.append(_base_identity(base))
            except (ValueError, UnicodeError):
                continue
        if identity not in allowed:
            return False
        addresses = socket.getaddrinfo(identity[1], identity[2])
        return bool(addresses) and all(
            ipaddress.ip_address(address[4][0]).is_global
            and not ipaddress.ip_address(address[4][0]).is_multicast
            for address in addresses
        )
    except (ValueError, UnicodeError, OSError):
        return False
