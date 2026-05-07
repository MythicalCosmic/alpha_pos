import html
import logging
from threading import Thread
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
        def _do():
            from notifications.services.telegram_service import TelegramService
            from notifications.services.queue_service import QueueService

            settings = NotificationSettings.load()
            for chat_id in (settings.chat_ids or []):
                try:
                    ok, error = TelegramService.send_message(text)
                    NotificationLog.objects.create(
                        notification_type=notification_type,
                        recipient=str(chat_id),
                        message_text=text,
                        status='SENT' if ok else 'FAILED',
                        error_message=error if not ok else '',
                    )
                    if not ok:
                        QueueService.add(text, notification_type)
                except Exception as e:
                    NotificationLog.objects.create(
                        notification_type=notification_type,
                        recipient=str(chat_id),
                        message_text=text,
                        status='FAILED',
                        error_message=str(e),
                    )
                    QueueService.add(text, notification_type)
                break  # send_message already sends to all chat_ids
        Thread(target=_do, daemon=True).start()
