import base64
import io
import matplotlib
matplotlib.use('Agg') # Required for headless server environments
import matplotlib.pyplot as plt
import librosa.display
import librosa
import numpy as np
import json # <-- Add this line
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import subprocess
import shutil
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_pitch_curve(file_path: str):
    # Load audio; sr=None preserves original sample rate
    y, sr = librosa.load(file_path, sr=None)

    # pYIN algorithm optimized for human speech (75Hz - 500Hz)
    # Returns fundamental frequency (f0), voiced flag, and probabilities
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y,
        fmin=75.0,
        fmax=500.0,
        sr=sr,
        frame_length=2048
    )

    # Generate time stamps for each frame
    times = librosa.times_like(f0, sr=sr)

    # Build the JSON response, filtering out unvoiced frames (silence/noise)
    points = []
    for t, f, is_voiced in zip(times, f0, voiced_flag):
        points.append({
            "t": round(float(t), 3),
            "hz": round(float(f), 1) if (is_voiced and not np.isnan(f)) else None
        })

    return points


@app.post("/analyze")
async def analyze_audio(file: UploadFile = File(...)):
    # Save the incoming file from the browser (which is actually WebM)
    temp_in = f"/tmp/in_{file.filename}"
    temp_wav = f"/tmp/out_{file.filename}.wav"

    with open(temp_in, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Force conversion to a true 16-bit PCM WAV file using ffmpeg
        subprocess.run(
            ["ffmpeg", "-y", "-i", temp_in, "-acodec", "pcm_s16le", "-ar", "44100", temp_wav],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Analyze the converted WAV file with Librosa
        contour = extract_pitch_curve(temp_wav)

    finally:
        # Clean up both temporary files
        if os.path.exists(temp_in):
            os.remove(temp_in)
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    return {"contour": contour}


@app.get("/analyze_native")
async def analyze_native_audio(filename: str):
    # Construct the path to the downloaded Bunpro audio
    file_path = os.path.join("static", "native_audio", filename)

    if not os.path.exists(file_path):
        return {"error": "File not found"}

    # Extract pitch contour directly from the MP3
    contour = extract_pitch_curve(file_path)
    return {"contour": contour}


@app.get("/api/sentences")
def get_available_sentences():
    db_path = os.path.join("static", "sentences.json")
    if not os.path.exists(db_path):
        return []

    with open(db_path, "r", encoding="utf-8") as f:
        sentences = json.load(f)

    # Only return sentences where the MP3 physically exists on your hard drive
    available = []
    for s in sentences:
        audio_path = os.path.join("static", s["audio_file"])
        if os.path.exists(audio_path):
            available.append(s)

    return available


# Serve the static frontend
os.makedirs("static", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")