"""Compatibility re-export hub for the settings layer.

`AGENTS.md` claimed `ModelManagerWidgetNew` lived here. It does not: the real
class is `ModelManagerWidget` in `cellium/ui/settings/dialog.py` (line ~419),
and `dialog.py` additionally defines the alias

    ModelManagerWidgetNew = ModelManagerWidget

`cellium/ui/main_window.py` picks that name up via
`from cellium.ui.settings.dialog import *`, not from this file.

This module re-exports the two widget modules that the settings layer shares,
so any `from cellium.ui.settings.models import *` in the codebase keeps working
and resolves to the same objects the dialog layer sees.
"""

from cellium.ui.widgets.toggle import *  # noqa: F401,F403  (currently empty)
from cellium.ui.chat.glass import *  # noqa: F401,F403
