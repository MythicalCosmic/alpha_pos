"""Regression tests for the inbound Telegram bot foothold.

Webhook auth, dispatcher resolution, /start handler, customer upsert.
TelegramAPI.send_to_chat is monkeypatched so no real network calls happen.
"""
import json

import pytest
from django.test import Client

from notifications.models import NotificationTemplate, TelegramCustomer


pytestmark = pytest.mark.django_db


WEBHOOK_URL = '/api/telegram/webhook/'
SECRET = 'test-webhook-secret-token'


@pytest.fixture
def webhook_secret(settings):
    """Set TELEGRAM_WEBHOOK_SECRET on the live settings for the test.
    pytest-django's `settings` fixture rolls back automatically."""
    settings.TELEGRAM_WEBHOOK_SECRET = SECRET
    return SECRET


@pytest.fixture
def patched_send(monkeypatch):
    """Replace TelegramAPI.send_to_chat with a recorder so tests can assert
    on what the bot tried to send without hitting api.telegram.org."""
    sent = []

    def fake_send(chat_id, text):
        sent.append({'chat_id': chat_id, 'text': text})
        return True, None

    from base.notifications.telegram import TelegramAPI
    monkeypatch.setattr(TelegramAPI, 'send_to_chat', staticmethod(fake_send))
    return sent


@pytest.fixture
def start_template(db):
    return NotificationTemplate.objects.create(
        notification_type='telegram.start',
        name='Bot welcome',
        template_text='Welcome {first_name} to {brand}',
    )


@pytest.fixture
def unknown_template(db):
    return NotificationTemplate.objects.create(
        notification_type='telegram.unknown_command',
        name='Bot unknown',
        template_text="Sorry {first_name}, didn't get '{input}'",
    )


def _post(client, body, secret=SECRET):
    headers = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': secret} if secret else {}
    return client.post(
        WEBHOOK_URL,
        data=json.dumps(body),
        content_type='application/json',
        **headers,
    )


def _start_update(chat_id=12345, first_name='Adrian'):
    return {
        'update_id': 1,
        'message': {
            'message_id': 1,
            'chat': {'id': chat_id, 'type': 'private'},
            'from': {
                'id': chat_id,
                'first_name': first_name,
                'language_code': 'uz',
                'is_bot': False,
            },
            'text': '/start',
        },
    }


class TestWebhookAuth:
    def test_no_secret_configured_returns_503(self, settings):
        # Default: TELEGRAM_WEBHOOK_SECRET = ''. Webhook refuses to serve.
        settings.TELEGRAM_WEBHOOK_SECRET = ''
        client = Client()
        resp = _post(client, _start_update())
        assert resp.status_code == 503

    def test_wrong_secret_returns_401(self, webhook_secret):
        client = Client()
        resp = _post(client, _start_update(), secret='not-the-secret')
        assert resp.status_code == 401

    def test_missing_secret_header_returns_401(self, webhook_secret):
        client = Client()
        resp = _post(client, _start_update(), secret=None)
        assert resp.status_code == 401

    def test_correct_secret_returns_200(self, webhook_secret, patched_send, start_template):
        client = Client()
        resp = _post(client, _start_update())
        assert resp.status_code == 200

    def test_invalid_json_still_returns_200(self, webhook_secret):
        # Telegram-friendly: never make Telegram retry forever on a junk body.
        client = Client()
        resp = client.post(
            WEBHOOK_URL,
            data='not json',
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET,
        )
        assert resp.status_code == 200


class TestStartCommand:
    def test_start_creates_customer(self, webhook_secret, patched_send, start_template):
        client = Client()
        _post(client, _start_update(chat_id=999, first_name='Adrian'))
        customer = TelegramCustomer.objects.get(chat_id=999)
        assert customer.first_name == 'Adrian'
        assert customer.language_code == 'uz'

    def test_start_renders_template_with_first_name(
        self, webhook_secret, patched_send, start_template,
    ):
        client = Client()
        _post(client, _start_update(chat_id=999, first_name='Adrian'))
        assert len(patched_send) == 1
        sent = patched_send[0]
        assert sent['chat_id'] == 999
        assert 'Welcome Adrian' in sent['text']
        assert 'Alpha POS' in sent['text']  # default brand

    def test_start_repeated_updates_existing_customer(
        self, webhook_secret, patched_send, start_template,
    ):
        client = Client()
        _post(client, _start_update(chat_id=999, first_name='Adrian'))
        # Same chat_id, different first_name (user changed Telegram profile)
        update = _start_update(chat_id=999, first_name='Adrian-Updated')
        _post(client, update)

        # Still only one row, but profile fields refreshed.
        assert TelegramCustomer.objects.filter(chat_id=999).count() == 1
        assert TelegramCustomer.objects.get(chat_id=999).first_name == 'Adrian-Updated'

    def test_blocked_customer_gets_no_reply(
        self, webhook_secret, patched_send, start_template,
    ):
        TelegramCustomer.objects.create(chat_id=999, first_name='X', is_blocked=True)
        client = Client()
        _post(client, _start_update(chat_id=999, first_name='X'))
        assert len(patched_send) == 0


class TestCommandRouting:
    def test_unknown_command_falls_through_to_unknown_template(
        self, webhook_secret, patched_send, unknown_template,
    ):
        client = Client()
        update = _start_update()
        update['message']['text'] = '/somethingweird'
        _post(client, update)
        assert len(patched_send) == 1
        assert "didn't get" in patched_send[0]['text']
        assert '/somethingweird' in patched_send[0]['text']

    def test_bot_suffixed_command_resolves(
        self, webhook_secret, patched_send, start_template,
    ):
        # Telegram appends @bot_username when commands run in groups —
        # /start@my_alpha_bot must route to the same /start handler.
        client = Client()
        update = _start_update()
        update['message']['text'] = '/start@my_alpha_bot'
        _post(client, update)
        assert len(patched_send) == 1
        assert 'Welcome' in patched_send[0]['text']

    def test_non_message_update_silently_ignored(self, webhook_secret, patched_send):
        # callback_query / inline_query / edited_message etc. — we don't
        # handle these yet; they shouldn't crash the webhook.
        client = Client()
        resp = _post(client, {
            'update_id': 2,
            'callback_query': {'id': 'cbq', 'data': 'x'},
        })
        assert resp.status_code == 200
        assert len(patched_send) == 0

    def test_plain_text_treated_as_unknown(
        self, webhook_secret, patched_send, unknown_template,
    ):
        client = Client()
        update = _start_update()
        update['message']['text'] = 'hello there'
        _post(client, update)
        assert len(patched_send) == 1
        assert "didn't get" in patched_send[0]['text']


class TestSendErrorHandling:
    def test_403_marks_customer_blocked(self, webhook_secret, monkeypatch, start_template):
        from base.notifications.telegram import TelegramAPI
        monkeypatch.setattr(
            TelegramAPI, 'send_to_chat',
            staticmethod(lambda chat_id, text: (False, 'API 403: forbidden')),
        )
        client = Client()
        _post(client, _start_update(chat_id=999))
        customer = TelegramCustomer.objects.get(chat_id=999)
        assert customer.is_blocked is True
