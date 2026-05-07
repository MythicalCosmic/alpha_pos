import html
import logging
from notifications.models import NotificationSettings, NotificationTemplate, NotificationLog

logger = logging.getLogger(__name__)


def _escape_context(context):
    # Escape every string value so user-controlled fields (cashier names,
    # product names, customer phones) cannot break Telegram's HTML parser
    # or inject markup. Templates may still contain literal <b>, <i>, etc.
    out = {}
    for k, v in context.items():
        if isinstance(v, str):
            out[k] = html.escape(v, quote=False)
        else:
            out[k] = v
    return out


class SenderService:
    @classmethod
    def send(cls, notification_type, context):
        """Main send API. Resolves template, checks enabled, sends async."""
        from notifications.services.config_service import ConfigService
        if not ConfigService.is_enabled(notification_type):
            return

        template = NotificationTemplate.objects.filter(
            notification_type=notification_type
        ).first()
        if not template:
            logger.warning(f'No template for {notification_type}')
            return

        settings = NotificationSettings.load()
        context['brand'] = settings.brand_name

        try:
            text = template.template_text.format(**_escape_context(context))
        except (KeyError, IndexError) as e:
            logger.error(f'Template render error for {notification_type}: {e}')
            return

        cls._send_async(text, notification_type)

    @classmethod
    def send_raw(cls, text):
        """Send arbitrary text (for test messages)."""
        cls._send_async(text, 'test')

    @classmethod
    def _send_async(cls, text, notification_type):
        # Hand off to the single background worker which serializes sends and
        # enforces a per-chat minimum interval. Avoids spawning a thread per
        # message under burst load.
        from notifications.services.worker import enqueue
        enqueue(text, notification_type)
