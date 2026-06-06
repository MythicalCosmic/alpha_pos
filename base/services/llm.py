"""Single entry point for LLM calls (Claude / Anthropic).

Both the stock AI assistant and the demand forecaster call Claude through
`call_claude()` so the model, key, and SDK wiring live in one place. The API
key and model are operator-configured (desktop panel / env):

    ANTHROPIC_API_KEY   — required; the assistant/forecast report a clean
                          'llm_key_missing' until it's set.
    ANTHROPIC_MODEL     — defaults to the current Sonnet (claude-sonnet-4-6).
                          Set to 'claude-sonnet-4-5' for the older Sonnet, or
                          'claude-opus-4-8' for the most capable model.

No sampling params (temperature/top_p) are sent — they're rejected by the Opus
4.7/4.8 models, so omitting them keeps `call_claude` model-agnostic.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:  # SDK not installed in this environment
    anthropic = None

# Current Sonnet — same price as 4.5, 1M context. Override via ANTHROPIC_MODEL.
DEFAULT_MODEL = 'claude-sonnet-4-6'


def get_model():
    return getattr(settings, 'ANTHROPIC_MODEL', '') or DEFAULT_MODEL


def call_claude(prompt, system=None, max_tokens=2048):
    """Call Claude with a single user message.

    Returns (text, error). On success error is None. On failure text is None
    and error is one of:
        'llm_sdk_missing'  — the anthropic package isn't installed
        'llm_key_missing'  — ANTHROPIC_API_KEY isn't configured
        <raw str>          — any other API/network error (already logged)
    """
    if anthropic is None:
        return None, 'llm_sdk_missing'
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '') or ''
    if not api_key:
        return None, 'llm_key_missing'
    try:
        client = anthropic.Anthropic(api_key=api_key)
        kwargs = {
            'model': get_model(),
            'max_tokens': max_tokens,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if system:
            kwargs['system'] = system
        resp = client.messages.create(**kwargs)
        # content is a list of blocks; concatenate the text blocks.
        text = ''.join(
            b.text for b in resp.content if getattr(b, 'type', None) == 'text'
        )
        return text, None
    except Exception as e:  # noqa: BLE001 — surface a code, log the detail
        logger.exception('claude call failed')
        return None, str(e)
