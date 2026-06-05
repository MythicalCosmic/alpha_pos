"""Headless smoke test for the desktop bridge (no GUI). Run:
    .venv/Scripts/python.exe -m desktop._smoketest
Exercises: setup -> start server -> connection -> mock sync -> fiscal -> stop.
"""
import time

from desktop.bridge import Api


def main():
    api = Api()
    print('state    :', api.get_state())
    print('setup    :', api.run_setup().get('ok'))
    print('start    :', api.start_server())
    time.sleep(1.5)
    print('status   :', api.server_status())
    print('conn     :', api.test_server_connection())
    print('fiscalmod:', api.fiscal_set_mode('mock'))
    print('mocksync :', api.send_mock_sync())
    print('getmock  :', api.fetch_mock_sync())
    print('fiscalt  :', api.fiscal_test())
    print('fiscalst :', api.fiscal_status())
    print('license  :', api.license_status())
    print('sync     :', api.sync_status())
    print('stop     :', api.stop_server())


if __name__ == '__main__':
    main()
