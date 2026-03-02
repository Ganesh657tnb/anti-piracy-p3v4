import os
import sqlite3
import tempfile
import subprocess
import streamlit as st
import numpy as np
import soundfile as sf
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# ------------------ CONFIG ------------------
AES_KEY = b'1234567890abcdef'  # 16 bytes = AES-128
DB_NAME = "users.db"

# ------------------ DATABASE ------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            phone TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------ AES ------------------
def aes_encrypt(data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(AES_KEY), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    padded = data + b' ' * (16 - len(data) % 16)
    return encryptor.update(padded) + encryptor.finalize()

def aes_decrypt(data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(AES_KEY), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()

# ------------------ WATERMARK ------------------
def embed_watermark(audio, user_id):
    binary = format(user_id, '016b')
    watermark = np.array([1 if b == '1' else -1 for b in binary])
    audio[:len(watermark)] += watermark * 0.0005
    return audio

def extract_watermark(audio):
    segment = audio[:16]
    bits = ['1' if x > 0 else '0' for x in segment]
    return int("".join(bits), 2)

# ------------------ FFMPEG ------------------
def extract_audio(video_path, wav_path):
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        wav_path
    ], check=True)

# ------------------ STREAMLIT UI ------------------
st.set_page_config("OTT Watermarking", layout="wide")
st.title("🎬 Inaudible Audio Watermarking for OTT Platforms")

tabs = st.tabs(["🔐 Login", "🎥 Watermark Video", "🕵️ Detect Watermark", "👤 User Info"])

# ------------------ LOGIN ------------------
with tabs[0]:
    st.subheader("Login / Register")

    username = st.text_input("Username", key="login_user")
    password = st.text_input("Password", type="password", key="login_pass")
    phone = st.text_input("Phone", key="login_phone")

    if st.button("Register"):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO users(username,password,phone) VALUES(?,?,?)",
                  (username, password, phone))
        conn.commit()
        conn.close()
        st.success("Registered successfully")

    if st.button("Login"):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=? AND password=?",
                  (username, password))
        row = c.fetchone()
        conn.close()
        if row:
            st.session_state.user_id = row[0]
            st.success(f"Logged in as User ID {row[0]}")
        else:
            st.error("Invalid credentials")

# ------------------ WATERMARK ------------------
with tabs[1]:
    if "user_id" not in st.session_state:
        st.warning("Login first")
    else:
        video = st.file_uploader("Upload Video", type=["mp4", "mkv", "avi", "mov"])
        if video:
            with tempfile.TemporaryDirectory() as tmp:
                vpath = os.path.join(tmp, video.name)
                wav = os.path.join(tmp, "audio.wav")

                with open(vpath, "wb") as f:
                    f.write(video.read())

                extract_audio(vpath, wav)
                audio, sr = sf.read(wav)

                wm_audio = embed_watermark(audio.copy(), st.session_state.user_id)
                out_wav = os.path.join(tmp, "watermarked.wav")
                sf.write(out_wav, wm_audio, sr)

                st.success("Watermark embedded")
                st.audio(out_wav)

# ------------------ DETECT ------------------
with tabs[2]:
    wav = st.file_uploader("Upload Extracted WAV", type=["wav"])
    if wav:
        audio, _ = sf.read(wav)
        uid = extract_watermark(audio)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT username, phone FROM users WHERE id=?", (uid,))
        row = c.fetchone()
        conn.close()

        if row:
            st.success(f"Watermark Owner: {row[0]} | Phone: {row[1]}")
        else:
            st.error("Watermark detected but user not found")

# ------------------ USER INFO ------------------
with tabs[3]:
    conn = sqlite3.connect(DB_NAME)
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    st.table(users)
