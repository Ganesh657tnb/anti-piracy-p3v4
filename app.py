import streamlit as st
import sqlite3
import hashlib
import numpy as np
import subprocess
import tempfile
import os
import soundfile as sf

# -------------------- DATABASE --------------------
conn = sqlite3.connect("users.db", check_same_thread=False)
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

# -------------------- HELPERS --------------------
def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def extract_audio(video_path, out_wav):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn", "-ac", "1",
        "-ar", "44100",
        out_wav
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def embed_watermark(audio, watermark):
    audio = audio.copy()
    for i in range(0, len(watermark)*100, 100):
        idx = i % len(audio)
        audio[idx] += 0.0005 if watermark[i//100] == "1" else -0.0005
    return audio

def extract_watermark(audio, length):
    bits = []
    for i in range(0, length*100, 100):
        idx = i % len(audio)
        bits.append("1" if audio[idx] > 0 else "0")
    return "".join(bits)

# -------------------- SESSION --------------------
if "user" not in st.session_state:
    st.session_state.user = None

# -------------------- AUTH --------------------
st.title("🎧 Inaudible Audio Watermarking – OTT Anti-Piracy")

if st.session_state.user is None:
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username", key="lu")
        p = st.text_input("Password", type="password", key="lp")

        if st.button("Login"):
            c.execute("SELECT * FROM users WHERE username=? AND password=?",
                      (u, hash_password(p)))
            r = c.fetchone()
            if r:
                st.session_state.user = r
                st.rerun()
            else:
                st.error("Invalid login")

    with tab2:
        ru = st.text_input("Username", key="ru")
        rp = st.text_input("Password", type="password", key="rp")
        ph = st.text_input("Phone", key="ph")

        if st.button("Register"):
            try:
                c.execute("INSERT INTO users (username,password,phone) VALUES (?,?,?)",
                          (ru, hash_password(rp), ph))
                conn.commit()
                st.success("Registered! Login now.")
            except:
                st.error("Username already exists")

# -------------------- MAIN APP --------------------
else:
    user = st.session_state.user
    uid = user[0]

    tabs = st.tabs(["Watermark Video", "Detect Watermark", "User Info", "Logout"])

    # -------- WATERMARK --------
    with tabs[0]:
        st.header("Embed Watermark")
        vid = st.file_uploader("Upload Video", type=["mp4","mkv","avi"])

        if vid:
            with tempfile.TemporaryDirectory() as tmp:
                vpath = os.path.join(tmp, "v.mp4")
                wpath = os.path.join(tmp, "a.wav")

                with open(vpath, "wb") as f:
                    f.write(vid.read())

                extract_audio(vpath, wpath)
                audio, sr = sf.read(wpath)

                wm = format(uid, "016b") * 5   # repetition = trim resistant
                wm_audio = embed_watermark(audio, wm)

                out = os.path.join(tmp, "watermarked.wav")
                sf.write(out, wm_audio, sr)

                st.audio(out)
                st.success("Watermark embedded (User ID linked)")
                st.download_button("Download Watermarked Audio",
                                   open(out,"rb"), "watermarked.wav")

    # -------- DETECT --------
    with tabs[1]:
        st.header("Detect Watermark")
        aud = st.file_uploader("Upload Watermarked WAV", type=["wav"])

        if aud:
            audio, sr = sf.read(aud)
            bits = extract_watermark(audio, 16)
            detected_id = int(bits[:16], 2)

            c.execute("SELECT username, phone FROM users WHERE id=?",
                      (detected_id,))
            r = c.fetchone()

            if r:
                st.success("Watermark detected")
                st.write("User ID:", detected_id)
                st.write("Username:", r[0])
                st.write("Phone:", r[1])
            else:
                st.error("Invalid / corrupted watermark")

    # -------- USER INFO --------
    with tabs[2]:
        st.header("My Info")
        st.write("User ID:", user[0])
        st.write("Username:", user[1])
        st.write("Phone:", user[3])

    # -------- LOGOUT --------
    with tabs[3]:
        if st.button("Logout"):
            st.session_state.user = None
            st.rerun()
