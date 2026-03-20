import logging
import requests
from base.notifications.config import NotificationConfig, NOTIFICATION_TIMEOUT

logger = logging.getLogger(__name__)


class TelegramAPI:

    @staticmethod
    def send_message(text):
        token = NotificationConfig.get_bot_token()
        chat_ids = NotificationConfig.get_chat_ids()

        if not token or not chat_ids:
            logger.warning('Telegram not configured (missing token or chat_ids)')
            return False, 'Not configured'

        url = f'https://api.telegram.org/bot{token}/sendMessage'
        all_ok = True
        last_error = None

        for chat_id in chat_ids:
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML',
            }
            try:
                resp = requests.post(url, json=payload, timeout=NOTIFICATION_TIMEOUT)
                if resp.status_code != 200:
                    all_ok = False
                    last_error = f'API {resp.status_code} for chat {chat_id}'
                    logger.warning(last_error)
            except requests.exceptions.ConnectionError:
                all_ok = False
                last_error = 'No internet connection'
            except requests.exceptions.Timeout:
                all_ok = False
                last_error = 'Request timeout'
            except Exception as e:
                all_ok = False
                last_error = str(e)
                logger.error(f'Telegram send error: {e}')

        return all_ok, last_error

    @staticmethod
    def is_online():
        token = NotificationConfig.get_bot_token()
        if not token:
            return False
        try:
            resp = requests.get(
                f'https://api.telegram.org/bot{token}/getMe',
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False
