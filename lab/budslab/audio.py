"""Microphone capture + quality metrics, to learn what the buds' mic can deliver.

Records from any input device (default: the one whose name contains "Buds"), saves 16-bit WAV, and
measures: native sample rate, true audio bandwidth, peak/RMS level, noise floor, SNR, clipping.
All local; audio never leaves the machine.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np


def _sd():
    try:
        import sounddevice as sd
        return sd
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"sounddevice unavailable ({exc}); pip install sounddevice") from exc


def list_inputs() -> list[dict]:
    sd = _sd()
    default = sd.default.device[0]
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append({"index": i, "name": d["name"], "rate": d["default_samplerate"],
                        "channels": d["max_input_channels"], "is_default": i == default,
                        "is_buds": bool(re.search(r"buds|sm-r400", d["name"], re.I))})
    return out


def pick_device(index: int | None) -> dict:
    devs = list_inputs()
    if index is not None:
        for d in devs:
            if d["index"] == index:
                return d
        raise ValueError(f"no input device {index}")
    for d in devs:
        if d["is_buds"]:
            return d
    raise LookupError("Buds FE is not listed as an input device. Connect the buds and select them as the input "
                      "in System Settings > Sound (macOS only exposes the mic once they act as a headset).")


def _db(x: float) -> float:
    return round(float(20 * np.log10(max(x, 1e-9))), 1)


def analyse(x: np.ndarray, rate: int) -> dict:
    """x: float array in [-1, 1]."""
    if x.size < rate // 5:
        return {"error": "recording too short"}
    frame = max(1, int(rate * 0.02))
    n = x.size // frame
    rms = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1))
    floor = float(np.percentile(rms, 10))
    thresh = max(floor * 3, 1e-4)
    active = rms[rms > thresh]
    act_rms = float(np.sqrt(np.mean(active ** 2))) if active.size else 0.0
    # bandwidth: highest frequency whose averaged power is within 60 dB of the spectral peak
    win = np.hanning(2048)
    segs = [x[i:i + 2048] * win for i in range(0, x.size - 2048, 1024)]
    bw = None
    if segs:
        spec = np.mean([np.abs(np.fft.rfft(s)) ** 2 for s in segs], axis=0)
        freqs = np.fft.rfftfreq(2048, 1 / rate)
        keep = np.where(10 * np.log10(spec / spec.max() + 1e-20) > -60)[0]
        bw = int(freqs[keep.max()]) if keep.size else None
    snr = round(_db(act_rms) - _db(floor), 1) if active.size else None
    return {
        "sample_rate": rate, "seconds": round(x.size / rate, 2), "peak_dbfs": _db(float(np.max(np.abs(x)))),
        "rms_dbfs": _db(float(np.sqrt(np.mean(x ** 2)))), "speech_rms_dbfs": _db(act_rms) if active.size else None,
        "noise_floor_dbfs": _db(floor), "snr_db": snr, "active_fraction": round(float(active.size / n), 2),
        "clipped_fraction": round(float(np.mean(np.abs(x) > 0.99)), 4), "bandwidth_hz": bw,
        "verdict": verdict(snr, _db(float(np.max(np.abs(x)))), bw),
    }


def verdict(snr: float | None, peak: float, bw: int | None) -> str:
    if snr is None:
        return "no speech detected (too quiet, or wrong input)"
    parts = [f"SNR {snr:.0f} dB: " + ("good" if snr >= 25 else "usable for speech recognition" if snr >= 15
                                         else "poor, recognition will struggle")]
    if peak > -1:
        parts.append("clipping")
    if bw:
        parts.append(f"bandwidth ~{bw / 1000:.1f} kHz " + ("(narrowband telephone quality)" if bw < 4500 else
                     "(wideband speech)" if bw < 9000 else "(full band)"))
    return "; ".join(parts)


def record(seconds: float, out_dir: Path, label: str, device: int | None = None) -> dict:
    """Blocking; run in an executor."""
    sd = _sd()
    dev = pick_device(device)
    rate = int(dev["rate"])
    out_dir.mkdir(parents=True, exist_ok=True)
    data = sd.rec(int(seconds * rate), samplerate=rate, channels=1, device=dev["index"], dtype="int16")
    sd.wait()
    pcm = data[:, 0]
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", label)[:40] or "rec"
    import time
    name = f"{time.strftime('%H%M%S')}-{safe}.wav"
    with wave.open(str(out_dir / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return {"file": name, "device": dev["name"], "device_index": dev["index"], "label": label,
            **analyse(pcm.astype(np.float32) / 32768.0, rate)}
