"""Order → fiscal receipt orchestration.

Entry point is fiscalize_order(), called (safely) from the order pay flow. It
honours the runtime toggle, builds the payload, calls the configured provider,
and records the outcome on a FiscalReceipt row. Under the default serve-now
policy a provider failure is recorded as FAILED (not raised) so the sale still
completes and a retry sweep picks it up later.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from base.helpers.response import ServiceResponse
from fiscalization.config import FiscalConfig
from fiscalization.models import FiscalReceipt
from fiscalization.providers import get_provider
from fiscalization.services.builder import build_receipt_payload

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8


class FiscalizationService:

    @staticmethod
    def get_provider():
        cfg = FiscalConfig.tenant()
        return get_provider(cfg['provider'], cfg)

    @staticmethod
    def fiscalize_order(order_id, receipt_type=FiscalReceipt.ReceiptType.SALE):
        """Fiscalize one order. Idempotent: re-calling for an already-CONFIRMED
        receipt is a no-op. Returns (ServiceResponse, status)."""
        if not FiscalConfig.is_enabled():
            return ServiceResponse.success(
                data={'skipped': True, 'reason': 'fiscalization disabled'},
                message='Fiscalization disabled',
            )

        from base.models import Order
        order = Order.objects.filter(id=order_id).first()
        if not order:
            return ServiceResponse.not_found('Order not found')

        mode = FiscalConfig.get_mode()
        cfg = FiscalConfig.tenant()

        with transaction.atomic():
            receipt, _ = FiscalReceipt.objects.select_for_update().get_or_create(
                order=order, receipt_type=receipt_type,
                defaults={
                    'status': FiscalReceipt.Status.PENDING,
                    'provider': cfg['provider'], 'mode': mode,
                    'amount': order.total_amount,
                    'branch_id': getattr(order, 'branch_id', '') or '',
                },
            )
            if receipt.status == FiscalReceipt.Status.CONFIRMED:
                return ServiceResponse.success(
                    data=FiscalizationService._serialize(receipt),
                    message='Already fiscalized',
                )

            payload = build_receipt_payload(order, cfg, receipt_type)
            receipt.request_payload = payload
            receipt.provider = cfg['provider']
            receipt.mode = mode
            receipt.attempts += 1
            receipt.status = FiscalReceipt.Status.SENT
            receipt.save()

        # Provider call OUTSIDE the row lock — network I/O must not hold a DB
        # lock on the receipt row.
        provider = get_provider(cfg['provider'], cfg)
        try:
            if receipt_type == FiscalReceipt.ReceiptType.REFUND:
                result = provider.fiscalize_refund(payload)
            else:
                result = provider.fiscalize(payload)
        except Exception as exc:  # noqa: BLE001 — provider may raise anything
            logger.exception('fiscalize_order: provider raised')
            result = type('R', (), {'success': False, 'error': str(exc),
                                    'raw_response': {}, 'fiscal_sign': None,
                                    'qr_url': None, 'fiscal_number': None})()

        with transaction.atomic():
            receipt = FiscalReceipt.objects.select_for_update().get(pk=receipt.pk)
            receipt.response_payload = getattr(result, 'raw_response', {}) or {}
            if result.success:
                receipt.status = FiscalReceipt.Status.CONFIRMED
                receipt.fiscal_sign = result.fiscal_sign
                receipt.qr_url = result.qr_url
                receipt.fiscal_number = result.fiscal_number
                receipt.fiscalized_at = timezone.now()
                receipt.error = ''
            else:
                receipt.status = FiscalReceipt.Status.FAILED
                receipt.error = result.error or 'unknown provider error'
            receipt.save()

        if result.success:
            return ServiceResponse.success(
                data=FiscalizationService._serialize(receipt),
                message='Fiscalized',
            )
        # error() has no data slot; return the tuple shape directly so callers
        # still get the receipt snapshot alongside the failure.
        return ({'success': False, 'message': receipt.error,
                 'data': FiscalizationService._serialize(receipt)}, 400)

    @staticmethod
    def fiscalize_on_payment(order_id):
        """Hook for the order pay flow. NEVER raises — under serve-now policy a
        failure is logged + queued, the sale stands. Under block-on-failure the
        caller checks the returned success flag."""
        try:
            result, _ = FiscalizationService.fiscalize_order(order_id)
            return result
        except Exception:
            logger.exception('fiscalize_on_payment failed (order=%s)', order_id)
            return ServiceResponse.error('fiscalization error (queued for retry)')

    @staticmethod
    def retry_failed(limit=100):
        """Re-attempt FAILED receipts under the retry cap. Run by the
        `fiscalize_retry` command / control-panel button / a periodic worker."""
        if not FiscalConfig.is_enabled():
            return {'retried': 0, 'confirmed': 0, 'still_failing': 0, 'skipped': True}
        qs = FiscalReceipt.objects.filter(
            status=FiscalReceipt.Status.FAILED, attempts__lt=MAX_ATTEMPTS,
        ).order_by('updated_at')[:limit]
        retried = confirmed = still = 0
        for receipt in qs:
            retried += 1
            result, _ = FiscalizationService.fiscalize_order(
                receipt.order_id, receipt.receipt_type,
            )
            if result.get('success'):
                confirmed += 1
            else:
                still += 1
        return {'retried': retried, 'confirmed': confirmed, 'still_failing': still}

    @staticmethod
    def stats():
        from django.db.models import Count
        rows = FiscalReceipt.objects.values('status').annotate(n=Count('id'))
        by_status = {r['status']: r['n'] for r in rows}
        return {
            'config': FiscalConfig.status(),
            'pending': by_status.get('PENDING', 0),
            'sent': by_status.get('SENT', 0),
            'confirmed': by_status.get('CONFIRMED', 0),
            'failed': by_status.get('FAILED', 0),
            'skipped': by_status.get('SKIPPED', 0),
        }

    @staticmethod
    def _serialize(receipt):
        return {
            'id': receipt.id,
            'order_id': receipt.order_id,
            'receipt_type': receipt.receipt_type,
            'status': receipt.status,
            'provider': receipt.provider,
            'mode': receipt.mode,
            'fiscal_sign': receipt.fiscal_sign,
            'qr_url': receipt.qr_url,
            'fiscal_number': receipt.fiscal_number,
            'amount': str(receipt.amount),
            'attempts': receipt.attempts,
            'error': receipt.error or None,
            'fiscalized_at': receipt.fiscalized_at.isoformat() if receipt.fiscalized_at else None,
        }
