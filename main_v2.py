import os
import json
import shutil
import subprocess
import base64
import io

import librosa
import librosa.display
import numpy as np

import matplotlib

matplotlib.use('Agg')  # Headless mode for servers
import matplotlib.pyplot as plt

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


def extract_audio_data(file_path: str):
    y, sr = librosa.load(file_path, sr=None)

    # 1. Extract Pitch (f0)
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=75.0, fmax=500.0, sr=sr, frame_length=2048
    )
    times = librosa.times_like(f0, sr=sr)

    points = []
    for t, f, is_voiced in zip(times, f0, voiced_flag):
        points.append({
            "t": round(float(t), 3),
            "hz": round(float(f), 1) if (is_voiced and not np.isnan(f)) else None
        })

    # 2. Generate Spectrogram
    fig, ax = plt.subplots(figsize=(10, 3), dpi=100)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)  # Remove margins

    D = librosa.amplitude_to_db(np.abs(librosa.stft(y)), ref=np.max)
    librosa.display.specshow(D, sr=sr, x_axis='time', y_axis='linear', ax=ax, cmap='magma')
    ax.set_ylim(0, 8000)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
    buf.seek(0)
    spec_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)

    return {
        "contour": points,
        "spectrogram": "data:image/png;base64," + spec_b64
    }


@app.post("/analyze")
async def analyze_audio(file: UploadFile = File(...)):
    temp_in = f"/tmp/in_{file.filename}"
    temp_wav = f"/tmp/out_{file.filename}.wav"

    with open(temp_in, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", temp_in, "-acodec", "pcm_s16le", "-ar", "44100", temp_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        data = extract_audio_data(temp_wav)
    finally:
        if os.path.exists(temp_in):
            os.remove(temp_in)
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    return data


@app.get("/analyze_native")
async def analyze_native_audio(filename: str):
    file_path = os.path.join("static", "native_audio", filename)
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    return extract_audio_data(file_path)


@app.get("/api/sentences")
def get_available_sentences():
    db_path = os.path.join("static", "sentences.json")
    if not os.path.exists(db_path):
        return []

    with open(db_path, "r", encoding="utf-8") as f:
        sentences = json.load(f)

    available = []
    for s in sentences:
        audio_path = os.path.join("static", s["audio_file"])
        if os.path.exists(audio_path):
            available.append(s)

    return available


os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")