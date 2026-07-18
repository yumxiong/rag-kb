import ipaddress
import socket
from urllib.parse import urlparse


def is_safe_base_url(url: str, allowlist: list) -> bool:
    u = urlparse(url)
    if u.scheme != "https":
        return False
    if not any(url.startswith(a) for a in allowlist):
        return False
    for fam, _, _, _, sa in set(socket.getaddrinfo(u.hostname, None)):
        ip = ipaddress.ip_address(sa[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False
    return True
