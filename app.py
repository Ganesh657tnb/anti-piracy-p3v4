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

# --- 1. SETUP & DIRECTORIES ---
DB_NAME = "guardian.db"
UPLOAD_DIR = "master_videos"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 🔐 HMAC secret key (KEEP SECRET)
HMAC_KEY = b"guardian_secret_key"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT UNIQUE, 
                  email TEXT, 
                  phone TEXT, 
                  password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  filename TEXT, 
                  uploader_id INTEGER)''')
    conn.commit()
    conn.close()

# --- 2. DSSS CORE LOGIC ---

def generate_pn_sequence(duration_samples):
    np.random.seed(42)  # fixed seed for detector consistency
    return (np.random.randint(0, 2, duration_samples) * 2 - 1).astype(np.float64)

# 🔐 HMAC-SHA256 → 128-bit watermark
def derive_watermark_bits(user_id: int):
    digest = hmac.new(
        HMAC_KEY,
        str(user_id).encode(),
        hashlib.sha256
    ).digest()

    truncated = digest[:16]  # 128 bits

    bits = []
    for byte in truncated:
        bits.extend([int(b) for b in format(byte, '08b')])

    return bits

def embed_watermark(input_wav, output_wav, user_id):
    with wave.open(input_wav, 'rb') as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)
        audio_samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)

    # 🔐 Generate secure watermark bits
    wm_bits = derive_watermark_bits(user_id)

    # Sync bit + watermark bits
    bits = [1] + wm_bits

    total_samples = len(audio_samples)
    sf = total_samples // len(bits)
    pn = generate_pn_sequence(total_samples)

    watermark = np.zeros(total_samples)
    for i, bit in enumerate(bits):
        val = 1 if bit == 1 else -1
        watermark[i * sf:(i + 1) * sf] = val * pn[i * sf:(i + 1) * sf]

    result = np.clip(
        audio_samples + (0.015 * watermark * np.max(np.abs(audio_samples))),
        -32768, 32767
    ).astype(np.int16)

    with wave.open(output_wav, 'wb') as out:
        out.setparams(params)
        out.writeframes(result.tobytes())

# --- 3. UI HELPERS ---
def run_ffmpeg(cmd):
    subprocess.run(cmd, check=True, capture_output=True)

# --- 4. MAIN APP ---
def main():
    st.set_page_config(page_title="Anti-Piracy Portal", layout="wide")
    init_db()

    if 'uid' not in st.session_state:
        st.session_state.uid = None

    # --- LOGIN / REGISTER ---
    if st.session_state.uid is None:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Login")
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.button("Login"):
                conn = sqlite3.connect(DB_NAME)
                res = conn.execute(
                    "SELECT id, password FROM users WHERE username=?", (u,)
                ).fetchone()
                conn.close()
                if res and bcrypt.checkpw(p.encode(), res[1]):
                    st.session_state.uid = res[0]
                    st.rerun()
                else:
                    st.error("Invalid Credentials")

        with col2:
            st.subheader("Create New Account")
            nu = st.text_input("New Username")
            nem = st.text_input("Email")
            nph = st.text_input("Phone")
            npw = st.text_input("Password", type="password")

            if st.button("Register"):
                if not (nu and nem and nph and npw):
                    st.error("All fields are mandatory!")
                else:
                    h = bcrypt.hashpw(npw.encode(), bcrypt.gensalt())
                    try:
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute(
                            "INSERT INTO users (username, email, phone, password) VALUES (?,?,?,?)",
                            (nu, nem, nph, h)
                        )
                        conn.commit()
                        st.success("Registration successful!")
                    except sqlite3.IntegrityError:
                        st.error("Username already exists.")
                    finally:
                        conn.close()
        st.stop()

    # --- LOGGED IN ---
    st.sidebar.title(f"Logged in as User ID: {st.session_state.uid}")
    if st.sidebar.button("Logout"):
        st.session_state.uid = None
        st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📚 Shared Library", "📤 Upload Content", "🔍 Forensic Detector", "👥 Database Admin"]
    )

    # --- TAB 1 ---
    with tab1:
        st.header("Available Content")
        conn = sqlite3.connect(DB_NAME)
        vids = conn.execute("SELECT filename FROM videos").fetchall()
        conn.close()

        for (fname,) in vids:
            st.write(f"🎬 **{fname}**")
            if st.button("Download Watermarked Copy", key=fname):
                with tempfile.TemporaryDirectory() as tmp:
                    in_v = os.path.join(UPLOAD_DIR, fname)
                    in_a = os.path.join(tmp, "in.wav")
                    out_a = os.path.join(tmp, "out.wav")
                    out_v = os.path.join(tmp, "protected.mp4")

                    run_ffmpeg(["ffmpeg", "-y", "-i", in_v, "-vn", "-acodec", "pcm_s16le", in_a])
                    embed_watermark(in_a, out_a, st.session_state.uid)
                    run_ffmpeg([
                        "ffmpeg", "-y",
                        "-i", in_v, "-i", out_a,
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac",
                        out_v
                    ])

                    with open(out_v, "rb") as f:
                        st.download_button("Download", f.read(), file_name=f"protected_{fname}")

    # --- TAB 2 ---
    with tab2:
        st.header("Upload Master Content")
        up_file = st.file_uploader("Select Video", type=['mp4', 'mkv', 'mov'])
        if up_file and st.button("Confirm Upload"):
            path = os.path.join(UPLOAD_DIR, up_file.name)
            with open(path, "wb") as f:
                f.write(up_file.read())
            conn = sqlite3.connect(DB_NAME)
            conn.execute(
                "INSERT INTO videos (filename, uploader_id) VALUES (?,?)",
                (up_file.name, st.session_state.uid)
            )
            conn.commit()
            conn.close()
            st.success("Upload successful!")

    # --- TAB 3 ---
    with tab3:
        st.header("Forensic Detector")
        st.info("Watermark extraction module can be added here.")

    # --- TAB 4 ---
    with tab4:
        st.header("User Management")
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT id, username, email, phone FROM users", conn)
        conn.close()
        st.dataframe(df, use_container_width=True)

if __name__ == "__main__":
    main()
