import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time
from io import BytesIO
from PIL import Image
import tempfile
import zipfile
import os

# 🎓 App Title
st.title("🎓 College Webcam Attendance System")

# ✅ Use a temporary DB path (works on Streamlit Cloud too)
if "db_path" not in st.session_state:
    temp_dir = tempfile.gettempdir()
    st.session_state.db_path = os.path.join(temp_dir, "attendance.db")

# Persistent DB connection
if "conn" not in st.session_state:
    st.session_state.conn = sqlite3.connect(st.session_state.db_path, check_same_thread=False)
    st.session_state.cursor = st.session_state.conn.cursor()

conn = st.session_state.conn
cursor = st.session_state.cursor

# ✅ Create tables if not exist
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    date TEXT,
    time TEXT,
    status TEXT,
    image_data BLOB,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")
conn.commit()

# 🔐 Admin login
st.sidebar.subheader("🔐 Admin Panel")
admin_pass = st.sidebar.text_input("Enter admin password", type="password")
admin_logged_in = admin_pass == "admin123"

# ✅ Admin-only controls
if admin_logged_in:
    st.sidebar.success("✅ Admin access granted")

    # Time window setup
    new_start_hour = st.sidebar.slider("Start Hour", 0, 23, 9)
    new_start_minute = st.sidebar.slider("Start Minute", 0, 59, 0)
    new_end_hour = st.sidebar.slider("End Hour", 0, 23, 9)
    new_end_minute = st.sidebar.slider("End Minute", 0, 59, 15)

    if st.sidebar.button("🕘 Set Time Window"):
        st.session_state.start_time = time(new_start_hour, new_start_minute)
        st.session_state.end_time = time(new_end_hour, new_end_minute)
        st.sidebar.success(
            f"✅ Time window set: {new_start_hour:02d}:{new_start_minute:02d} – {new_end_hour:02d}:{new_end_minute:02d}"
        )

    # Delete attendance data
    if st.sidebar.button("🗑️ Delete All Attendance Records"):
        cursor.execute("DELETE FROM attendance")
        conn.commit()
        st.sidebar.warning("⚠️ All attendance records deleted.")

    # 📦 Download attendance archive (CSV + images in-memory)
    df = pd.read_sql_query("""
        SELECT a.id, u.name, a.date, a.time, a.status, a.image_data
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.id DESC
    """, conn)

    if st.sidebar.button("📦 Prepare Attendance Archive"):
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            # Add CSV to ZIP
            csv_data = df.drop(columns=["image_data"]).to_csv(index=False)
            zipf.writestr("attendance.csv", csv_data)

            # Add images
            for i, row in df.iterrows():
                if row["image_data"]:
                    img_name = f"{row['name']}_{row['time'].replace(':', '-')}.jpg"
                    zipf.writestr(img_name, row["image_data"])

        zip_buffer.seek(0)
        st.sidebar.download_button(
            "📥 Download Archive",
            zip_buffer,
            file_name="attendance_archive.zip",
            mime="application/zip",
        )

else:
    st.sidebar.info("ℹ️ Admin access required to set attendance window.")

# 📷 Webcam input
img = st.camera_input("📷 Take a picture")

# 🧑 Name input
name = st.text_input("🧍 Enter your name")

# ✅ Mark Attendance Button
if st.button("✅ Mark Attendance"):
    if not name.strip():
        st.warning("⚠️ Please enter your name.")
    elif not img:
        st.warning("⚠️ Please capture your photo.")
    else:
        if "start_time" not in st.session_state or "end_time" not in st.session_state:
            st.warning("⛔ Attendance time window not set. Please contact admin.")
        else:
            now = datetime.now()
            current_time = now.time()
            start_time = st.session_state.start_time
            end_time = st.session_state.end_time

            if start_time <= current_time <= end_time:
                # Check if user exists
                cursor.execute("SELECT id FROM users WHERE name=?", (name,))
                result = cursor.fetchone()

                if not result:
                    cursor.execute("INSERT INTO users (name) VALUES (?)", (name,))
                    conn.commit()
                    cursor.execute("SELECT id FROM users WHERE name=?", (name,))
                    result = cursor.fetchone()

                user_id = result[0]
                date = now.strftime("%Y-%m-%d")
                time_str = now.strftime("%H:%M:%S")
                image_bytes = img.getvalue()

                # Check if already marked today
                cursor.execute("SELECT * FROM attendance WHERE user_id=? AND date=?", (user_id, date))
                if cursor.fetchone():
                    st.warning(f"⚠️ Attendance already marked today for {name}")
                else:
                    cursor.execute("""
                        INSERT INTO attendance (user_id, date, time, status, image_data)
                        VALUES (?, ?, ?, ?, ?)
                    """, (user_id, date, time_str, "Present", image_bytes))
                    conn.commit()
                    st.success(f"✅ Attendance marked for {name} at {time_str}")
            else:
                st.warning(
                    f"⏰ Attendance allowed between {start_time.strftime('%H:%M')} – {end_time.strftime('%H:%M')}"
                )

# 📊 Attendance Viewer
if st.checkbox("📊 Show Attendance Records"):
    df = pd.read_sql_query("""
        SELECT a.id, u.name, a.date, a.time, a.status, a.image_data
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.id DESC
    """, conn)

    st.markdown("### 📋 Attendance Records")

    # Table headers
    col1, col2, col3, col4, col5 = st.columns([1.5, 2, 2, 2, 2])
    col1.markdown("**🖼️ Image**")
    col2.markdown("**🧑 Name**")
    col3.markdown("**📅 Date**")
    col4.markdown("**⏰ Time**")
    col5.markdown("**✅ Status**")

    # Rows
    for _, row in df.iterrows():
        c1, c2, c3, c4, c5 = st.columns([1.5, 2, 2, 2, 2])
        if row["image_data"]:
            c1.image(BytesIO(row["image_data"]), width=80)
        else:
            c1.write("No image")
        c2.write(row["name"])
        c3.write(row["date"])
        c4.write(row["time"])
        c5.write(row["status"])
