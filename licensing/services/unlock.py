"""Ed25519 verification for the vendor's perpetual-unlock files.

This is the customer's escape hatch: if the vendor ever shuts down and
stops issuing license renewals, they publish a signed JSON blob. Any
alpha_pos install can paste it into /api/licensing/unlock and the kill
switch goes away forever — no more heartbeats required.

Threat model + intentional design choices:

- The signature is over a FIXED payload string `PERPETUAL_UNLOCK_v1`
  plus a timestamp. It is NOT bound to a specific tenant or email. The
  whole point is "one published file unlocks every install" — if the
  vendor disappears, we want any operator to be able to use the file.
- That means a leaked / stolen unlock file would also work on pirated
  installs. We accept this — the file is meant to be public after the
  vendor shuts down.
- The vendor's private key is the trust anchor. Custody is operational
  (hardware vault); a leak means losing remote-control of the install
  base. The plan documents this risk.
- We use a versioned payload string (`_v1`) so a future protocol
  change can introduce `PERPETUAL_UNLOCK_v2` that the old client
  refuses, forcing operators to upgrade alpha_pos before accepting it.
- The `signed_at` timestamp is informational — it's logged so operators
  can see when the file was created. We do NOT reject "old" files; the
  vendor might sign a file years before publishing it.
"""
import base64
import binascii
import json
import logging
from typing import Optional, Tuple

from django.conf import settings

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover — cryptography is in requirements
    _CRYPTO_AVAILABLE = False


logger = logging.getLogger(__name__)


# The exact byte sequence the vendor's private key must sign. Versioned
# so a future protocol bump can require a new alpha_pos build to honor
# new unlocks.
PAYLOAD_STRING = 'PERPETUAL_UNLOCK_v1'


def _vendor_public_key() -> Optional[Ed25519PublicKey]:
    """Materialise the configured pubkey. Returns None if unset or
    malformed — caller surfaces a 503 in that case."""
    raw_hex = (getattr(settings, 'LICENSE_VENDOR_PUBLIC_KEY', '') or '').strip()
    if not raw_hex:
        return None
    if not _CRYPTO_AVAILABLE:
        logger.error('cryptography package missing; cannot verify unlock')
        return None
    try:
        raw = binascii.unhexlify(raw_hex)
    except (binascii.Error, ValueError):
        logger.error('LICENSE_VENDOR_PUBLIC_KEY is not valid hex')
        return None
    if len(raw) != 32:
        logger.error(
            'LICENSE_VENDOR_PUBLIC_KEY must be exactly 32 bytes (got %d)',
            len(raw),
        )
        return None
    return Ed25519PublicKey.from_public_bytes(raw)


def _signed_message(signed_at: str) -> bytes:
    """The exact bytes the vendor's private key must have signed.

    Format: `PERPETUAL_UNLOCK_v1|<ISO8601 signed_at>`. The pipe is fine
    here because both halves are constrained — neither can contain a
    pipe — so there's no ambiguity for a forger to exploit."""
    return f'{PAYLOAD_STRING}|{signed_at}'.encode('utf-8')


def verify_unlock_file(unlock_file_b64: str) -> Tuple[bool, str]:
    """Verify a base64-encoded unlock file. Returns (is_valid, reason).

    `unlock_file_b64` is what the operator pastes — base64 of the JSON
    blob {"payload": "PERPETUAL_UNLOCK_v1", "signed_at": "...",
    "signature": "<hex>"}. The base64 wrapping makes the file
    copy-pasteable in environments that mangle whitespace.
    """
    pubkey = _vendor_public_key()
    if pubkey is None:
        return False, 'vendor_pubkey_not_configured'

    if not unlock_file_b64 or not isinstance(unlock_file_b64, str):
        return False, 'unlock_file_required'

    # Decode the outer base64 wrapper. Tolerate whitespace and missing
    # padding so the file survives copy-paste through email / Telegram.
    try:
        raw = base64.b64decode(unlock_file_b64.strip(), validate=False)
    except (binascii.Error, ValueError):
        return False, 'unlock_file_not_base64'

    try:
        blob = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return False, 'unlock_file_not_json'
    if not isinstance(blob, dict):
        return False, 'unlock_file_not_object'

    payload = blob.get('payload')
    signed_at = blob.get('signed_at')
    sig_hex = blob.get('signature')

    if payload != PAYLOAD_STRING:
        return False, 'payload_string_mismatch'
    if not isinstance(signed_at, str) or not signed_at:
        return False, 'signed_at_missing'
    if not isinstance(sig_hex, str) or not sig_hex:
        return False, 'signature_missing'

    try:
        signature = binascii.unhexlify(sig_hex)
    except (binascii.Error, ValueError):
        return False, 'signature_not_hex'

    try:
        pubkey.verify(signature, _signed_message(signed_at))
    except InvalidSignature:
        return False, 'signature_invalid'
    except Exception:
        logger.exception('unexpected error verifying unlock signature')
        return False, 'verification_error'

    return True, signed_at
