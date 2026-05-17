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
    def send_to_chat(chat_id, text, reply_markup=None):
        """Send `text` to a single chat_id. Used by the inbound bot to reply
        directly to whoever messaged us, in contrast to send_message() which
        broadcasts to every staff chat in NotificationConfig.

        `reply_markup` is an optional Telegram reply_markup dict — typically
        a ReplyKeyboardMarkup with `request_contact` for /login, or
        `{'remove_keyboard': True}` to drop the custom keyboard once we're
        done with it.

        Returns (ok, error). On 403 (user blocked the bot), the caller
        should mark the TelegramCustomer is_blocked so we stop trying.
        """
        token = NotificationConfig.get_bot_token()
        if not token:
            return False, 'Not configured'

        url = f'https://api.telegram.org/bot{token}/sendMessage'
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
        }
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup
        try:
            resp = requests.post(url, json=payload, timeout=NOTIFICATION_TIMEOUT)
            if resp.status_code == 200:
                return True, None
            return False, f'API {resp.status_code}: {resp.text[:200]}'
        except requests.exceptions.ConnectionError:
            return False, 'No internet connection'
        except requests.exceptions.Timeout:
            return False, 'Request timeout'
        except Exception as e:
            logger.error(f'Telegram send_to_chat error: {e}')
            return False, str(e)

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
