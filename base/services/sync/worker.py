import logging
import threading

logger = logging.getLogger(__name__)

_running = False
_thread = None
_lock = threading.Lock()
# Event used both as "stop signal" and as the interval-sleep mechanism.
# wait(timeout) returns True when set so the loop exits promptly on stop()
# instead of sitting inside a 30-second time.sleep.
_stop_event = threading.Event()


def start():
    global _running, _thread
    with _lock:
        if _running:
            return False
        _running = True
        _stop_event.clear()
        _thread = threading.Thread(target=_run_loop, daemon=True)
        _thread.start()
        logger.info('Sync worker started')
        return True


def stop():
    global _running, _thread
    with _lock:
        _running = False
        _stop_event.set()
        if _thread:
            # Worker is sleeping on _stop_event.wait so it wakes immediately;
            # the timeout here covers the case where it's mid-push.
            _thread.join(timeout=10)
            _thread = None
        logger.info('Sync worker stopped')


def is_running():
    return _running


def _sleep(seconds):
    # Returns True if the stop signal fired during the wait, False on timeout.
    return _stop_event.wait(timeout=seconds)


def _run_loop():
    global _running
    from base.services.sync.config import (
        get_sync_interval, get_sync_retry_interval,
        SyncConfig, get_pull_enabled,
    )

    while _running:
        try:
            if not SyncConfig.is_enabled():
                if _sleep(get_sync_interval()):
                    return
                continue

            from base.services.sync.service import SyncService

            push_result = SyncService.push()

            if push_result.get('offline'):
                if _sleep(get_sync_retry_interval()):
                    return
                continue

            if get_pull_enabled():
                try:
                    SyncService.pull_from_cloud()
                except Exception as e:
                    logger.error(f'Pull error in worker: {e}')
                    from base.services.sync.status import SyncStatus
                    SyncStatus.set_error(f'Pull failed: {e}')

            if _sleep(get_sync_interval()):
                return

        except Exception as e:
            logger.exception(f'Sync worker error: {e}')
            if _sleep(get_sync_retry_interval()):
                return


def start_on_ready():
    from base.services.sync.config import SyncConfig, is_local_mode
    if SyncConfig.is_enabled() and is_local_mode():
        threading.Timer(5.0, start).start()
