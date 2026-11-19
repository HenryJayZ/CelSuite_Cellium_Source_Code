from __future__ import annotations
import math
import random
import time
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget


class _SmokePlume:
    """Single volumetric nebula smoke lobe with curl-noise drift & elliptical rotation."""
    __slots__ = (
        "angle", "ang_vel", "orbit_rx", "orbit_ry", "wobble_freq", "wobble_phase",
        "rx", "ry", "rot", "rot_vel", "color_idx", "alpha_base", "seed",
    )

    def __init__(self, idx: int, total: int, rng: random.Random):
        frac = idx / max(1, total)
        self.angle = frac * math.tau + rng.uniform(-0.25, 0.25)
        self.ang_vel = rng.choice((-1.0, 1.0)) * rng.uniform(0.18, 0.42)
        self.orbit_rx = rng.uniform(0.08, 0.30)
        self.orbit_ry = rng.uniform(0.06, 0.24)
        self.wobble_freq = rng.uniform(0.45, 1.15)
        self.wobble_phase = rng.uniform(0.0, math.tau)
        self.rx = rng.uniform(0.22, 0.44)
        self.ry = rng.uniform(0.14, 0.30)
        self.rot = rng.uniform(0.0, 180.0)
        self.rot_vel = rng.uniform(-18.0, 18.0)
        self.color_idx = idx % 5
        self.alpha_base = rng.uniform(0.16, 0.32)
        self.seed = rng.uniform(0.0, 100.0)


