import os
import sqlite3
import tempfile
import subprocess
import numpy as np
import wave
import bcrypt
import streamlit as st
import pandas as pd
import hmac
import hashlib

# ---------------- CONFIG ----------------
DB_NAME = "guardian.db"
UPLOAD_DIR = "master_videos"
HMAC_KEY = b"guardian_secret_key"

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT,
            phone TEXT,
            password TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            uploader_id INTEGER
        )
    """)
    conn.commit()
    conn.close()

# ---------------- DSSS + HMAC ----------------
def generate_pn_sequence(n):
    np.random.seed(42)
    return (np.random.randint(0, 2, n) * 2 - 1).astype(np.float64)

def derive_watermark_bits(user_id: int):
    digest = hmac.new(
        HMAC_KEY,
        str(user_id).encode(),
        hashlib.sha256
    ).digest()

    truncated = digest[:16]  # 128 bits
    bits = []
    for b in truncated:
        bits.extend([int(x) for x in format(b, "08b")])
    return bits

def embed_watermark(input_wav, output_wav, user_id):
    with wave.open(input_wav, "rb") as wav:
        params = wav.getparams()
        samples = np.frombuffer(
            wav.readframes(params.nframes),
            dtype=np.int16
        ).astype(np.float64)

    bits = [1] + derive_watermark_bits(user_id)
    total_samples = len(samples)
    sf = total_samples // len(bits)
    pn = generate_pn_sequence(total_samples)

    watermark = np.zeros(total_samples)
    for i, bit in enumerate(bits):
        val = 1 if bit else -1
        watermark[i*sf:(i+1)*sf] = val * pn[i*sf:(i+1)*sf]

    result = np.clip(
        samples + 0.015 * watermark * np.max(np.abs(samples)),
        -32768, 32767
    ).astype(np.int16)

    with wave.open(output_wav, "wb") as out:
        out.setparams(params)
        out.writeframes(result.tobytes())

# ---------------- STREAMLIT APP ----------------
def main():
    st.set_page_config("Anti-Piracy Portal", layout="wide")
    init_db()

    if "uid" not in st.session_state:
        st.session_state.uid = None

    # ---------- LOGIN / REGISTER ----------
    if st.session_state.uid is None:
        col1, col2 = st.columns(2)

        # LOGIN
        with col1:
            st.subheader("🔐 Login")
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")

            if st.button("Login", key="login_btn"):
                conn = sqlite3.connect(DB_NAME)
                row = conn.execute(
                    "SELECT id, password FROM users WHERE username=?",
                    (username,)
                ).fetchone()
                conn.close()

                if row and bcrypt.checkpw(password.encode(), row[1]):
                    st.session_state.uid = row[0]
                    st.rerun()
                else:
                    st.error("Invalid credentials")

        # REGISTER
        with col2:
            st.subheader("🆕 Register")
            r_user = st.text_input("New Username", key="reg_user")
            r_email = st.text_input("Email", key="reg_email")
            r_phone = st.text_input("Phone", key="reg_phone")
            r_pass = st.text_input("Password", type="password", key="reg_pass")

            if st.button("Register", key="reg_btn"):
                if not all([r_user, r_email, r_phone, r_pass]):
                    st.error("All fields required")
                else:
                    try:
                        h = bcrypt.hashpw(r_pass.encode(), bcrypt.gensalt())
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute(
                            "INSERT INTO users (username,email,phone,password) VALUES (?,?,?,?)",
                            (r_user, r_email, r_phone, h)
                        )
                        conn.commit()
                        conn.close()
                        st.success("Registration successful")
                    except sqlite3.IntegrityError:
                        st.error("Username already exists")

        st.stop()

    # ---------- LOGGED IN ----------
    st.sidebar.success(f"Logged in as User ID {st.session_state.uid}")
    if st.sidebar.button("Logout", key="logout"):
        st.session_state.uid = None
        st.rerun()

    tab1, tab2, tab3 = st.tabs(
        ["📚 Library", "📤 Upload", "🔍 Detector"]
    )

    # ---------- TAB 1 ----------
    with tab1:
        st.header("Available Videos")
        conn = sqlite3.connect(DB_NAME)
        videos = conn.execute("SELECT filename FROM videos").fetchall()
        conn.close()

        for (fname,) in videos:
            st.write(f"🎬 **{fname}**")
            if st.button("Download Watermarked", key=f"dl_{fname}"):
                with tempfile.TemporaryDirectory() as tmp:
                    in_v = os.path.join(UPLOAD_DIR, fname)
                    in_a = os.path.join(tmp, "in.wav")
                    out_a = os.path.join(tmp, "out.wav")
                    out_v = os.path.join(tmp, "protected.mp4")

                    subprocess.run(
                        ["ffmpeg", "-y", "-i", in_v, "-vn", "-acodec", "pcm_s16le", in_a],
                        check=True
                    )
                    embed_watermark(in_a, out_a, st.session_state.uid)
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", in_v, "-i", out_a,
                         "-map", "0:v:0", "-map", "1:a:0",
                         "-c:v", "copy", "-c:a", "aac", out_v],
                        check=True
                    )

                    with open(out_v, "rb") as f:
                        st.download_button(
                            "Download File",
                            f.read(),
                            file_name=f"protected_{fname}",
                            key=f"save_{fname}"
                        )

    # ---------- TAB 2 ----------
    with tab2:
        st.header("Upload Master Video")
        up = st.file_uploader("Select video", type=["mp4", "mkv", "mov"], key="upload_vid")
        if up and st.button("Upload", key="upload_btn"):
            path = os.path.join(UPLOAD_DIR, up.name)
            with open(path, "wb") as f:
                f.write(up.read())

            conn = sqlite3.connect(DB_NAME)
            conn.execute(
                "INSERT INTO videos (filename, uploader_id) VALUES (?,?)",
                (up.name, st.session_state.uid)
            )
            conn.commit()
            conn.close()
            st.success("Uploaded successfully")

    # ---------- TAB 3 ----------
    with tab3:
        st.info("Forensic detection handled by separate detector app.")

if __name__ == "__main__":
    main()
