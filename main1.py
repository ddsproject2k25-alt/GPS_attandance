# app.py (Enhanced Version with Dynamic Location Management)

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time, timedelta
from io import BytesIO
from PIL import Image
import os
import hashlib
import secrets
from streamlit_js_eval import streamlit_js_eval
from geopy.distance import geodesic
from twilio.rest import Client
import logging
import folium
from streamlit_folium import folium_static
import json

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Page Configuration ---
st.set_page_config(
    page_title="Attendance System", 
    layout="wide", 
    initial_sidebar_state="expanded",
    page_icon="🎓"
)

# --- Constants & Configuration ---
DEFAULT_COLLEGE_LOCATION = (10.678922, 77.032420)
DEFAULT_ALLOWED_RADIUS_KM = 5.5
MAX_IMAGE_SIZE_MB = 5
ATTENDANCE_COOLDOWN_MINUTES = 60

# --- Twilio Setup ---
ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
FROM_SMS = os.environ.get("TWILIO_FROM_SMS")

if ACCOUNT_SID and AUTH_TOKEN and FROM_SMS:
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
else:
    client = None

# --- Security Functions ---
def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_admin_password(password):
    """Verify admin password (use environment variable in production)"""
    stored_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not stored_hash:
        stored_hash = hash_password("admin123")
    return hash_password(password) == stored_hash

# --- Helper Functions ---
def send_sms(to_number, message):
    """Send SMS with error handling and logging"""
    if not client:
        logger.warning("Twilio not configured - SMS not sent")
        return False
    
    try:
        msg = client.messages.create(body=message, from_=FROM_SMS, to=to_number)
        logger.info(f"SMS sent to {to_number} - SID: {msg.sid}")
        return True
    except Exception as e:
        logger.error(f"SMS failed to {to_number}: {str(e)}")
        st.error(f"❌ SMS failed: {str(e)}")
        return False

def get_active_location_zone(conn):
    """Get the currently active location zone for attendance"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, latitude, longitude, radius_meters, is_active 
        FROM location_zones 
        WHERE is_active = 1 
        ORDER BY updated_at DESC 
        LIMIT 1
    """)
    result = cursor.fetchone()
    
    if result:
        return {
            'id': result[0],
            'name': result[1],
            'latitude': result[2],
            'longitude': result[3],
            'radius_meters': result[4],
            'is_active': result[5]
        }
    return None

def is_within_zone(student_loc, zone):
    """Check if student location is within the specified zone"""
    if not student_loc or 'latitude' not in student_loc or 'longitude' not in student_loc:
        return False, None
    
    if not zone:
        return False, None
    
    try:
        student_coords = (student_loc['latitude'], student_loc['longitude'])
        zone_coords = (zone['latitude'], zone['longitude'])
        distance_meters = geodesic(zone_coords, student_coords).meters
        
        logger.info(f"Distance from {zone['name']}: {distance_meters:.2f} meters")
        
        is_within = distance_meters <= zone['radius_meters']
        return is_within, distance_meters
    except Exception as e:
        logger.error(f"Location validation error: {str(e)}")
        return False, None

def validate_image(img_buffer):
    """Validate image size and format"""
    if not img_buffer:
        return False, "No image provided"
    
    img_size_mb = len(img_buffer.getvalue()) / (1024 * 1024)
    if img_size_mb > MAX_IMAGE_SIZE_MB:
        return False, f"Image too large ({img_size_mb:.1f}MB). Max: {MAX_IMAGE_SIZE_MB}MB"
    
    try:
        Image.open(BytesIO(img_buffer.getvalue()))
        return True, "Valid"
    except Exception as e:
        return False, f"Invalid image: {str(e)}"

def sanitize_name(name):
    """Sanitize and validate student name"""
    if not name:
        return None
    
    name = ' '.join(name.strip().lower().split())
    
    if len(name) < 2 or len(name) > 100:
        return None
    
    if not all(c.isalpha() or c.isspace() or c in "'-." for c in name):
        return None
    
    return name