class SmokeField(QWidget):
    """Google Gemini Live style multi-layered volumetric smoke nebula behind Cel's face."""

    _PALETTE_IDLE = (
        ((124, 58, 237),  (76, 29, 149),  (15, 10, 35)),
        ((147, 51, 234),  (88, 28, 135),  (18, 10, 38)),
        ((79, 70, 229),   (49, 46, 129),  (12, 12, 36)),
        ((192, 38, 211),  (112, 26, 117), (22, 10, 36)),
        ((109, 40, 217),  (59, 7, 100),   (14, 8, 30)),
    )
    _PALETTE_USER = (
        ((56, 189, 248),  (37, 99, 235),  (15, 18, 42)),
        ((129, 140, 248), (79, 70, 229),  (16, 14, 40)),
        ((168, 85, 247),  (91, 33, 182),  (18, 12, 38)),
        ((34, 211, 238),  (29, 78, 216),  (12, 16, 38)),
        ((139, 92, 246),  (67, 56, 202),  (15, 12, 36)),
    )
    _PALETTE_CEL = (
        ((232, 121, 249), (147, 51, 234), (24, 10, 42)),
        ((168, 85, 247),  (107, 33, 168), (20, 10, 38)),
        ((244, 114, 182), (157, 23, 77),  (26, 10, 38)),
        ((139, 92, 246),  (76, 29, 149),  (16, 10, 36)),
        ((192, 132, 252), (126, 34, 206), (22, 12, 40)),
    )

    def __init__(self, parent=None, count: int = 18):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        rng = random.Random(20261015)
        self._plumes = [_SmokePlume(i, max(14, count), rng) for i in range(max(14, count))]
        self._t0 = time.monotonic()
        self._last_t = self._t0
        self._phase_clock = 0.0
        self._target_energy = 0.15
        self._energy = 0.15
        self._speaker_mode = "idle"
        self._talking = False
        self._user_rms = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def start(self) -> None:
        if not self._timer.isActive():
            self._last_t = time.monotonic()
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def dispose(self) -> None:
        self._timer.stop()

    def set_talking(self, talking: bool) -> None:
        self._talking = bool(talking)
        if self._talking:
            self._speaker_mode = "cel"
            self._target_energy = max(self._target_energy, 0.82)
        elif self._user_rms < 0.02:
            self._speaker_mode = "idle"
            self._target_energy = 0.16

    def set_voice_level(self, rms: float, speaker: str = "user") -> None:
        val = max(0.0, min(1.0, float(rms) * 8.5))
        if speaker == "cel" or self._talking:
            self._speaker_mode = "cel"
            self._target_energy = 0.45 + 0.55 * max(0.35, val)
        elif val > 0.08:
            self._user_rms = val
            self._speaker_mode = "user"
            self._target_energy = 0.35 + 0.65 * val
        else:
            self._user_rms = 0.0
            if not self._talking:
                self._speaker_mode = "idle"
                self._target_energy = 0.16

    def set_intensity(self, level: float) -> None:
        self._target_energy = max(0.08, min(1.0, float(level)))

    def set_level(self, level: float) -> None:
        self.set_voice_level(level, speaker="user")

    def pulse(self, strength: float = 0.85) -> None:
        self._energy = min(1.0, self._energy + 0.35 * float(strength))
        self._target_energy = max(self._target_energy, min(1.0, float(strength)))

    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.005, min(0.10, now - self._last_t))
        self._last_t = now
        alpha = 0.22 if self._target_energy > self._energy else 0.07
        self._energy += (self._target_energy - self._energy) * alpha
        if self._talking:
            mod = 0.18 * math.sin(now * 9.5) * math.cos(now * 6.2)
            self._energy = max(0.45, min(1.0, 0.76 + mod))

        speed_mult = 0.65 + 2.15 * self._energy
        self._phase_clock += dt * speed_mult
        for p in self._plumes:
            p.angle = (p.angle + p.ang_vel * dt * speed_mult) % math.tau
            p.rot = (p.rot + p.rot_vel * dt * speed_mult) % 360.0
        if self.isVisible():
            self.update()

    def paintEvent(self, _event) -> None:
        w = float(self.width())
        h = float(self.height())
        if w < 10 or h < 10:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        cx, cy = w * 0.50, h * 0.47
        span = min(w, h)
        e = self._energy
        t = self._phase_clock
        palette = (
            self._PALETTE_CEL if self._speaker_mode == "cel"
            else (self._PALETTE_USER if self._speaker_mode == "user" else self._PALETTE_IDLE)
        )

        base_r = span * (0.42 + 0.14 * e)
        bg_grad = QRadialGradient(QPointF(cx, cy), base_r)
        c0 = palette[0][1]
        bg_grad.setColorAt(0.0, QColor(c0[0], c0[1], c0[2], int(38 + 42 * e)))
        bg_grad.setColorAt(0.55, QColor(c0[0], c0[1], c0[2], int(18 + 24 * e)))
        bg_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(bg_grad)
        painter.drawEllipse(QPointF(cx, cy), base_r * 1.25, base_r * 0.95)

        scale_boost = 0.82 + 0.46 * e
        alpha_boost = 0.72 + 0.68 * e
        for p in self._plumes:
            curl_x = math.sin(t * p.wobble_freq + p.wobble_phase) + 0.45 * math.cos(t * 0.7 + p.seed)
            curl_y = math.cos(t * p.wobble_freq * 0.85 + p.wobble_phase) + 0.45 * math.sin(t * 0.6 + p.seed)
            px = cx + (math.cos(p.angle) * p.orbit_rx + 0.08 * curl_x) * span * scale_boost
            py = cy + (math.sin(p.angle) * p.orbit_ry + 0.08 * curl_y) * span * scale_boost
            rx = p.rx * span * scale_boost * (1.0 + 0.14 * math.sin(t + p.seed))
            ry = p.ry * span * scale_boost * (1.0 + 0.14 * math.cos(t * 0.9 + p.seed))

            inner_rgb, mid_rgb, outer_rgb = palette[p.color_idx % len(palette)]
            a_peak = int(min(135, p.alpha_base * 255.0 * alpha_boost))
            a_mid = int(a_peak * 0.52)

            painter.save()
            painter.translate(px, py)
            painter.rotate(p.rot + 18.0 * curl_x)
            painter.scale(1.0, max(0.35, ry / max(1.0, rx)))
            grad = QRadialGradient(QPointF(0.0, 0.0), rx, QPointF(rx * 0.18 * curl_x, rx * 0.18 * curl_y))
            grad.setColorAt(0.0, QColor(inner_rgb[0], inner_rgb[1], inner_rgb[2], a_peak))
            grad.setColorAt(0.42, QColor(mid_rgb[0], mid_rgb[1], mid_rgb[2], a_mid))
            grad.setColorAt(0.78, QColor(outer_rgb[0], outer_rgb[1], outer_rgb[2], int(a_mid * 0.28)))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(grad)
            painter.drawEllipse(QPointF(0.0, 0.0), rx, rx)
            painter.restore()
        painter.end()
