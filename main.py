import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time
from io import BytesIO
from PIL import Image
import os
import zipfile

# Title
st.title("🎓 College Webcam Attendance System")

# Persistent DB connection
if "conn" not in st.session_state:
    st.session_state.conn = sqlite3.connect("attendance.db", check_same_thread=False)
    st.session_state.cursor = st.session_state.conn.cursor()

cursor = st.session_state.cursor
conn = st.session_state.conn

# Create tables if not exist
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

# Admin login
st.sidebar.subheader("🔐 Admin Panel")
admin_pass = st.sidebar.text_input("Enter admin password", type="password")
admin_logged_in = admin_pass == "admin123"

# Admin-only controls
if admin_logged_in:
    st.sidebar.success("Admin access granted")

    # Time sliders
    new_start_hour = st.sidebar.slider("Start Hour", 0, 23, 9)
    new_start_minute = st.sidebar.slider("Start Minute", 0, 59, 0)
    new_end_hour = st.sidebar.slider("End Hour", 0, 23, 9)
    new_end_minute = st.sidebar.slider("End Minute", 0, 59, 15)

    # Set Time button
    if st.sidebar.button("🕘 Set Time Window"):
        st.session_state.start_time = time(new_start_hour, new_start_minute)
        st.session_state.end_time = time(new_end_hour, new_end_minute)
        st.sidebar.success(f"✅ Time window updated to {new_start_hour:02d}:{new_start_minute:02d} – {new_end_hour:02d}:{new_end_minute:02d}")

    # Delete attendance records button
    if st.sidebar.button("🗑️ Delete All Attendance Records"):
        cursor.execute("DELETE FROM attendance")
        conn.commit()
        st.sidebar.warning("⚠️ All attendance records deleted.")

    # Download attendance archive (CSV + images)
    df = pd.read_sql_query("""
        SELECT a.id, u.name, a.date, a.time, a.status, a.image_data
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.id DESC
    """, conn)

    if st.sidebar.button("📦 Download Attendance Archive"):
        os.makedirs("attendance_images", exist_ok=True)
        csv_path = "attendance_images/attendance.csv"
        df.drop(columns=["image_data"]).to_csv(csv_path, index=False)

        # Save images
        for i, row in df.iterrows():
            if row["image_data"]:
                img_path = f"attendance_images/{row['name']}_{row['time'].replace(':', '-')}.jpg"
                with open(img_path, "wb") as f:
                    f.write(row["image_data"])

        # Create ZIP
        zip_path = "attendance_archive.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            zipf.write(csv_path)
            for file in os.listdir("attendance_images"):
                zipf.write(os.path.join("attendance_images", file))

        with open(zip_path, "rb") as f:
            st.sidebar.download_button("📥 Download Archive", f.read(), file_name="attendance_archive.zip", mime="application/zip")

else:
    st.sidebar.info("Admin access required to set attendance time window.")

# Webcam input
img = st.camera_input("📷 Take a picture")

# Name input
name = st.text_input("🧑 Enter your name")

# Attendance marking
if st.button("✅ Mark Attendance", key="mark_btn"):
    if name.strip() and img:
        if "start_time" not in st.session_state or "end_time" not in st.session_state:
            st.warning("⛔ Attendance time window not set. Please contact admin.")
        else:
            now = datetime.now()
            current_time = now.time()
            start_time = st.session_state.start_time
            end_time = st.session_state.end_time

            if start_time <= current_time <= end_time:
                cursor.execute("SELECT id FROM users WHERE name=?", (name,))
                result = cursor.fetchone()

                if not result:
                    cursor.execute("INSERT INTO users (name) VALUES (?)", (name,))
                    conn.commit()
                    cursor.execute("SELECT id FROM users WHERE name=?", (name,))
                    result = cursor.fetchone()

                user_id = result[0]
                date, time_str = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
                image_bytes = img.getvalue()

                cursor.execute("""
                    SELECT * FROM attendance WHERE user_id=? AND date=?
                """, (user_id, date))
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
                st.warning(f"⏰ Attendance can only be marked between {start_time.strftime('%H:%M')} and {end_time.strftime('%H:%M')}")
    else:
        st.warning("⚠️ Please enter your name and capture a photo.")

# Attendance viewer
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

    # Table rows
    for _, row in df.iterrows():
        col1, col2, col3, col4, col5 = st.columns([1.5, 2, 2, 2, 2])
        if row['image_data']:
            col1.image(BytesIO(row['image_data']), width=80)
        else:
            col1.write("No image")
        col2.write(row['name'])
        col3.write(row['date'])
        col4.write(row['time'])
        col5.write(row['status'])
