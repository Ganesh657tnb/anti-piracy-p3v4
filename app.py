import os
import sqlite3
import tempfile
import subprocess
import streamlit as st
import numpy as np
import wave
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from Crypto.Random import get_random_bytes

# ---------------- CONFIG ----------------

DB_PATH = "watermark.db"
AES_KEY = b"this_is_16_bytes"   # 16 bytes = AES-128
AES_IV  = b"this_is_16_bytes"   # 16 bytes IV (demo purpose)
PN_SEED = 42

# ---------------------------------------

st.set_page_config(page_title="AES DSSS Watermarking", layout="wide")
st.title("🔐 AES-128 DSSS Watermarking WebApp")

# ---------- DATABASE ----------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            email TEXT,
            aes_cipher BLOB
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- AES ENCRYPTION ----------

def aes_encrypt_user_id(user_id: int) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    plaintext = str(user_id).encode()
    ciphertext = cipher.encrypt(pad(plaintext, 16))
    return ciphertext   # 128-bit aligned

def bytes_to_bits(data: bytes):
    bits = []
    for byte in data:
        for i in range(8):
            bits.append((byte >> (7 - i)) & 1)
    return bits

# ---------- DSSS ----------

def generate_pn_sequence(length):
    np.random.seed(PN_SEED)
    return (np.random.randint(0, 2, length) * 2 - 1).astype(np.float64)

def embed_dsss(audio_samples, bits):
    samples = audio_samples.astype(np.float64)
    pn = generate_pn_sequence(len(samples))

    bit_len = len(samples) // len(bits)
    alpha = 0.01  # watermark strength

    for i, bit in enumerate(bits):
        start = i * bit_len
        end = start + bit_len
        if end > len(samples):
            break
        samples[start:end] += alpha * pn[start:end] * (1 if bit else -1)

    return np.clip(samples, -32768, 32767).astype(np.int16)

# ---------- FFMPEG ----------

def extract_audio(video_path, wav_path):
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", wav_path
    ], check=True)

def merge_audio(video_path, audio_path, out_path):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-shortest",
        out_path
    ], check=True)

# ---------- UI ----------

tab1, tab2 = st.tabs(["🎬 Watermark Video", "👥 Users"])

with tab1:
    username = st.text_input("Username", key="uname")
    email = st.text_input("Email", key="email")
    video = st.file_uploader("Upload Video", type=["mp4", "mkv", "avi"])

    if st.button("Encrypt & Watermark"):
        if not (username and email and video):
            st.error("Fill all fields")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                in_video = os.path.join(tmp, video.name)
                with open(in_video, "wb") as f:
                    f.write(video.read())

                audio_wav = os.path.join(tmp, "audio.wav")
                extract_audio(in_video, audio_wav)

                with wave.open(audio_wav, "rb") as w:
                    params = w.getparams()
                    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

                # DB insert
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username,email) VALUES (?,?)",
                            (username, email))
                user_id = cur.lastrowid

                cipher = aes_encrypt_user_id(user_id)
                cur.execute("UPDATE users SET aes_cipher=? WHERE user_id=?",
                            (cipher, user_id))
                conn.commit()
                conn.close()

                bits = bytes_to_bits(cipher)
                watermarked_audio = embed_dsss(audio, bits)

                out_audio = os.path.join(tmp, "wm_audio.wav")
                with wave.open(out_audio, "wb") as w:
                    w.setparams(params)
                    w.writeframes(watermarked_audio.tobytes())

                out_video = os.path.join(tmp, "watermarked.mp4")
                merge_audio(in_video, out_audio, out_video)

                with open(out_video, "rb") as f:
                    st.success("✅ Watermarking Complete")
                    st.download_button(
                        "Download Watermarked Video",
                        f,
                        file_name="watermarked.mp4"
                    )

with tab2:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email FROM users")
    rows = cur.fetchall()
    conn.close()

    st.subheader("Registered Users")
    st.table(rows)
