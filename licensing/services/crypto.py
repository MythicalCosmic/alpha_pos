"""Fernet wrapper for encrypting the license key at rest.

The license key is the only secret the License row carries. Storing it
in cleartext would mean a DB dump (backups, support exports, accidental
log line) leaks credentials that let the holder act as this tenant
against the control center. Encrypt with Fernet keyed by
LICENSE_FERNET_KEY so a stolen DB still requires the env var.

Dev fallback: if LICENSE_FERNET_KEY is unset and DEBUG is on, derive a
key deterministically from SECRET_KEY so `runserver` + tests work
without extra setup. Production must set LICENSE_FERNET_KEY explicitly.
"""
import base64
import hashlib
import logging
from typing import Optional

from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


logger = logging.getLogger(__name__)


def _resolve_fernet_key() -> bytes:
    """Return a 32-byte urlsafe-base64 Fernet key.

    Priority: settings.LICENSE_FERNET_KEY (explicit env) → derived from
    SECRET_KEY (dev fallback). In non-DEBUG with no LICENSE_FERNET_KEY,
    we still derive from SECRET_KEY but log a warning; refusing to boot
    would brick a misconfigured production deploy.
    """
    explicit = getattr(settings, 'LICENSE_FERNET_KEY', '') or ''
    if explicit:
        return explicit.encode('utf-8') if isinstance(explicit, str) else explicit

    if not getattr(settings, 'DEBUG', False):
        # Loud once-per-process warning so it shows up in container logs.
        if not getattr(_resolve_fernet_key, '_warned', False):
            logger.warning(
                'LICENSE_FERNET_KEY is unset in a non-DEBUG environment; '
                'falling back to SECRET_KEY-derived key. License rotation '
                'will break if SECRET_KEY rotates. Pin LICENSE_FERNET_KEY '
                'and never rotate it.'
            )
            _resolve_fernet_key._warned = True

    digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_resolve_fernet_key())


def encrypt_key(cleartext: str) -> bytes:
    """Encrypt a license key for at-rest storage. Returns bytes safe for
    a BinaryField."""
    if not cleartext:
        return b''
    return _fernet().encrypt(cleartext.encode('utf-8'))


def decrypt_key(blob: bytes) -> Optional[str]:
    """Decrypt a previously-stored license key. Returns None on tamper /
    wrong-key (e.g. the operator rotated LICENSE_FERNET_KEY)."""
    if not blob:
        return None
    try:
        return _fernet().decrypt(bytes(blob)).decode('utf-8')
    except InvalidToken:
        logger.error(
            'License key decryption failed — LICENSE_FERNET_KEY may have '
            'rotated. The operator must re-run the setup wizard to issue '
            'a new key.'
        )
        return None
