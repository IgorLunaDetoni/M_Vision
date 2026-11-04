"""Verified HTTPS with native certificate-chain building when available."""
from functools import lru_cache
import ssl
from urllib.request import urlopen


@lru_cache(maxsize=1)
def tls_context():
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    # Use an explicit context, without changing SSL behavior globally.
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def https_open(request, timeout=30):
    return urlopen(request, timeout=timeout, context=tls_context())
