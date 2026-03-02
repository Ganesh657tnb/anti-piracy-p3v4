import streamlit as st
import sqlite3
import hashlib
import os
import tempfile
import subprocess
import numpy as np
from scipy.io import wavfile

# ---------------- DB SETUP ----------------
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            phone TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------- AUTH UTILS ----------------
def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def register_user(username, password, phone):
    try:
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (username, password, phone) VALUES (?, ?, ?)",
            (username, hash_password(password), phone)
        )
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute(
        "SELECT id FROM users WHERE username=? AND password=?",
        (username, hash_password(password))
    )
    user = c.fetchone()
    conn.close()
    return user[0] if user else None

def get_user(user_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT username, phone FROM users WHERE id=?", (user_id,))
    data = c.fetchone()
    conn.close()
    return data

# ---------------- AUDIO UTILS ----------------
def extract_audio(video_path, wav_path):
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100",
        wav_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def merge_audio(video_path, audio_path, out_path):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        out_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ---------------- WATERMARK CORE ----------------
def embed_watermark(audio, user_id):
    bits = format(user_id, "016b")
    positions = [int(len(audio) * p) for p in [0.1, 0.3, 0.5, 0.7, 0.9]]
    audio = audio.copy()

    for pos in positions:
        for i, bit in enumerate(bits):
            audio[pos + i] = (audio[pos + i] & ~1) | int(bit)
    return audio

def extract_watermark(audio):
    positions = [int(len(audio) * p) for p in [0.1, 0.3, 0.5, 0.7, 0.9]]
    collected = []

    for pos in positions:
        bits = [str(audio[pos + i] & 1) for i in range(16)]
        collected.append(bits)

    final_bits = []
    for i in range(16):
        ones = sum(1 for c in collected if c[i] == "1")
        final_bits.append("1" if ones >= 3 else "0")

    return int("".join(final_bits), 2)

# ---------------- STREAMLIT STATE ----------------
if "user_id" not in st.session_state:
    st.session_state.user_id = None

st.set_page_config("OTT Anti-Piracy System", layout="wide")
st.title("🎬 OTT Inaudible Audio Watermarking System")

# ---------------- AUTH PAGES ----------------
if st.session_state.user_id is None:
    tabs = st.tabs(["🔐 Login", "📝 Register"])

    with tabs[0]:
        u = st.text_input("Username", key="login_u")
        p = st.text_input("Password", type="password", key="login_p")
        if st.button("Login"):
            uid = login_user(u, p)
            if uid:
                st.session_state.user_id = uid
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tabs[1]:
        u = st.text_input("Username", key="reg_u")
        p = st.text_input("Password", type="password", key="reg_p")
        ph = st.text_input("Phone Number", key="reg_ph")
        if st.button("Register"):
            if register_user(u, p, ph):
                st.success("Registered successfully. Please login.")
            else:
                st.error("Username already exists")

# ---------------- MAIN APP ----------------
else:
    tabs = st.tabs(["👤 User Info", "🔐 Embed Watermark", "🔍 Detect Watermark", "🚪 Logout"])

    # ---- USER INFO ----
    with tabs[0]:
        username, phone = get_user(st.session_state.user_id)
        st.subheader("User Information")
        st.write(f"**User ID:** {st.session_state.user_id}")
        st.write(f"**Username:** {username}")
        st.write(f"**Phone:** {phone}")

    # ---- EMBED ----
    with tabs[1]:
        video = st.file_uploader("Upload Video", type=["mp4", "mkv", "avi"])
        if st.button("Embed Watermark"):
            if not video:
                st.warning("Upload a video")
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    vp = os.path.join(tmp, video.name)
                    with open(vp, "wb") as f:
                        f.write(video.read())

                    wav = os.path.join(tmp, "a.wav")
                    out_wav = os.path.join(tmp, "wm.wav")
                    out_vid = os.path.join(tmp, "wm.mp4")

                    extract_audio(vp, wav)
                    rate, audio = wavfile.read(wav)
                    if audio.ndim > 1:
                        audio = audio[:, 0]

                    wm = embed_watermark(audio, st.session_state.user_id)
                    wavfile.write(out_wav, rate, wm.astype(np.int16))
                    merge_audio(vp, out_wav, out_vid)

                    st.success("Watermark embedded")
                    with open(out_vid, "rb") as f:
                        st.download_button("Download Video", f, "watermarked.mp4")

    # ---- DETECT ----
    with tabs[2]:
        video = st.file_uploader("Upload Video", type=["mp4", "mkv", "avi"], key="det")
        if st.button("Detect"):
            with tempfile.TemporaryDirectory() as tmp:
                vp = os.path.join(tmp, video.name)
                with open(vp, "wb") as f:
                    f.write(video.read())

                wav = os.path.join(tmp, "a.wav")
                extract_audio(vp, wav)
                rate, audio = wavfile.read(wav)
                if audio.ndim > 1:
                    audio = audio[:, 0]

                uid = extract_watermark(audio)
                st.success(f"Extracted User ID: {uid}")

    # ---- LOGOUT ----
    with tabs[3]:
        if st.button("Logout"):
            st.session_state.user_id = None
            st.rerun()
