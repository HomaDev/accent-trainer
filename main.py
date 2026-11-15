import os
import uuid
import shutil
import subprocess
import base64
import io

import numpy as np
from scipy.io import wavfile
from scipy import signal
from PIL import Image
import imageio_ffmpeg

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_pitch_yin(y: np.ndarray, sr: int, frame_length: int = 2048, hop_length: int = 512):
    min_lag = int(sr / 500.0)
    max_lag = int(sr / 75.0)
    points = []

    for start in range(0, len(y) - frame_length, hop_length):
        t = round((start + frame_length / 2) / sr, 3)
        frame = y[start : start + frame_length]

        if np.sqrt(np.mean(frame ** 2)) < 0.01:
            points.append({"t": t, "hz": None})
            continue

        # Fast autocorrelation via FFT for YIN difference function
        w = frame[: frame_length - max_lag]
        energy_0 = np.sum(w ** 2)
        cum_energy = np.concatenate(([0.0], np.cumsum(frame ** 2)))
        energy_tau = cum_energy[len(w) : len(w) + max_lag + 1] - cum_energy[: max_lag + 1]

        fft_size = 1 << (frame_length * 2 - 1).bit_length()
        r = np.fft.irfft(np.fft.rfft(frame, n=fft_size) * np.conj(np.fft.rfft(w, n=fft_size)))[: max_lag + 1]

        d = energy_0 + energy_tau - 2.0 * r
        d[0] = 0.0
        cmnd = np.ones_like(d)
        running_sum = np.cumsum(d[1:])
        cmnd[1:] = d[1:] * np.arange(1, max_lag + 1) / np.maximum(running_sum, 1e-10)

        search = cmnd[min_lag:max_lag]
        below = np.where(search < 0.15)[0]
        if len(below) > 0:
            idx = below[0]
            while idx + 1 < len(search) and search[idx + 1] < search[idx]:
                idx += 1
            tau = min_lag + idx
        else:
            idx = int(np.argmin(search))
            if search[idx] < 0.35:
                tau = min_lag + idx
            else:
                points.append({"t": t, "hz": None})
                continue

        # Parabolic interpolation for smooth frequency steps
        if 1 <= tau < max_lag:
            denom = 2.0 * (2.0 * cmnd[tau] - cmnd[tau - 1] - cmnd[tau + 1])
            if abs(denom) > 1e-10:
                tau = tau + (cmnd[tau - 1] - cmnd[tau + 1]) / denom

        points.append({"t": t, "hz": round(float(sr / tau), 1)})

    return points


def generate_spectrogram_b64(y: np.ndarray, sr: int) -> str:
    f, _, sxx = signal.spectrogram(y, fs=sr, nperseg=1024, noverlap=768)
    sxx = sxx[f <= 8000]
    sxx_db = 10.0 * np.log10(sxx + 1e-10)

    vmax = float(np.max(sxx_db))
    norm = np.clip((sxx_db - (vmax - 80.0)) / 80.0, 0.0, 1.0)
    norm = np.flipud(norm)

    # Magma-style RGB lookup
    stops = [0.0, 0.33, 0.66, 1.0]
    r = np.interp(norm, stops, [0, 81, 230, 252]).astype(np.uint8)
    g = np.interp(norm, stops, [0, 18, 81, 253]).astype(np.uint8)
    b = np.interp(norm, stops, [4, 124, 100, 191]).astype(np.uint8)

    img = Image.fromarray(np.stack([r, g, b], axis=-1), mode="RGB")
    img = img.resize((1000, 300), Image.Resampling.BILINEAR)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def extract_audio_data(file_path: str):
    sr, y = wavfile.read(file_path)
    if y.ndim > 1:
        y = y.mean(axis=1)
    y = y.astype(np.float32) / 32768.0

    return {
        "contour": extract_pitch_yin(y, sr),
        "spectrogram": generate_spectrogram_b64(y, sr),
    }


@app.post("/analyze")
async def analyze_audio(file: UploadFile = File(...)):
    req_id = uuid.uuid4().hex
    temp_in = f"/tmp/in_{req_id}"
    temp_wav = f"/tmp/out_{req_id}.wav"

    with open(temp_in, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", temp_in, "-ac", "1", "-ar", "22050", temp_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        data = extract_audio_data(temp_wav)
    finally:
        if os.path.exists(temp_in):
            os.remove(temp_in)
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    return data


os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")