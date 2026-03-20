import logging
from threading import Thread
from base.notifications.config import NotificationConfig
from base.notifications.telegram import TelegramAPI
from base.notifications.queue import NotificationQueue
from base.notifications.helpers import format_datetime, format_money, format_prep_time
from base.notifications import messages

logger = logging.getLogger(__name__)


class OrderNotification:

    @classmethod
    def on_new_order(cls, order):
        if not NotificationConfig.is_enabled('order.new'):
            return

        items_lines = []
        for item in order.items.select_related('product').all():
            items_lines.append(f'  {item.product.name} x{item.quantity} — {format_money(item.price * item.quantity)} so\'m')

        cashier_name = '—'
        if order.cashier:
            cashier_name = f'{order.cashier.first_name} {order.cashier.last_name}'

        order_type = messages.ORDER_TYPE_LABELS.get(order.order_type, order.order_type)
        _, time_str = format_datetime()

        text = messages.ORDER_NEW.format(
            display_id=order.display_id,
            cashier_name=cashier_name,
            order_type=order_type,
            total_amount=format_money(order.total_amount),
            items_list='\n'.join(items_lines),
            time=time_str,
        ).strip()

        cls._send_async(text, 'order.new')

    @classmethod
    def on_order_ready(cls, order_id):
        if not NotificationConfig.is_enabled('order.ready'):
            return

        from base.models import Order
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return

        prep_time = '—'
        if order.ready_at and order.created_at:
            seconds = (order.ready_at - order.created_at).total_seconds()
            prep_time = format_prep_time(seconds)

        _, time_str = format_datetime()

        text = messages.ORDER_READY.format(
            display_id=order.display_id,
            prep_time=prep_time,
            total_amount=format_money(order.total_amount),
            time=time_str,
        ).strip()

        cls._send_async(text, 'order.ready')

    @classmethod
    def on_order_cancelled(cls, order_id):
        if not NotificationConfig.is_enabled('order.cancelled'):
            return

        from base.models import Order
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return

        _, time_str = format_datetime()

        text = messages.ORDER_CANCELLED.format(
            display_id=order.display_id,
            total_amount=format_money(order.total_amount),
            time=time_str,
        ).strip()

        cls._send_async(text, 'order.cancelled')

    @classmethod
    def on_order_paid(cls, order_id):
        if not NotificationConfig.is_enabled('order.paid'):
            return

        from base.models import Order
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return

        _, time_str = format_datetime()

        text = messages.ORDER_PAID.format(
            display_id=order.display_id,
            total_amount=format_money(order.total_amount),
            time=time_str,
        ).strip()

        cls._send_async(text, 'order.paid')

    @classmethod
    def _send_async(cls, text, notification_type):
        def _send():
            try:
                ok, error = TelegramAPI.send_message(text)
                if not ok:
                    NotificationQueue.add(text, notification_type)
                    logger.warning(f'Notification queued ({notification_type}): {error}')
            except Exception as e:
                NotificationQueue.add(text, notification_type)
                logger.error(f'Notification error ({notification_type}): {e}')

        Thread(target=_send, daemon=True).start()