@st.cache_resource
def connect_db():
    """Create database connection"""
    try:
        conn = sqlite3.connect("attendance.db", check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        st.error("❌ Database connection failed")
        return None

def create_tables(conn):
    """Initialize database schema with location zones table"""
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Location zones table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS location_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        radius_meters REAL NOT NULL,
        is_active INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Attendance table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        status TEXT NOT NULL,
        image_data BLOB,
        latitude REAL,
        longitude REAL,
        distance_meters REAL,
        zone_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(zone_id) REFERENCES location_zones(id)
    )""")
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance(user_id, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_location_zones_active ON location_zones(is_active)")
    
    # Parent contacts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS parent_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        parent_name TEXT,
        phone TEXT NOT NULL,
        relationship TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    
    # Insert default college location zone if none exists
    cursor.execute("SELECT COUNT(*) FROM location_zones")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO location_zones (name, latitude, longitude, radius_meters, is_active)
            VALUES ('College Campus', ?, ?, ?, 1)
        """, (DEFAULT_COLLEGE_LOCATION[0], DEFAULT_COLLEGE_LOCATION[1], DEFAULT_ALLOWED_RADIUS_KM * 1000))
    
    conn.commit()
    logger.info("Database tables created/verified")

def get_attendance_stats(conn, date_str=None):
    """Get attendance statistics"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    cursor = conn.cursor()
    total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    present = cursor.execute(
        "SELECT COUNT(DISTINCT user_id) FROM attendance WHERE date = ? AND status = 'Present'",
        (date_str,)
    ).fetchone()[0]
    
    absent = total_users - present
    attendance_rate = (present / total_users * 100) if total_users > 0 else 0
    
    return {'total': total_users, 'present': present, 'absent': absent, 'rate': attendance_rate}

# --- Main App ---
def main():
    st.title("🎓 College Webcam Attendance System")
    
    if "location" not in st.session_state:
        st.session_state.location = None
    if "location_verified_at" not in st.session_state:
        st.session_state.location_verified_at = None
    
    conn = connect_db()
    if not conn:
        st.error("Cannot proceed without database connection")
        return
    
    create_tables(conn)
    
    render_admin_panel(conn)
    render_student_section(conn)
    
    if st.checkbox("📈 Show Dashboard", value=False):
        render_dashboard(conn)

def render_admin_panel(conn):
    """Render admin sidebar with location management"""
    st.sidebar.header("🔐 Admin Panel")
    
    admin_pass = st.sidebar.text_input("Enter Admin Password", type="password", key="admin_password")
    
    if not admin_pass:
        st.sidebar.info("Enter password to access admin features")
        return
    
    if not verify_admin_password(admin_pass):
        st.sidebar.error("❌ Invalid Password")
        return
    
    st.sidebar.success("✅ Admin Access Granted")
    
    # Location Zone Management
    st.sidebar.subheader("📍 Location Zone Management")
    
    # Show current active zone
    active_zone = get_active_location_zone(conn)
    if active_zone:
        st.sidebar.info(
            f"**Active Zone:** {active_zone['name']}\n\n"
            f"📍 Lat: {active_zone['latitude']:.6f}\n\n"
            f"📍 Lon: {active_zone['longitude']:.6f}\n\n"
            f"📏 Radius: {active_zone['radius_meters']:.0f} meters"
        )
    else:
        st.sidebar.warning("⚠️ No active location zone set")
    
    if st.sidebar.button("🗺️ Manage Location Zones"):
        st.session_state.show_location_manager = True
    
    # Time Window Configuration
    st.sidebar.subheader("🕒 Attendance Time Window")
    start_time_default = st.session_state.get('start_time', time(9, 0))
    end_time_default = st.session_state.get('end_time', time(17, 0))
    
    st.session_state.start_time = st.sidebar.time_input("Start Time", value=start_time_default)
    st.session_state.end_time = st.sidebar.time_input("End Time", value=end_time_default)
    
    if st.session_state.start_time >= st.session_state.end_time:
        st.sidebar.error("⚠️ End time must be after start time")
    else:
        st.sidebar.info(
            f"Window: {st.session_state.start_time.strftime('%H:%M')} – "
            f"{st.session_state.end_time.strftime('%H:%M')}"
        )
    
    # Statistics
    st.sidebar.subheader("📊 Today's Stats")
    stats = get_attendance_stats(conn)
    st.sidebar.metric("Total Students", stats['total'])
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Present", stats['present'])
    col2.metric("Absent", stats['absent'])
    st.sidebar.progress(stats['rate'] / 100)
    st.sidebar.caption(f"Attendance Rate: {stats['rate']:.1f}%")
    
    # Admin Actions
    st.sidebar.subheader("⚙️ Actions")
    
    export_format = st.sidebar.selectbox("Export Format", ["CSV", "Excel"])
    date_range = st.sidebar.date_input(
        "Select Date Range",
        value=(datetime.now().date(), datetime.now().date()),
        max_value=datetime.now().date()
    )
    
    if st.sidebar.button("📥 Export Attendance"):
        export_attendance_data(conn, date_range, export_format)
    
    if st.sidebar.button("🗑️ Delete All Records"):
        if st.sidebar.checkbox("⚠️ Confirm Deletion", key="delete_confirm"):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM attendance")
            conn.commit()
            st.sidebar.success("✅ All records deleted")
            st.rerun()
    
    if client:
        st.sidebar.subheader("📲 SMS Notifications")
        if st.sidebar.button("Send Daily Summary"):
            send_daily_summary(conn)
    
    # Show location manager modal
    if st.session_state.get('show_location_manager', False):
        render_location_manager(conn)

def render_location_manager(conn):
    """Render location zone management interface"""
    st.markdown("---")
    st.header("🗺️ Location Zone Manager")
    
    cursor = conn.cursor()
    
    # Tabs for different operations
    tab1, tab2, tab3 = st.tabs(["📍 Create New Zone", "📋 View All Zones", "🗺️ Interactive Map"])
    
    with tab1:
        st.subheader("Create New Location Zone")
        
        col1, col2 = st.columns(2)
        
        with col1:
            zone_name = st.text_input(
                "Zone Name",
                placeholder="e.g., Classroom 101, Library, Lab A",
                help="Give a descriptive name for this location"
            )
            
            # Preset locations
            preset = st.selectbox(
                "Quick Presets",
                ["Custom Location", "College Campus (Wide)", "Classroom (Precise)", "Library", "Laboratory"]
            )
            
            if preset == "College Campus (Wide)":
                default_radius = 5500
            elif preset == "Classroom (Precise)":
                default_radius = 10
            elif preset == "Library":
                default_radius = 50
            elif preset == "Laboratory":
                default_radius = 30
            else:
                default_radius = 100
            
            radius_meters = st.number_input(
                "Radius (meters)",
                min_value=5,
                max_value=10000,
                value=default_radius,
                step=5,
                help="How far from the center point should attendance be allowed?"
            )
        
        with col2:
            st.info(
                "**Recommended Radius Guidelines:**\n\n"
                "🏫 College Campus: 5000-10000m\n\n"
                "🚪 Classroom: 10-20m\n\n"
                "📚 Library: 30-50m\n\n"
                "🔬 Laboratory: 20-40m\n\n"
                "🏟️ Sports Complex: 100-200m"
            )
        
        st.markdown("#### Set Location Coordinates")
        
        coord_method = st.radio(
            "Choose coordinate input method:",
            ["Manual Input", "Click on Map", "Use Current Location"],
            horizontal=True
        )
        
        if coord_method == "Manual Input":
            col1, col2 = st.columns(2)
            with col1:
                latitude = st.number_input(
                    "Latitude",
                    value=DEFAULT_COLLEGE_LOCATION[0],
                    format="%.6f",
                    help="Decimal degrees (e.g., 10.678922)"
                )
            with col2:
                longitude = st.number_input(
                    "Longitude",
                    value=DEFAULT_COLLEGE_LOCATION[1],
                    format="%.6f",
                    help="Decimal degrees (e.g., 77.032420)"
                )
        
        elif coord_method == "Click on Map":
            st.info("👆 Click on the map in the 'Interactive Map' tab to select coordinates")
            
            if 'selected_coords' in st.session_state:
                latitude = st.session_state.selected_coords[0]
                longitude = st.session_state.selected_coords[1]
                st.success(f"Selected: {latitude:.6f}, {longitude:.6f}")
            else:
                latitude = DEFAULT_COLLEGE_LOCATION[0]
                longitude = DEFAULT_COLLEGE_LOCATION[1]
        
        else:  # Use Current Location
            if st.button("📍 Get My Current Location"):
                js_code = """
                new Promise(function(resolve, reject) {
                    if (!navigator.geolocation) {
                        reject("Geolocation not supported");
                        return;
                    }
                    navigator.geolocation.getCurrentPosition(
                        function(position) {
                            resolve({
                                latitude: position.coords.latitude, 
                                longitude: position.coords.longitude
                            });
                        },
                        function(error) {
                            reject("Error: " + error.message);
                        },
                        {enableHighAccuracy: true, timeout: 10000}
                    );
                });
                """
                
                with st.spinner("Getting your location..."):
                    loc_data = streamlit_js_eval(js_expressions=js_code, want_output=True, key=f"admin_loc_{secrets.token_hex(4)}")
                
                if isinstance(loc_data, dict) and 'latitude' in loc_data:
                    latitude = loc_data['latitude']
                    longitude = loc_data['longitude']
                    st.success(f"📍 Location captured: {latitude:.6f}, {longitude:.6f}")
                else:
                    st.error("Could not get location")
                    latitude = DEFAULT_COLLEGE_LOCATION[0]
                    longitude = DEFAULT_COLLEGE_LOCATION[1]
            else:
                latitude = DEFAULT_COLLEGE_LOCATION[0]
                longitude = DEFAULT_COLLEGE_LOCATION[1]
        
        # Preview map
        st.markdown("#### Preview Zone")
        preview_map = folium.Map(
            location=[latitude, longitude],
            zoom_start=17 if radius_meters < 100 else 15
        )
        
        folium.Marker(
            [latitude, longitude],
            popup=f"{zone_name or 'New Zone'}<br>Radius: {radius_meters}m",
            tooltip="Zone Center",
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(preview_map)
        
        folium.Circle(
            location=[latitude, longitude],
            radius=radius_meters,
            color='blue',
            fill=True,
            fillColor='blue',
            fillOpacity=0.2,
            popup=f"Allowed Area: {radius_meters}m radius"
        ).add_to(preview_map)
        
        folium_static(preview_map, width=700, height=400)
        
        # Save button
        col1, col2 = st.columns([1, 4])
        with col1:
            set_active = st.checkbox("Set as Active Zone", value=True)
        
        if st.button("💾 Save Location Zone", type="primary", use_container_width=True):
            if not zone_name:
                st.error("⚠️ Please enter a zone name")
            else:
                try:
                    # Deactivate all zones if this should be active
                    if set_active:
                        cursor.execute("UPDATE location_zones SET is_active = 0")
                    
                    # Insert new zone
                    cursor.execute("""
                        INSERT INTO location_zones 
                        (name, latitude, longitude, radius_meters, is_active, updated_at)
                        VALUES (?, ?, ?, ?, ?, datetime('now'))
                    """, (zone_name, latitude, longitude, radius_meters, 1 if set_active else 0))
                    
                    conn.commit()
                    st.success(f"✅ Location zone '{zone_name}' created successfully!")
                    logger.info(f"New zone created: {zone_name} at ({latitude}, {longitude}) with radius {radius_meters}m")
                    
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error creating zone: {str(e)}")
    
    with tab2:
        st.subheader("All Location Zones")
        
        zones_df = pd.read_sql_query("""
            SELECT 
                id, name, latitude, longitude, radius_meters, 
                is_active, created_at
            FROM location_zones
            ORDER BY created_at DESC
        """, conn)
        
        if zones_df.empty:
            st.info("No location zones created yet")
        else:
            for _, zone in zones_df.iterrows():
                with st.expander(
                    f"{'🟢' if zone['is_active'] else '⚪'} {zone['name']} - "
                    f"{zone['radius_meters']:.0f}m radius",
                    expanded=zone['is_active'] == 1
                ):
                    col1, col2, col3 = st.columns([2, 2, 1])
                    
                    with col1:
                        st.write(f"**Zone ID:** {zone['id']}")
                        st.write(f"**Latitude:** {zone['latitude']:.6f}")
                        st.write(f"**Longitude:** {zone['longitude']:.6f}")
                    
                    with col2:
                        st.write(f"**Radius:** {zone['radius_meters']:.0f} meters")
                        st.write(f"**Status:** {'✅ Active' if zone['is_active'] else '⚪ Inactive'}")
                        st.write(f"**Created:** {zone['created_at'][:16]}")
                    
                    with col3:
                        if zone['is_active'] == 0:
                            if st.button("Activate", key=f"activate_{zone['id']}"):
                                cursor.execute("UPDATE location_zones SET is_active = 0")
                                cursor.execute(
                                    "UPDATE location_zones SET is_active = 1, updated_at = datetime('now') WHERE id = ?",
                                    (zone['id'],)
                                )
                                conn.commit()
                                st.success("✅ Zone activated")
                                st.rerun()
                        
                        if st.button("Delete", key=f"delete_{zone['id']}", type="secondary"):
                            if zone['is_active'] == 1:
                                st.error("Cannot delete active zone")
                            else:
                                cursor.execute("DELETE FROM location_zones WHERE id = ?", (zone['id'],))
                                conn.commit()
                                st.success("🗑️ Zone deleted")
                                st.rerun()
    
    with tab3:
        st.subheader("Interactive Map - All Zones")
        
        # Get all zones
        cursor.execute("SELECT name, latitude, longitude, radius_meters, is_active FROM location_zones")
        all_zones = cursor.fetchall()
        
        if not all_zones:
            st.info("No zones to display")
        else:
            # Create map centered on first zone
            map_center = [all_zones[0][1], all_zones[0][2]]
            interactive_map = folium.Map(location=map_center, zoom_start=15)
            
            for zone in all_zones:
                name, lat, lon, radius, is_active = zone
                color = 'red' if is_active else 'gray'
                
                folium.Marker(
                    [lat, lon],
                    popup=f"<b>{name}</b><br>Radius: {radius}m<br>{'Active' if is_active else 'Inactive'}",
                    tooltip=name,
                    icon=folium.Icon(color=color, icon='info-sign')
                ).add_to(interactive_map)
                
                folium.Circle(
                    location=[lat, lon],
                    radius=radius,
                    color=color,
                    fill=True,
                    fillColor=color,
                    fillOpacity=0.2 if is_active else 0.1,
                    popup=f"{name}: {radius}m radius"
                ).add_to(interactive_map)
            
            folium_static(interactive_map, width=900, height=600)
    
    if st.button("✖️ Close Location Manager"):
        st.session_state.show_location_manager = False
        st.rerun()

def export_attendance_data(conn, date_range, format_type):
    """Export attendance data"""
    start_date, end_date = date_range if isinstance(date_range, tuple) else (date_range, date_range)
    
    query = """
        SELECT 
            u.name AS Name,
            a.date AS Date,
            a.time AS Time,
            a.status AS Status,
            lz.name AS Location_Zone,
            a.distance_meters AS Distance_Meters
        FROM attendance a 
        JOIN users u ON a.user_id = u.id
        LEFT JOIN location_zones lz ON a.zone_id = lz.id
        WHERE a.date BETWEEN ? AND ?
        ORDER BY a.date DESC, a.time DESC
    """
    
    df = pd.read_sql_query(query, conn, params=(str(start_date), str(end_date)))
    
    if df.empty:
        st.sidebar.warning("No records found")
        return
    
    if format_type == "CSV":
        csv_data = df.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button(
            "💾 Download CSV",
            data=csv_data,
            file_name=f"attendance_{start_date}_to_{end_date}.csv",
            mime="text/csv"
        )
    else:
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Attendance')
        
        st.sidebar.download_button(
            "💾 Download Excel",
            data=buffer.getvalue(),
            file_name=f"attendance_{start_date}_to_{end_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

def send_daily_summary(conn):
    """Send daily summary SMS"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    all_users_df = pd.read_sql_query("SELECT name FROM users", conn)
    present_df = pd.read_sql_query(
        "SELECT u.name FROM attendance a JOIN users u ON a.user_id = u.id "
        "WHERE a.date = ? AND a.status = 'Present'",
        conn, params=(today_str,)
    )
    
    all_students = set(all_users_df["name"])
    present_students = set(present_df["name"])
    absent_students = sorted(list(all_students - present_students))
    
    faculty_number = "+916238533419"
    summary_msg = (
        f"Attendance Summary ({today_str}):\n"
        f"Present: {len(present_students)}\n"
        f"Absent: {len(absent_students)}\n"
        f"Absent: {', '.join(absent_students) if absent_students else 'None'}"
    )
    
    if send_sms(faculty_number, summary_msg):
        st.sidebar.success("✅ SMS sent")

