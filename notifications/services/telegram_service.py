import logging
import requests

logger = logging.getLogger(__name__)


def _redact(text, secret):
    # Strip the bot token from any string that may include it (Telegram URLs
    # contain the token in the path, and some error paths echo the URL).
    if not secret or not text:
        return text
    return str(text).replace(secret, '<REDACTED>')


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
        token = config.bot_token
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
                    # Don't return resp.text directly — Telegram error bodies
                    # sometimes echo the request URL (which contains the
                    # bot token). Keep the status code and a redacted snippet.
                    last_error = f'HTTP {resp.status_code}: {_redact(resp.text[:200], token)}'
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
                last_error = _redact(str(e), token)
                logger.error(f'Telegram error for {chat_id}: {last_error}')

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
