"""Calibrated noise cancellation for captured voice.

First-run calibration records a few seconds of your *quiet room* and stores
it as a spectral-gating profile. Every clip captured afterwards is cleaned
with `noisereduce <https://github.com/timsainb/noisereduce>`_ (stationary
spectral gating) before any STT engine sees it - the settings slider maps
straight onto noisereduce's ``prop_decrease`` (0 = off, 100 = full gate).

Why this library: it needs no model download (metered-connection friendly),
runs on the already-installed numpy/scipy, and its noise-profile workflow is
exactly what mic calibration produces. If the import ever fails, clips pass
through untouched so transcription never breaks.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from ..core.config import BASE_DIR

#: Sibling of cerebrium_settings.json - same persisted-state directory.
PROFILE_FILE: Path = BASE_DIR / "cel_noise_profile.npz"

_settings = {"enabled": True, "strength": 0.7}
_profile: Optional[np.ndarray] = None
_profile_sr = 16000
_profile_loaded = False
_nr = "unloaded"          # lazy noisereduce module | None | "unloaded"

__all__ = [
    "configure", "has_profile", "save_profile", "clear_profile", "profile_rms",
    "denoise", "measure", "estimate_reduction", "profile_gate",
    "effective_gate", "PROFILE_FILE",
]


# ── settings bridge ────────────────────────────────────────────────────────
def configure(settings) -> None:
    """Mirror the app settings dict (cheap; called on boot and on save)."""
    if not isinstance(settings, dict):
        return
    try:
        _settings["enabled"] = bool(settings.get("noise_cancel_enabled", True))
        s = float(settings.get("noise_cancel_strength", 70))
        _settings["strength"] = max(0.0, min(1.0, s / 100.0))
    except (TypeError, ValueError):
        pass


def set_enabled(on: bool) -> None:
    _settings["enabled"] = bool(on)


def set_strength(percent) -> None:
    try:
        _settings["strength"] = max(0.0, min(1.0, float(percent) / 100.0))
    except (TypeError, ValueError):
        pass


# ── wav helpers ────────────────────────────────────────────────────────────
def _decode_wav(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    """16-bit PCM wav bytes → float32 mono [-1, 1] + sample rate."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM is supported")
        sr = wf.getframerate()
        ch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    y = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        y = y.reshape(-1, ch).mean(axis=1)
    return y, sr


def _encode_wav(y: np.ndarray, sr: int) -> bytes:
    pcm = np.clip(np.asarray(y, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())
    return bio.getvalue()


def measure(wav_bytes: bytes) -> float:
    """RMS of a clip (0..1) - the number the visualizer displays."""
    try:
        y, _ = _decode_wav(wav_bytes)
        if y.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(y))))
    except Exception:
        return 0.0


# ── profile persistence ────────────────────────────────────────────────────
def has_profile() -> bool:
    global _profile, _profile_sr, _profile_loaded
    if not _profile_loaded:
        _profile_loaded = True
        _profile = None
        if PROFILE_FILE.is_file():
            try:
                data = np.load(str(PROFILE_FILE))
                _profile = np.asarray(data["noise"], dtype=np.float32)
                _profile_sr = int(data["sr"]) if "sr" in data else 16000
            except Exception:
                _profile = None
    return _profile is not None


def save_profile(wav_bytes: bytes) -> dict:
    """Persist a captured noise-floor clip. Returns measured stats."""
    global _profile, _profile_sr, _profile_loaded
    y, sr = _decode_wav(wav_bytes)
    if y.size < int(sr * 0.25):
        raise ValueError("noise sample too short")
    max_n = int(sr * 5.0)
    if y.size > max_n:
        y = y[:max_n].copy()
    _profile = y.astype(np.float32)
    _profile_sr = int(sr)
    _profile_loaded = True
    np.savez(str(PROFILE_FILE), noise=_profile, sr=np.int32(_profile_sr))
    rms = float(np.sqrt(np.mean(np.square(_profile))))
    return {"rms": rms, "seconds": round(_profile.size / max(1, sr), 2),
            "sr": _profile_sr}


def profile_rms() -> float:
    """RMS of the saved room floor (0.0 when no profile).

    The live VU meter subtracts ``profile_rms() * strength`` so the bar
    shows what the gate actually lets through - a quiet PC fan stops
    making the meter dance while you speak.
    """
    if not has_profile() or _profile is None or _profile.size == 0:
        return 0.0
    try:
        return float(np.sqrt(np.mean(np.square(_profile))))
    except Exception:
        return 0.0