def render_student_section(conn):
    """Render student attendance section"""
    st.markdown("---")
    st.header("👤 Student Attendance Marking")
    
    # Get active zone
    active_zone = get_active_location_zone(conn)
    
    if not active_zone:
        st.error("⚠️ No active location zone configured. Please contact admin.")
        return
    
    # Display active zone info
    st.info(
        f"📍 **Active Attendance Zone:** {active_zone['name']}\n\n"
        f"You must be within **{active_zone['radius_meters']:.0f} meters** of the designated location to mark attendance."
    )
    
    # Step 1: Location Verification
    st.subheader("📍 Step 1: Verify Your Location")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.write(f"Click the button below to verify you're within the **{active_zone['name']}** zone.")
    
    with col2:
        if st.session_state.location:
            is_valid, distance = is_within_zone(st.session_state.location, active_zone)
            if is_valid:
                st.success(f"✅ Verified ({distance:.1f}m)")
            else:
                st.error(f"❌ Too far ({distance:.1f}m)")
    
    if st.button("🌍 Get & Verify My Location", use_container_width=True):
        js_code = """
        new Promise(function(resolve, reject) {
            if (!navigator.geolocation) {
                reject("Geolocation not supported");
                return;
            }
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    resolve({
                        latitude: position.coords.latitude, 
                        longitude: position.coords.longitude,
                        accuracy: position.coords.accuracy
                    });
                },
                function(error) {
                    reject("Error: " + error.message);
                },
                {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}
            );
        });
        """
        
        with st.spinner("Getting your location..."):
            location_data = streamlit_js_eval(
                js_expressions=js_code, 
                want_output=True, 
                key=f"student_loc_{secrets.token_hex(4)}"
            )
        
        if isinstance(location_data, dict) and 'latitude' in location_data:
            st.session_state.location = location_data
            st.session_state.location_verified_at = datetime.now()
            
            is_valid, distance = is_within_zone(location_data, active_zone)
            
            st.success(
                f"📍 Location: {location_data['latitude']:.6f}, "
                f"{location_data['longitude']:.6f} (±{location_data.get('accuracy', 0):.0f}m)"
            )
            
            if is_valid:
                st.success(f"✅ You are within the **{active_zone['name']}** zone! Distance: {distance:.1f}m")
            else:
                st.error(
                    f"❌ You are **{distance:.1f} meters** from {active_zone['name']}. "
                    f"Required: within {active_zone['radius_meters']:.0f}m. "
                    "Please move closer to the designated location."
                )
        else:
            st.error(
                "❌ Could not get location. Please ensure:\n"
                "- Location services are enabled\n"
                "- You granted permission to this website\n"
                "- You're using a supported browser"
            )
    
    # Step 2: Mark Attendance
    st.markdown("---")
    st.subheader("📸 Step 2: Mark Attendance")
    
    name = st.text_input(
        "Enter your full name",
        key="student_name",
        placeholder="e.g., John Doe"
    ).strip()
    
    img_buffer = st.camera_input("📷 Take a picture for verification")
    
    if img_buffer:
        st.caption("✅ Photo captured")
    
    if st.button("✅ Mark My Attendance", type="primary", use_container_width=True):
        mark_attendance(conn, name, img_buffer, active_zone)

