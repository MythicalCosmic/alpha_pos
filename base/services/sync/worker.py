import logging
import threading
import time

logger = logging.getLogger(__name__)

_running = False
_thread = None
_lock = threading.Lock()


def start():
    global _running, _thread
    with _lock:
        if _running:
            return False
        _running = True
        _thread = threading.Thread(target=_run_loop, daemon=True)
        _thread.start()
        logger.info('Sync worker started')
        return True


def stop():
    global _running, _thread
    with _lock:
        _running = False
        if _thread:
            _thread.join(timeout=5)
            _thread = None
        logger.info('Sync worker stopped')


def is_running():
    return _running


def _run_loop():
    global _running
    from base.services.sync.config import (
        get_sync_interval, get_sync_retry_interval,
        SyncConfig, get_pull_enabled,
    )

    while _running:
        try:
            if not SyncConfig.is_enabled():
                time.sleep(get_sync_interval())
                continue

            from base.services.sync.service import SyncService

            push_result = SyncService.push()

            if push_result.get('offline'):
                time.sleep(get_sync_retry_interval())
                continue

            if get_pull_enabled():
                try:
                    SyncService.pull_from_cloud()
                except Exception as e:
                    logger.error(f'Pull error in worker: {e}')
                    from base.services.sync.status import SyncStatus
                    SyncStatus.set_error(f'Pull failed: {e}')

            time.sleep(get_sync_interval())

        except Exception as e:
            logger.exception(f'Sync worker error: {e}')
            time.sleep(get_sync_retry_interval())


def start_on_ready():
    from base.services.sync.config import SyncConfig, is_local_mode
    if SyncConfig.is_enabled() and is_local_mode():
        threading.Timer(5.0, start).start()