def profile_gate(margin: float = 1.6, percentile: float = 95.0) -> float:
    """A silence gate that actually clears *this* room.

    ``profile_rms()`` is the mean of the calibration clip, which is the wrong
    number for silence detection. A steady fan can sit at 0.14 RMS while speech
    peaks at 0.3: with a flat 0.012 gate the recorder never sees a quiet
    second, the auto-stop never fires, and live mode looks completely dead.
    What matters is the loudest *background* block, so take a high percentile
    of 50 ms block RMS and clear it by ``margin``.
    """
    if not has_profile() or _profile is None or _profile.size == 0:
        return 0.0
    try:
        block = max(1, int(_profile_sr * 0.05))
        n = _profile.size // block
        if n < 1:
            return float(np.sqrt(np.mean(np.square(_profile)))) * float(margin)
        blocks = _profile[: n * block].reshape(n, block)
        rms = np.sqrt(np.mean(np.square(blocks), axis=1))
        return float(np.percentile(rms, percentile)) * float(margin)
    except Exception:
        return 0.0


def effective_gate(settings=None, base: float = 0.012,
                   cap: float = 0.40) -> float:
    """The silence gate to hand a recorder on *this* machine.

    One rule for every caller - live calls, the “Hey Cel” wizard, anything
    else that has to tell speech from a quiet room:

    * start from ``base``,
    * and if cancellation is on and a profile exists, raise it until it clears
      the room's own loudest background, scaled by the strength slider,
    * bounded at both ends - never so high that ordinary speech cannot cross
      it, never so low that a noisy room never reads as silence.

    user's floor is 0.137 RMS (fan, loudest block 0.147), so a flat 0.006 in
    the wizard meant the "silence" it waited for never happened.
    """
    try:
        gate = float(base)
    except (TypeError, ValueError):
        gate = 0.012
    try:
        if (isinstance(settings, dict)
                and settings.get("noise_cancel_enabled", True)
                and has_profile()):
            try:
                strength = max(0.0, min(1.0, float(
                    settings.get("noise_cancel_strength", 70)) / 100.0))
            except (TypeError, ValueError):
                strength = 0.7
            gate = max(gate, profile_gate(margin=1.15 + 0.85 * strength))
    except Exception:
        pass
    try:
        return max(0.006, min(gate, cap))
    except TypeError:
        return 0.012


def clear_profile() -> None:
    global _profile, _profile_loaded
    _profile = None
    _profile_loaded = True
    try:
        if PROFILE_FILE.is_file():
            PROFILE_FILE.unlink()
    except OSError:
        pass


