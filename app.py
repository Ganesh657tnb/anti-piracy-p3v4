import os
import sqlite3
import streamlit as st
import tempfile
import subprocess
import numpy as np
from scipy.io import wavfile

# ---------------- CONFIG ----------------
st.set_page_config("OTT Audio Watermarking", layout="wide")
DB = "users.db"
VIDEO_DIR = "storage/videos"
os.makedirs(VIDEO_DIR, exist_ok=True)

# ---------------- DATABASE ----------------
conn = sqlite3.connect(DB, check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    phone TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS videos(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    path TEXT,
    uploaded_by INTEGER
)
""")
conn.commit()

# ---------------- AUTH ----------------
def register(username, password, phone):
    try:
        c.execute(
            "INSERT INTO users(username,password,phone) VALUES (?,?,?)",
            (username, password, phone)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def login(username, password):
    c.execute(
        "SELECT id FROM users WHERE username=? AND password=?",
        (username, password)
    )
    row = c.fetchone()
    return row[0] if row else None

# ---------------- WATERMARK CORE ----------------
def embed_watermark(samples, user_id):
    bits = np.array(list(np.binary_repr(user_id, width=16)), dtype=int)
    bits = bits * 2 - 1

    samples = samples.astype(np.float32)
    chunk = len(samples) // len(bits)

    for i, b in enumerate(bits):
        samples[i*chunk:(i+1)*chunk] += b * 0.5

    return samples.astype(np.int16)

def extract_watermark(samples):
    samples = samples.astype(np.float32)
    bits = []
    chunk = len(samples) // 16

    for i in range(16):
        seg = samples[i*chunk:(i+1)*chunk]
        bits.append(1 if np.mean(seg) > 0 else 0)

    return int("".join(map(str, bits)), 2)

# ---------------- FFMPEG ----------------
def extract_audio(video, wav):
    subprocess.run([
        "ffmpeg", "-y", "-i", video,
        "-vn", "-acodec", "pcm_s16le", wav
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def merge_audio(video, wav, out):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video, "-i", wav,
        "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0",
        out
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ---------------- SESSION ----------------
if "user" not in st.session_state:
    st.session_state.user = None

# ---------------- LOGIN / REGISTER ----------------
if not st.session_state.user:
    st.title("🔐 Login / Register")

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Login"):
            uid = login(u, p)
            if uid:
                st.session_state.user = uid
                st.success("Login success")
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tab2:
        u = st.text_input("New Username")
        p = st.text_input("New Password", type="password")
        ph = st.text_input("Phone")
        if st.button("Register"):
            if register(u, p, ph):
                st.success("Registered! Login now.")
            else:
                st.error("Username already exists")

    st.stop()

# ---------------- MAIN APP ----------------
uid = st.session_state.user
tabs = st.tabs([
    "🎧 Watermark Video",
    "🔍 Detect Watermark",
    "📂 All Watermarked Videos",
    "👥 Users",
    "🚪 Logout"
])

# -------- WATERMARK --------
with tabs[0]:
    st.header("Watermark Video")
    vid = st.file_uploader("Upload Video", type=["mp4", "mkv", "avi"])

    if vid and st.button("Apply Watermark"):
        with tempfile.TemporaryDirectory() as tmp:
            in_vid = os.path.join(tmp, vid.name)
            wav = os.path.join(tmp, "a.wav")
            wm_wav = os.path.join(tmp, "wm.wav")
            out_vid = os.path.join(VIDEO_DIR, f"wm_user{uid}_{vid.name}")

            open(in_vid, "wb").write(vid.read())
            extract_audio(in_vid, wav)

            sr, samples = wavfile.read(wav)
            wm_samples = embed_watermark(samples, uid)
            wavfile.write(wm_wav, sr, wm_samples)

            merge_audio(in_vid, wm_wav, out_vid)

            c.execute(
                "INSERT INTO videos(filename,path,uploaded_by) VALUES(?,?,?)",
                (vid.name, out_vid, uid)
            )
            conn.commit()

            st.success("Watermarked!")
            st.video(out_vid)
            st.download_button("Download", open(out_vid, "rb"), file_name=vid.name)

# -------- DETECT --------
with tabs[1]:
    st.header("Detect Watermark")
    vid = st.file_uploader("Upload Video for Detection", type=["mp4","mkv","avi"], key="detect")

    if vid and st.button("Detect"):
        with tempfile.TemporaryDirectory() as tmp:
            v = os.path.join(tmp, vid.name)
            wav = os.path.join(tmp, "d.wav")
            open(v,"wb").write(vid.read())
            extract_audio(v, wav)

            sr, samples = wavfile.read(wav)
            wid = extract_watermark(samples)

            c.execute("SELECT username FROM users WHERE id=?", (wid,))
            user = c.fetchone()

            if user:
                st.success(f"Watermark belongs to user ID {wid} ({user[0]})")
            else:
                st.error("Unknown / corrupted watermark")

# -------- ALL VIDEOS --------
with tabs[2]:
    st.header("All Watermarked Videos")
    c.execute("""
        SELECT videos.filename, videos.path, users.username
        FROM videos JOIN users ON users.id = videos.uploaded_by
    """)
    for f,p,u in c.fetchall():
        st.markdown(f"**{f}** — uploaded by `{u}`")
        st.video(p)
        st.download_button("Download", open(p,"rb"), file_name=f)

# -------- USERS --------
with tabs[3]:
    st.header("Registered Users")
    c.execute("SELECT id,username,phone FROM users")
    for i,u,p in c.fetchall():
        st.markdown(f"ID: {i} | User: {u} | Phone: {p}")

# -------- LOGOUT --------
with tabs[4]:
    if st.button("Logout"):
        st.session_state.user = None
        st.rerun()
