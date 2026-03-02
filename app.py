import os
import sqlite3
import tempfile
import subprocess
import streamlit as st
import numpy as np
import wave
import bcrypt
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ---------------- CONFIG ----------------
DB_PATH = "watermark.db"
AES_KEY = b"this_is_16_bytes"
AES_IV  = b"this_is_16_bytes"
PN_SEED = 42
# --------------------------------------

st.set_page_config(page_title="AES DSSS Watermarking", layout="wide")

# ---------- DATABASE ----------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT,
            password BLOB,
            aes_cipher BLOB
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- AES ----------

def aes_encrypt_user_id(user_id: int) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(str(user_id).encode(), 16))

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

def embed_dsss(audio, bits):
    audio = audio.astype(np.float64)
    pn = generate_pn_sequence(len(audio))
    sf = len(audio) // len(bits)
    alpha = 0.01

    for i, bit in enumerate(bits):
        start = i * sf
        end = start + sf
        if end > len(audio):
            break
        audio[start:end] += alpha * pn[start:end] * (1 if bit else -1)

    return np.clip(audio, -32768, 32767).astype(np.int16)

# ---------- FFMPEG ----------

def extract_audio(video, wav):
    subprocess.run([
        "ffmpeg", "-y", "-i", video,
        "-vn", "-acodec", "pcm_s16le", wav
    ], check=True)

def merge_audio(video, audio, out):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video,
        "-i", audio,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-shortest", out
    ], check=True)

# ---------- AUTH ----------

if "user_id" not in st.session_state:
    st.session_state.user_id = None

# ---------- LOGIN / REGISTER ----------

if st.session_state.user_id is None:
    st.title("🔐 Login / Register")

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username", key="login_u")
        p = st.text_input("Password", type="password", key="login_p")

        if st.button("Login"):
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT user_id, password FROM users WHERE username=?", (u,))
            row = cur.fetchone()
            conn.close()

            if row and bcrypt.checkpw(p.encode(), row[1]):
                st.session_state.user_id = row[0]
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tab2:
        ru = st.text_input("Username", key="reg_u")
        re = st.text_input("Email", key="reg_e")
        rp = st.text_input("Password", type="password", key="reg_p")

        if st.button("Register"):
            if not (ru and re and rp):
                st.error("All fields required")
            else:
                hp = bcrypt.hashpw(rp.encode(), bcrypt.gensalt())
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO users (username,email,password) VALUES (?,?,?)",
                        (ru, re, hp)
                    )
                    conn.commit()
                    conn.close()
                    st.success("Registration successful! Login now.")
                except sqlite3.IntegrityError:
                    st.error("Username already exists")

    st.stop()

# ---------- DASHBOARD ----------

st.sidebar.success(f"Logged in as User ID {st.session_state.user_id}")
if st.sidebar.button("Logout"):
    st.session_state.user_id = None
    st.rerun()

tab1, tab2 = st.tabs(["🎬 Watermark Video", "👥 Users"])

# ---------- WATERMARK ----------

with tab1:
    st.header("Encrypt & Watermark Video")
    video = st.file_uploader("Upload Video", type=["mp4", "mkv", "avi"])

    if st.button("Watermark"):
        if not video:
            st.error("Upload a video")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                in_v = os.path.join(tmp, video.name)
                with open(in_v, "wb") as f:
                    f.write(video.read())

                audio = os.path.join(tmp, "audio.wav")
                extract_audio(in_v, audio)

                with wave.open(audio, "rb") as w:
                    params = w.getparams()
                    samples = np.frombuffer(
                        w.readframes(w.getnframes()), dtype=np.int16
                    )

                cipher = aes_encrypt_user_id(st.session_state.user_id)

                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE users SET aes_cipher=? WHERE user_id=?",
                    (cipher, st.session_state.user_id)
                )
                conn.commit()
                conn.close()

                bits = bytes_to_bits(cipher)
                wm_audio = embed_dsss(samples, bits)

                out_audio = os.path.join(tmp, "wm.wav")
                with wave.open(out_audio, "wb") as w:
                    w.setparams(params)
                    w.writeframes(wm_audio.tobytes())

                out_v = os.path.join(tmp, "watermarked.mp4")
                merge_audio(in_v, out_audio, out_v)

                with open(out_v, "rb") as f:
                    st.success("✅ Watermark Embedded")
                    st.download_button("Download Video", f, "watermarked.mp4")

# ---------- USERS TAB ----------

with tab2:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT user_id, username, email FROM users"
    ).fetchall()
    conn.close()

    st.subheader("Registered Users")
    st.table(rows)
