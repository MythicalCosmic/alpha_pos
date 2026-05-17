"""Inbound Telegram bot: dispatch incoming updates to command handlers.

Replies render through the editable NotificationTemplate system so a
restaurant can change the bot's wording from the admin UI without a deploy.
The template names this module uses are:

    telegram.start              — reply to /start
    telegram.unknown_command    — reply when we don't recognize the input
    telegram.menu_root          — reply to /menu (top-level category list)
    telegram.menu_category      — reply to /menu <slug> (products in category)
    telegram.menu_empty         — fallback when no categories are active
    telegram.menu_not_found     — fallback when slug doesn't match
    telegram.login_prompt       — reply to /login with the share-contact keyboard
    telegram.login_success      — confirmation after we save the phone
    telegram.login_other_contact — sender shared someone else's contact card
"""
import logging

from django.db.models import Count, Q
from django.utils import timezone

from base.models import Category, Product
from base.notifications.telegram import TelegramAPI
from notifications.helpers import format_money
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
    sender = message.get('from') or {}
    text = (message.get('text') or '').strip()

    if not chat_id:
        return None

    customer = _upsert_customer(chat_id, sender)

    if customer.is_blocked:
        # Telegram keeps trying to deliver some updates even after a block;
        # don't bother replying.
        return None

    # Contact share (from the request_contact button on /login) arrives as
    # a message with a `contact` payload and no command text. Handle it
    # before text routing so users don't have to type anything.
    contact = message.get('contact')
    if contact:
        return _handle_contact(customer, contact, sender)

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


def _send(customer, text, reply_markup=None):
    """Reply to `customer` and update is_blocked if Telegram says so."""
    ok, err = TelegramAPI.send_to_chat(customer.chat_id, text, reply_markup=reply_markup)
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


@register('/menu')
def _handle_menu(customer, text):
    """Show the menu.

    Without args: list top-level active categories with item counts.
    With `<slug>`: list that category's products and any subcategories.

    Categories are filtered through the SyncManager's `active()` (excludes
    soft-deleted rows) and the explicit ACTIVE status. Products use the
    default manager and we filter is_deleted in the query.
    """
    parts = text.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ''

    if not arg:
        return _send(customer, _render_menu_root(customer))
    return _send(customer, _render_menu_category(customer, arg))


def _render_menu_root(customer):
    categories = (
        Category.objects.active()
        .filter(parent__isnull=True, status='ACTIVE')
        .annotate(product_count=Count(
            'products', filter=Q(products__is_deleted=False),
        ))
        .order_by('sort_order', 'name')
    )
    if not categories.exists():
        rendered = _render('telegram.menu_empty', {
            'first_name': customer.first_name or 'friend',
        })
        return rendered or 'No menu items are available right now.'

    # Plain text only — the dispatcher's _escape_context HTML-escapes any
    # string value passed in the template context, so inline <b> would
    # render as literal "&lt;b&gt;" markup. Bold lives in the static
    # template_text wrapper instead.
    lines = []
    for cat in categories:
        lines.append(f'• {cat.name} ({cat.product_count}) — /menu {cat.slug}')

    rendered = _render('telegram.menu_root', {
        'first_name': customer.first_name or 'friend',
        'categories_list': '\n'.join(lines),
    })
    return rendered or '\n'.join(lines)


def _render_menu_category(customer, slug):
    try:
        category = Category.objects.active().get(slug=slug, status='ACTIVE')
    except Category.DoesNotExist:
        rendered = _render('telegram.menu_not_found', {'slug': slug})
        return rendered or f"No category '{slug}'."

    products = (
        Product.objects.filter(category=category, is_deleted=False)
        .order_by('name')
    )
    product_lines = [
        f"• {p.name} — {format_money(p.price)} so'm"
        for p in products
    ]
    subcategories = (
        Category.objects.active()
        .filter(parent=category, status='ACTIVE')
        .order_by('sort_order', 'name')
    )
    subcat_lines = [
        f'• {c.name} — /menu {c.slug}' for c in subcategories
    ]

    body_parts = []
    if product_lines:
        body_parts.append('\n'.join(product_lines))
    if subcat_lines:
        body_parts.append('\n'.join(subcat_lines))
    body = '\n\n'.join(body_parts) if body_parts else '(empty)'

    rendered = _render('telegram.menu_category', {
        'category_name': category.name,
        'products_list': body,
    })
    return rendered or f'{category.name}\n{body}'


# ---- Phone linking (/login) ------------------------------------------------

# Telegram's request_contact buttons render as a custom keyboard. Tapping
# the button sends the user's *own* phone number — Telegram clients restrict
# request_contact to the sender's number, but we still verify the contact's
# user_id matches the sender before saving (a hand-crafted client can POST
# anything to the bot API, and we don't want a sender to bind their account
# to someone else's phone).
_LOGIN_KEYBOARD = {
    'keyboard': [[{'text': "📞 Raqamni ulashish", 'request_contact': True}]],
    'resize_keyboard': True,
    'one_time_keyboard': True,
}
_REMOVE_KEYBOARD = {'remove_keyboard': True}


@register('/login')
def _handle_login(customer, text):
    rendered = _render('telegram.login_prompt', {
        'first_name': customer.first_name or 'friend',
    })
    if rendered is None:
        rendered = 'Tap the button below to share your phone.'
    return _send(customer, rendered, reply_markup=_LOGIN_KEYBOARD)


def _handle_contact(customer, contact, sender):
    """Save the phone if the contact belongs to the sender, else warn."""
    contact_user_id = contact.get('user_id')
    sender_id = sender.get('id')
    if contact_user_id and sender_id and contact_user_id != sender_id:
        rendered = _render('telegram.login_other_contact', {
            'first_name': customer.first_name or 'friend',
        }) or "Please share your own phone, not someone else's."
        return _send(customer, rendered, reply_markup=_REMOVE_KEYBOARD)

    phone = (contact.get('phone_number') or '').strip()
    if not phone:
        return None
    # Telegram returns phone like "998901234567" (no leading '+'); normalize
    # so downstream order-matching can compare to whatever the cashier typed
    # at order time. We keep a leading '+' if Telegram included one.
    customer.phone_number = phone[:20]
    customer.save(update_fields=['phone_number'])

    rendered = _render('telegram.login_success', {
        'first_name': customer.first_name or 'friend',
        'phone': customer.phone_number,
    }) or f'Saved {customer.phone_number}.'
    return _send(customer, rendered, reply_markup=_REMOVE_KEYBOARD)
