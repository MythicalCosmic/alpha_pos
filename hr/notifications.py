import logging
from threading import Thread
from base.notifications.config import NotificationConfig
from base.notifications.telegram import TelegramAPI
from base.notifications.queue import NotificationQueue

logger = logging.getLogger(__name__)


class HRNotification:
    @classmethod
    def on_contract_expiring(cls, contract, days_until):
        if not NotificationConfig.is_enabled('hr.contract_expiry'):
            return
        emp = contract.employee
        name = f'{emp.user.first_name} {emp.user.last_name}'
        text = f"<b>CONTRACT EXPIRING</b>\n\nEmployee: <b>{name}</b>\nContract: {contract.contract_number}\nExpires: <b>{contract.end_date}</b>\nDays left: <b>{days_until}</b>"
        cls._send(text)

    @classmethod
    def on_probation_ending(cls, contract, days_until):
        if not NotificationConfig.is_enabled('hr.probation_end'):
            return
        emp = contract.employee
        name = f'{emp.user.first_name} {emp.user.last_name}'
        text = f"<b>PROBATION ENDING</b>\n\nEmployee: <b>{name}</b>\nProbation ends: <b>{contract.probation_end_date}</b>\nDays left: <b>{days_until}</b>"
        cls._send(text)

    @classmethod
    def on_document_expiring(cls, doc, days_until):
        if not NotificationConfig.is_enabled('hr.document_expiry'):
            return
        emp = doc.employee
        name = f'{emp.user.first_name} {emp.user.last_name}'
        text = f"<b>DOCUMENT EXPIRING</b>\n\nEmployee: <b>{name}</b>\nDocument: {doc.title} ({doc.get_document_type_display()})\nExpires: <b>{doc.expiry_date}</b>\nDays left: <b>{days_until}</b>"
        cls._send(text)

    @classmethod
    def _send(cls, text):
        def _do():
            try:
                ok, err = TelegramAPI.send_message(text)
                if not ok:
                    NotificationQueue.add(text, 'hr')
            except Exception as e:
                NotificationQueue.add(text, 'hr')
                logger.error(f'HR notification error: {e}')
        Thread(target=_do, daemon=True).start()
