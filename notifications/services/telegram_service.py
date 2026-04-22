import logging
import requests

logger = logging.getLogger(__name__)


class TelegramService:
    @classmethod
    def _get_config(cls):
        from notifications.models import NotificationSettings
        return NotificationSettings.load()

    @classmethod
    def send_message(cls, text):
        config = cls._get_config()
        if not config.bot_token or not config.chat_ids:
            return False, 'Bot token or chat IDs not configured'

        url = f'https://api.telegram.org/bot{config.bot_token}/sendMessage'
        success = True
        last_error = ''

        for chat_id in config.chat_ids:
            try:
                resp = requests.post(url, json={
                    'chat_id': chat_id,
                    'text': text,
                    'parse_mode': 'HTML',
                }, timeout=config.timeout)
                if not resp.ok:
                    success = False
                    last_error = resp.text
                    logger.warning(f'Telegram API error for {chat_id}: {resp.status_code}')
            except requests.ConnectionError:
                success = False
                last_error = 'Connection error'
                logger.warning(f'Telegram connection error for {chat_id}')
            except requests.Timeout:
                success = False
                last_error = 'Timeout'
                logger.warning(f'Telegram timeout for {chat_id}')
            except Exception as e:
                success = False
                last_error = str(e)
                logger.error(f'Telegram error for {chat_id}: {e}')

        return success, last_error

    @classmethod
    def is_online(cls):
        config = cls._get_config()
        if not config.bot_token:
            return False
        try:
            url = f'https://api.telegram.org/bot{config.bot_token}/getMe'
            resp = requests.get(url, timeout=5)
            return resp.ok
        except Exception:
            return False