def _resample(y: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Polyphase resample - profile captured at one rate, clip at another."""
    import scipy.signal
    g = np.gcd(int(sr_to), int(sr_from))
    if g <= 0:
        return y
    up, down = int(sr_to) // g, int(sr_from) // g
    return scipy.signal.resample_poly(y, up, down).astype(np.float32)


def _profile_for(sr: int) -> Optional[np.ndarray]:
    p = _profile
    if p is None or p.size < 64:
        return None
    if sr == _profile_sr:
        return p
    try:
        return _resample(p, _profile_sr, sr)
    except Exception:
        return p


# ── the actual gate ────────────────────────────────────────────────────────
def _nr_module():
    global _nr
    if _nr == "unloaded":
        try:
            import noisereduce as _mod
            _nr = _mod
        except Exception:
            _nr = None
    return None if _nr == "unloaded" else _nr


def _spectral_denoise_numpy(y: np.ndarray, sr: int, noise_ref: Optional[np.ndarray], strength: float) -> np.ndarray:
    """Built-in STFT spectral subtraction + 110Hz fan-rumble high-pass + speech normalization."""
    import scipy.signal
    if y.size < 512:
        return y
    # 1. 110Hz 2nd-order Butterworth high-pass filter to kill PC fan rumble & DC offset
    try:
        sos = scipy.signal.butter(2, 110.0 / (0.5 * sr), btype="highpass", output="sos")
        y = scipy.signal.sosfilt(sos, y).astype(np.float32)
    except Exception:
        y = np.append(y[0], y[1:] - 0.95 * y[:-1]).astype(np.float32)

    # 2. Short-Time Fourier Transform (STFT) spectral gating
    nperseg = 512
    noverlap = 384
    _f, _t, Zxx = scipy.signal.stft(y, fs=sr, nperseg=nperseg, noverlap=noverlap)
    mag = np.abs(Zxx)
    phase = np.angle(Zxx)

    # Estimate noise spectrum from the quietest 20% of frames in this clip (tracks live fan RPM!)
    frame_energy = np.mean(mag, axis=0)
    n_quiet = max(1, int(frame_energy.size * 0.22))
    quiet_idx = np.argsort(frame_energy)[:n_quiet]
    live_noise_spec = np.median(mag[:, quiet_idx], axis=1, keepdims=True)

    # Blend with calibrated room profile if present
    if noise_ref is not None and noise_ref.size >= 512:
        try:
            if 'sos' in locals():
                noise_ref = scipy.signal.sosfilt(sos, noise_ref).astype(np.float32)
            _, _, Znoise = scipy.signal.stft(noise_ref, fs=sr, nperseg=nperseg, noverlap=noverlap)
            prof_spec = np.median(np.abs(Znoise), axis=1, keepdims=True)
            noise_spec = np.maximum(live_noise_spec, prof_spec * 0.85)
        except Exception:
            noise_spec = live_noise_spec
    else:
        noise_spec = live_noise_spec

    # Soft spectral gate: subtract fan spectrum scaled by user's strength slider
    over_sub = 1.0 + 1.8 * float(strength)
    floor_gain = max(0.02, 1.0 - 0.92 * float(strength))
    gain = np.clip((mag - over_sub * noise_spec) / np.maximum(mag, 1e-7), floor_gain, 1.0)
    # Smooth gain slightly across time & frequency to prevent "musical noise" artifacts
    if gain.shape[1] >= 3:
        gain = 0.25 * np.roll(gain, 1, axis=1) + 0.50 * gain + 0.25 * np.roll(gain, -1, axis=1)

    _, cleaned = scipy.signal.istft(gain * mag * np.exp(1j * phase), fs=sr, nperseg=nperseg, noverlap=noverlap)
    cleaned = np.asarray(cleaned[:y.size], dtype=np.float32)

    # 3. Normalize speech peak so Whisper hears crystal-clear syllables
    peak = float(np.max(np.abs(cleaned))) if cleaned.size else 0.0
    if 0.015 < peak < 0.65:
        cleaned = cleaned * min(3.2, 0.72 / peak)
    return np.clip(cleaned, -1.0, 1.0)


def denoise(wav_bytes: bytes, strength: Optional[float] = None) -> bytes:
    """Spectral-gate a clip against the calibrated room profile + live stationary fan floor."""
    if not wav_bytes or not _settings["enabled"]:
        return wav_bytes
    s = _settings["strength"] if strength is None else max(0.0, min(1.0, float(strength)))
    if s <= 0.001:
        return wav_bytes
    try:
        y, sr = _decode_wav(wav_bytes)
        if y.size < 512:
            return wav_bytes
        noise = _profile_for(sr) if has_profile() else None
        cleaned = _spectral_denoise_numpy(y, sr, noise, s)
        if cleaned.size == 0:
            return wav_bytes
        return _encode_wav(cleaned, sr)
    except Exception:
        return wav_bytes


def estimate_reduction(wav_bytes: bytes, strength: float,
                       profile_wav: Optional[bytes] = None) -> Tuple[float, float]:
    """(rms_before, rms_after) at a candidate strength - for the preview.

    ``profile_wav`` lets the calibration dialog audition the *just-captured*
    room clip before it has been saved as the official profile.
    """
    before = measure(wav_bytes)
    after = before
    try:
        s = max(0.0, min(1.0, float(strength)))
        if s <= 0.001:
            return before, after
        mod = _nr_module()
        if mod is None:
            return before, after
        y, sr = _decode_wav(wav_bytes)
        if y.size < 512:
            return before, after
        if profile_wav is not None:
            noise, _nsr = _decode_wav(profile_wav)
            if noise.size < 64:
                return before, after
            if _nsr != sr:
                noise = _resample(noise, _nsr, sr)
        else:
            noise = _profile_for(sr)
        if noise is None:
            return before, after
        cleaned = mod.reduce_noise(y=y, sr=sr, y_noise=noise,
                                   prop_decrease=s, stationary=True)
        after = float(np.sqrt(np.mean(np.square(
            np.asarray(cleaned, dtype=np.float32)))))
    except Exception:
        after = before
    return before, after