def mark_attendance(conn, name, img_buffer, active_zone):
    """Process attendance marking with zone validation"""
    cursor = conn.cursor()
    
    # Validations
    if not name:
        st.warning("⚠️ Please enter your name")
        return
    
    sanitized_name = sanitize_name(name)
    if not sanitized_name:
        st.error("❌ Invalid name format")
        return
    
    if not img_buffer:
        st.warning("⚠️ Please take a picture")
        return
    
    is_valid, msg = validate_image(img_buffer)
    if not is_valid:
        st.error(f"❌ {msg}")
        return
    
    if "start_time" not in st.session_state or "end_time" not in st.session_state:
        st.error("⛔ Attendance time window not configured")
        return
    
    if not st.session_state.location:
        st.warning("⚠️ Please complete Step 1 to verify your location")
        return
    
    # Check location recency
    if st.session_state.location_verified_at:
        elapsed_minutes = (datetime.now() - st.session_state.location_verified_at).seconds / 60
        if elapsed_minutes > 5:
            st.warning("⚠️ Location verification expired. Please verify again.")
            st.session_state.location = None
            return
    
    # Validate zone
    is_within, distance = is_within_zone(st.session_state.location, active_zone)
    
    if not is_within:
        st.error(
            f"❌ Cannot mark attendance. You are **{distance:.1f} meters** away from {active_zone['name']}. "
            f"You must be within **{active_zone['radius_meters']:.0f} meters**."
        )
        return
    
    # Check time window
    now = datetime.now()
    current_time = now.time()
    
    if not (st.session_state.start_time <= current_time <= st.session_state.end_time):
        start_str = st.session_state.start_time.strftime('%H:%M')
        end_str = st.session_state.end_time.strftime('%H:%M')
        st.warning(f"⏰ Attendance allowed between {start_str} and {end_str}")
        return
    
    # Get or create user
    cursor.execute("SELECT id FROM users WHERE name=?", (sanitized_name,))
    result = cursor.fetchone()
    
    if not result:
        cursor.execute("INSERT INTO users (name) VALUES (?)", (sanitized_name,))
        conn.commit()
        user_id = cursor.lastrowid
        logger.info(f"New user: {sanitized_name}")
    else:
        user_id = result[0]
    
    # Check duplicate
    date_str = now.strftime("%Y-%m-%d")
    cursor.execute("SELECT id, time FROM attendance WHERE user_id=? AND date=?", (user_id, date_str))
    existing = cursor.fetchone()
    
    if existing:
        st.warning(f"⚠️ Attendance already marked for '{sanitized_name.title()}' at {existing[1]}")
        return
    
    # Save attendance
    time_str = now.strftime("%H:%M:%S")
    image_bytes = img_buffer.getvalue()
    
    cursor.execute(
        """INSERT INTO attendance 
        (user_id, date, time, status, image_data, latitude, longitude, distance_meters, zone_id) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, date_str, time_str, "Present", image_bytes,
            st.session_state.location['latitude'],
            st.session_state.location['longitude'],
            distance,
            active_zone['id']
        )
    )
    conn.commit()
    
    st.success(
        f"✅ Attendance marked for **{sanitized_name.title()}** at {time_str}\n\n"
        f"📍 Location: {active_zone['name']} ({distance:.1f}m from center)"
    )
    logger.info(f"Attendance: {sanitized_name} at {time_str} in {active_zone['name']}")
    
    # Clear location
    st.session_state.location = None
    st.session_state.location_verified_at = None

def render_dashboard(conn):
    """Render dashboard"""
    st.markdown("---")
    st.header("📋 Attendance Dashboard")
    
    selected_date = st.date_input(
        "Select Date",
        value=datetime.now().date(),
        max_value=datetime.now().date()
    )
    
    date_str = selected_date.strftime("%Y-%m-%d")
    stats = get_attendance_stats(conn, date_str)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Students", stats['total'])
    col2.metric("Present", stats['present'])
    col3.metric("Absent", stats['absent'])
    col4.metric("Rate", f"{stats['rate']:.1f}%")
    
    st.subheader(f"📝 Records for {selected_date.strftime('%B %d, %Y')}")
    
    df = pd.read_sql_query(
        """
        SELECT 
            u.name, a.time, a.status, a.image_data, 
            lz.name as zone_name, a.distance_meters
        FROM attendance a 
        JOIN users u ON a.user_id = u.id
        LEFT JOIN location_zones lz ON a.zone_id = lz.id
        WHERE a.date = ? 
        ORDER BY a.time ASC
        """,
        conn,
        params=(date_str,)
    )
    
    if df.empty:
        st.info(f"No records for {selected_date.strftime('%B %d, %Y')}")
    else:
        for idx, row in df.iterrows():
            with st.container():
                col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 2, 2])
                
                with col1:
                    if row["image_data"]:
                        try:
                            img = Image.open(BytesIO(row["image_data"]))
                            st.image(img, width=80)
                        except:
                            st.write("📷")
                
                col2.markdown(f"**{row['name'].title()}**")
                col3.markdown(f"🕐 {row['time']}")
                col4.markdown(f"📍 {row['zone_name'] or 'N/A'}")
                
                if row['distance_meters']:
                    col5.markdown(f"📏 {row['distance_meters']:.1f}m")
                else:
                    col5.markdown("📏 N/A")
                
                st.divider()

if __name__ == "__main__":
    main()