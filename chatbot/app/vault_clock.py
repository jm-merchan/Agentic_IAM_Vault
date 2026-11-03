"""Diagnose a failed JWT request without relaxing validation or retrying it."""
from email.utils import parsedate_to_datetime
import math
import time

import jwt

from .security import AccessDenied


CLOCK_MESSAGE = ('Vault ha rechazado el JWT y su reloj difiere {seconds} s del servidor de Lumen. '
                 'Sincroniza los relojes de la VM y del host y vuelve a intentarlo.')


class VaultClockSkew(AccessDenied):
    """Clock evidence, distinct from a policy denial or token revocation."""


def jwt_clock_offset(response, token, *, now=None):
    """Return an offset only when server time excludes an otherwise live JWT.

    Date is evidence from the TLS-protected Vault response. Decoding here is
    observational: it never authenticates a caller or changes Vault's result.
    A generic 403, an expired JWT or a revoked token with aligned clocks remains
    an ordinary denial. HTTP Date has one-second precision; allow a 30 s margin.
    """
    if response.status_code != 403:
        return None
    now = time.time() if now is None else now
    try:
        server = parsedate_to_datetime(response.headers['date'])
        if server.tzinfo is None:
            return None
        server_time = server.timestamp()
        offset = server_time - now
        if abs(offset) <= 30:
            return None
        claims = jwt.decode(token, options={'verify_signature': False})
        expiry = claims.get('exp')
        not_before = claims.get('nbf', claims.get('iat'))
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (expiry, not_before)):
            return None
        if not (not_before <= now + 15 and expiry > now):
            return None
        if not_before > server_time + 15 or expiry < server_time - 15:
            return offset
    except (KeyError, ValueError, TypeError, OverflowError, jwt.InvalidTokenError):
        pass
    return None


def raise_for_clock_mismatch(response, token, current):
    offset = jwt_clock_offset(response, token)
    if offset is not None:
        current.set_attribute('vault.clock.offset_seconds', round(offset, 1))
        raise VaultClockSkew(CLOCK_MESSAGE.format(seconds=round(abs(offset))))
