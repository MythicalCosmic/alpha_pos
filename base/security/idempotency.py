import json
import logging
from functools import wraps

from django.db import IntegrityError, transaction
from django.http import JsonResponse

from base.models import IdempotencyKey

logger = logging.getLogger(__name__)

_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def idempotent(scope):
    """Dedup retries of a write endpoint by the `Idempotency-Key` header.

    Behavior when the header is present:
    * First time we see (actor, scope, key) → execute the view, store the
      response, return it.
    * The same key replayed after the original finished → return the stored
      response without re-executing.
    * The same key replayed while the original is still in flight → 409 so
      the second attempt doesn't double-act.

    Without the header the view runs unchanged — the contract change is
    opt-in for clients.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method in _SAFE_METHODS:
                return view_func(request, *args, **kwargs)

            key = (request.META.get('HTTP_IDEMPOTENCY_KEY') or '').strip()
            if not key or len(key) > 128:
                return view_func(request, *args, **kwargs)

            actor = getattr(request, 'user', None)
            actor_id = getattr(actor, 'id', None) or 0
            full_scope = f"{actor_id}:{scope}"

            # Claim the (scope, key) row. Losing the unique-constraint race
            # means another request already owns it — fall through to the
            # replay / in-flight branch.
            record = None
            we_own_it = False
            try:
                with transaction.atomic():
                    record = IdempotencyKey.objects.create(
                        scope=full_scope,
                        key=key,
                        response_status=0,
                        response_body={},
                    )
                we_own_it = True
            except IntegrityError:
                record = IdempotencyKey.objects.filter(
                    scope=full_scope, key=key,
                ).first()

            if not we_own_it:
                if not record:
                    # Vanishingly unlikely race (row was deleted between the
                    # IntegrityError and the lookup). Behave like a fresh
                    # request rather than 500.
                    return view_func(request, *args, **kwargs)
                if record.response_status == 0:
                    return JsonResponse(
                        {
                            'success': False,
                            'message': 'Duplicate request — original is still in progress.',
                        },
                        status=409,
                    )
                return JsonResponse(
                    record.response_body,
                    status=record.response_status,
                )

            # We won the claim. Run the view and persist its response.
            response = view_func(request, *args, **kwargs)

            body = {}
            try:
                if response.content:
                    body = json.loads(response.content)
            except (ValueError, TypeError):
                # Non-JSON responses (rare on this surface) replay with an
                # empty body but the correct status code. That's enough to
                # tell the client "we already handled it."
                body = {}

            try:
                IdempotencyKey.objects.filter(pk=record.pk).update(
                    response_status=response.status_code,
                    response_body=body,
                )
            except Exception:
                logger.exception(
                    'failed to persist idempotency response (scope=%s key=%s)',
                    full_scope, key,
                )

            return response

        return wrapper

    return decorator
