"""Long-running heartbeat loop.

Launched by entrypoint.sh alongside gunicorn — NOT inside an
AppConfig.ready() thread (which would spawn one heartbeat per gunicorn
worker, tripling load and skewing last_heartbeat_at). Running as its
own process keeps it observable: `docker ps` shows it, `docker logs`
includes its output, and `docker kill` stops it cleanly via SIGTERM.

Cadence: configurable via LICENSE_HEARTBEAT_INTERVAL (seconds).
Backoff on failure follows 5m → 15m → 60m and resets on recovery.
"""
import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from licensing.services import heartbeat as heartbeat_svc


logger = logging.getLogger(__name__)


# Backoff schedule when the control center is unreachable / 5xx. The
# values are *minimum* seconds between attempts; the daemon picks the
# higher of (LICENSE_HEARTBEAT_INTERVAL, backoff[step]) so a config that
# specifies an unusually long base interval still dominates.
_BACKOFF_SCHEDULE_S = (5 * 60, 15 * 60, 60 * 60)


class Command(BaseCommand):
    help = (
        'Run the license heartbeat loop. Talks to LICENSE_CONTROL_CENTER_URL '
        'every LICENSE_HEARTBEAT_INTERVAL seconds (default 300). Backs off '
        'exponentially on failure.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Send one heartbeat and exit. Useful for cron-style setups.',
        )
        parser.add_argument(
            '--interval', type=int, default=None,
            help='Override LICENSE_HEARTBEAT_INTERVAL for this run.',
        )

    def handle(self, *args, **options):
        # SIGTERM / SIGINT must break the sleep cleanly so docker stop
        # doesn't have to wait the full interval.
        self._stop = False

        def _on_signal(signum, _frame):
            logger.info('heartbeat_daemon: signal %s received, exiting',
                        signum)
            self._stop = True

        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)

        interval = options['interval'] or getattr(
            settings, 'LICENSE_HEARTBEAT_INTERVAL', 300,
        )

        if options['once']:
            self._tick()
            return

        backoff_step = 0
        logger.info('heartbeat_daemon: starting, interval=%ss', interval)

        # Fire immediately so a fresh-boot install confirms its key fast
        # (otherwise the first heartbeat would be `interval` seconds away
        # and the operator wouldn't see the SETUP_SUCCEEDED state propagate
        # to last_heartbeat_at right away).
        success = self._tick()
        if not success:
            backoff_step = min(backoff_step + 1, len(_BACKOFF_SCHEDULE_S))

        while not self._stop:
            sleep_s = (
                _BACKOFF_SCHEDULE_S[backoff_step - 1]
                if backoff_step > 0 else interval
            )
            sleep_s = max(sleep_s, interval if backoff_step == 0 else 60)
            self._sleep(sleep_s)
            if self._stop:
                break
            success = self._tick()
            if success:
                if backoff_step != 0:
                    logger.info('heartbeat_daemon: recovered')
                backoff_step = 0
            else:
                backoff_step = min(backoff_step + 1, len(_BACKOFF_SCHEDULE_S))

    # -- internals ----------------------------------------------------------

    def _tick(self) -> bool:
        """Fire one heartbeat. Returns True when the call should NOT
        trigger backoff (success OR no-op). False on a real failure."""
        try:
            body, status = heartbeat_svc.do_heartbeat()
        except Exception:
            logger.exception('heartbeat_daemon: unexpected exception')
            return False

        if status == 200:
            logger.info('heartbeat ok: status=%s', body.get('status'))
            return True
        if status == 304:
            # UNREGISTERED / PERPETUAL_UNLOCK — nothing to phone home about.
            # Don't burn backoff on these; the operator may register at
            # any moment.
            logger.debug('heartbeat noop: %s', body.get('message'))
            return True

        logger.warning(
            'heartbeat failed: status=%s message=%s',
            status, body.get('message'),
        )
        return False

    def _sleep(self, seconds: float):
        """Sleep in 1s slices so SIGTERM during a long interval doesn't
        wait the full duration."""
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            time.sleep(min(1.0, end - time.monotonic()))
