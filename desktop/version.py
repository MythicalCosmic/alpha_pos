"""Single source of truth for the desktop app version.

Bumped on every release; the release script (tools/release.py) reads this to
name the update bundle, and the updater (desktop/updater.py) compares it against
the version advertised by the update server.
"""
__version__ = "1.0.0"

# Logical app name used by tufup for the bundle archive prefix and the trusted
# metadata. Must stay stable across releases or clients won't recognise updates.
APP_NAME = "AlphaPOS"
