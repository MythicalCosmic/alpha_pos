"""Inbound Telegram bot: dispatch incoming updates to command handlers.

Today this only handles `/start` — the foothold for the upcoming
customer-facing layer (menu / order / status / loyalty). The dispatcher
is intentionally tiny so adding `/menu` etc. is a one-line registration.

Replies render through the editable NotificationTemplate system so a
restaurant can change the bot's wording from the admin UI without a deploy.
The template names this module uses are:

    telegram.start              — reply to /start
    telegram.unknown_command    — reply when we don't recognize the input
"""
import logging

from django.utils import timezone

from base.notifications.telegram import TelegramAPI
from notifications.models import NotificationTemplate, TelegramCustomer

logger = logging.getLogger(__name__)


# Registered command handlers. Add new commands here as they're built.
# Convention: lower-case, leading slash, no arguments in the key.
COMMAND_HANDLERS = {}


def register(command):
    """Decorator: register a handler under `/command`."""
    def decorator(fn):
        COMMAND_HANDLERS[command] = fn
        return fn
    return decorator


def handle_update(update):
    """Top-level entry point invoked from the webhook view.

    `update` is the raw Telegram update dict. We only handle `message`
    updates today; callback queries / inline queries are silently ignored
    so an admin who's enabled them in BotFather doesn't get error spam.
    """
    message = update.get('message') or {}
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    text = (message.get('text') or '').strip()

    if not chat_id:
        return None

    customer = _upsert_customer(chat_id, message.get('from') or {})

    if customer.is_blocked:
        # Telegram keeps trying to deliver some updates even after a block;
        # don't bother replying.
        return None

    handler = _resolve_handler(text)
    return handler(customer, text)


def _resolve_handler(text):
    """Find the registered handler for `text`, or fall back to unknown."""
    if not text.startswith('/'):
        return _handle_unknown
    # Strip arguments — "/start abc" → "/start". Bot-suffixed commands
    # (Telegram appends @bot_username when used in groups) are normalized
    # the same way: "/start@my_bot" → "/start".
    head = text.split()[0]
    if '@' in head:
        head = head.split('@', 1)[0]
    return COMMAND_HANDLERS.get(head, _handle_unknown)


def _upsert_customer(chat_id, sender):
    """Create or refresh the TelegramCustomer row for this chat."""
    defaults = {
        'first_name': (sender.get('first_name') or '')[:64],
        'last_name': (sender.get('last_name') or '')[:64],
        'username': (sender.get('username') or '')[:64],
        'language_code': (sender.get('language_code') or '')[:8],
    }
    customer, created = TelegramCustomer.objects.get_or_create(
        chat_id=chat_id, defaults=defaults,
    )
    if not created:
        # Refresh profile fields in case the user changed their handle.
        for field, value in defaults.items():
            if value:
                setattr(customer, field, value)
        customer.last_seen_at = timezone.now()
        customer.save(update_fields=['first_name', 'last_name', 'username',
                                     'language_code', 'last_seen_at'])
    return customer


def _send(customer, text):
    """Reply to `customer` and update is_blocked if Telegram says so."""
    ok, err = TelegramAPI.send_to_chat(customer.chat_id, text)
    if not ok and err and err.startswith('API 403'):
        customer.is_blocked = True
        customer.save(update_fields=['is_blocked'])
    return ok


def _render(template_type, context):
    """Pull a NotificationTemplate by type and render it with context.

    Mirrors SenderService.send so behavior matches what staff notifications
    do — same HTML escaping, same brand fallback. Returns None if the
    template isn't seeded; the caller should handle that gracefully.
    """
    from notifications.services.sender_service import _escape_context
    from notifications.models import NotificationSettings

    template = NotificationTemplate.objects.filter(
        notification_type=template_type, is_enabled=True,
    ).first()
    if not template:
        return None

    settings = NotificationSettings.load()
    context.setdefault('brand', settings.brand_name)

    try:
        return template.template_text.format(**_escape_context(context))
    except (KeyError, IndexError, ValueError) as e:
        logger.error('Template render error for %s: %s', template_type, e)
        return None


# ---- Command handlers ------------------------------------------------------

@register('/start')
def _handle_start(customer, text):
    rendered = _render('telegram.start', {
        'first_name': customer.first_name or 'friend',
    })
    if rendered is None:
        # Safe fallback if the template was deleted by an over-zealous admin.
        rendered = 'Welcome.'
    return _send(customer, rendered)


def _handle_unknown(customer, text):
    rendered = _render('telegram.unknown_command', {
        'first_name': customer.first_name or 'friend',
        'input': text,
    })
    if rendered is None:
        rendered = "Sorry, I don't recognize that command yet."
    return _send(customer, rendered)
