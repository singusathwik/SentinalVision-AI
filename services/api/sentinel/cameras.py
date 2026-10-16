"""Encrypted RTSP configuration and exact-IP pinning against DNS rebinding."""

import base64
import hashlib
import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

from cryptography.fernet import Fernet

from .config import settings


def cipher() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret.encode()).digest()))


def pin_url(url: str) -> str:
    parsed = urlparse(url)
    allowed_hosts = set(filter(None, settings.rtsp_hosts.split(",")))
    allowed_ips = set(filter(None, settings.rtsp_allowed_ips.split(",")))
    if parsed.scheme != "rtsp" or parsed.hostname not in allowed_hosts or parsed.fragment:
        raise ValueError("RTSP host must be explicitly provisioned")
    addresses = {
        str(ipaddress.ip_address(item[4][0]))
        for item in socket.getaddrinfo(parsed.hostname, parsed.port or 554, type=socket.SOCK_STREAM)
    }
    if not addresses or not addresses.issubset(allowed_ips):
        raise ValueError("All resolved camera IPs must be explicitly allowlisted")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or (ip.is_loopback and not settings.allow_loopback_camera_fixture)
        ):
            raise ValueError("Forbidden camera destination")
    selected = sorted(addresses)[0]
    host = f"[{selected}]" if ":" in selected else selected
    credentials = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    return urlunparse(parsed._replace(netloc=f"{credentials}{host}:{parsed.port or 554}"))


def encrypt_source(url: str) -> str:
    pin_url(url)
    return cipher().encrypt(url.encode()).decode()


def open_source(encrypted: str) -> str:
    return pin_url(cipher().decrypt(encrypted.encode()).decode())
