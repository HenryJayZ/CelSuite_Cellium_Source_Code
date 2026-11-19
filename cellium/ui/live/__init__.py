"""CelAS Live Mode - full-screen voice companion for Cellium.

    from cellium.ui.live import LiveModeController, LiveStage

    stage = LiveStage(parent=self, gender="Female")
    self.live = LiveModeController(self, stage, hide_targets=[...])
    btn_live.clicked.connect(self.live.enter_live)

See ``CELAS_LIVE_MODE_SPEC.md`` for the state machine and the definition of done.
"""

from .talk_animation import TalkEnvelope, talking_expression
from .live_mode import LiveModeController, LiveState, LiveStage

try:  # audio needs sounddevice; Live Mode must still work without it
    from .audio import LiveAudio
except Exception:  # pragma: no cover
    LiveAudio = None

__all__ = [
    "LiveAudio",
    "LiveModeController",
    "LiveStage",
    "LiveState",
    "TalkEnvelope",
    "talking_expression",
]
