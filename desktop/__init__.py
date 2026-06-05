"""Alpha POS desktop control panel.

A small native (pywebview) GUI that an operator/installer uses on the single
restaurant PC to: accept the ToS on first run, enter the business's own config
(fiscal identity, license, branch, Telegram), start/stop the local POS server,
and run the built-in self-tests (sync heartbeat, license/subscription/balance,
mock sync round-trip, Telegram test message, fiscalization test).

The Django backend runs IN-PROCESS via waitress, so the whole thing packages
into one .exe with PyInstaller — no separate Python or server to manage.
"""
