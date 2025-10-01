#!/usr/bin/env python3
"""
College Webcam Attendance System - Complete Updated Version
Created: October 2025
Version: 3.0 (Complete Update)
Author: CS/IT Student Project

Features:
- Location-based attendance with GPS verification
- Real-time webcam photo capture
- Admin panel with zone management
- Database with complete schema
- Enhanced error handling and debugging
- Dashboard with statistics and reports
- Parent SMS notifications (optional)
- Audit logging and backup system
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time, timedelta
from io import BytesIO
from PIL import Image
import os
import hashlib
import secrets
import json
import time as time_module
import logging
from typing import Dict, Optional, Tuple, Any

# Third-party imports
try:
    from streamlit_js_eval import streamlit_js_eval
    from geopy.distance import geodesic
    import folium
    from streamlit_folium import folium_static
except ImportError as e:
    st.error(f"❌ Missing required package: {e}")
    st.info("Run: pip install -r requirements.txt")
    st.stop()

# Optional imports (SMS functionality)
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

# --- Enhanced Logging Configuration ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')

# File handler
file_handler = logging.FileHandler('attendance_app.log')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# --- Page Configuration ---
st.set_page_config(
    page_title="🎓 College Attendance System", 
    layout="wide", 
    initial_sidebar_state="expanded",
    page_icon="🎓",
    menu_items={
        'Get Help': 'https://github.com/your-repo/attendance-system',
        'Report a bug': 'https://github.com/your-repo/attendance-system/issues',
        'About': "College Webcam Attendance System v3.0\nBuilt with Streamlit and SQLite"
    }
)

# --- Constants & Configuration ---
class Config:
    """Application configuration"""
    DEFAULT_COLLEGE_LOCATION = (10.678922, 77.032420)
    DEFAULT_ALLOWED_RADIUS_KM = 5.5
    MAX_IMAGE_SIZE_MB = 5
    ATTENDANCE_COOLDOWN_MINUTES = 60
    LOCATION_EXPIRE_MINUTES = 5

    # Database
    DB_PATH = "attendance.db"

    # Time limits
    DEFAULT_START_TIME = time(8, 0)   # 8:00 AM
    DEFAULT_END_TIME = time(18, 0)    # 6:00 PM

    # Security
    ADMIN_PASSWORD_DEFAULT = "admin123"
    SESSION_TIMEOUT_MINUTES = 30

# --- Security Functions ---
class Security:
    """Security utilities"""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_admin_password(password: str) -> bool:
        """Verify admin password"""
        stored_hash = os.environ.get("ADMIN_PASSWORD_HASH")
        if not stored_hash:
            stored_hash = Security.hash_password(Config.ADMIN_PASSWORD_DEFAULT)
        return Security.hash_password(password) == stored_hash

    @staticmethod
    def sanitize_name(name: str) -> Optional[str]:
        """Sanitize and validate student name"""
        if not name:
            return None

        # Clean and normalize
        name = ' '.join(name.strip().split())

        if len(name) < 2 or len(name) > 100:
            logger.warning(f"Invalid name length: {len(name)}")
            return None

        if not all(c.isalpha() or c.isspace() or c in "'-." for c in name):
            logger.warning(f"Invalid characters in name: {name}")
            return None

        return name.lower()  # Store in lowercase for consistency

# --- Database Management ---
class DatabaseManager:
    """Enhanced database operations"""

    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self.conn = None

    @st.cache_resource
    def get_connection(_self):
        """Get cached database connection"""
        try:
            conn = sqlite3.connect(_self.db_path, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            logger.info("✅ Database connected successfully")
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            st.error(f"❌ Database connection failed: {e}")
            return None

    def ensure_tables_exist(self):
        """Ensure all required tables exist"""
        conn = self.get_connection()
        if not conn:
            return False

        cursor = conn.cursor()

        # Check if required tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]

        required_tables = ['users', 'location_zones', 'attendance']
        missing_tables = [t for t in required_tables if t not in existing_tables]

        if missing_tables:
            logger.warning(f"Missing tables: {missing_tables}")
            st.warning(f"Missing database tables: {missing_tables}")
            st.info("Please run: python db.py")
            return False

        return True

    def get_active_location_zone(self) -> Optional[Dict]:
        """Get the currently active location zone"""
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, description, latitude, longitude, radius_meters, is_active 
                FROM location_zones 
                WHERE is_active = 1 
                ORDER BY updated_at DESC 
                LIMIT 1
            """)
            result = cursor.fetchone()

            if result:
                zone = {
                    'id': result[0],
                    'name': result[1],
                    'description': result[2] or '',
                    'latitude': result[3],
                    'longitude': result[4],
                    'radius_meters': result[5],
                    'is_active': result[6]
                }
                logger.debug(f"Active zone found: {zone['name']}")
                return zone
            else:
                logger.warning("No active location zone found")
                return None
        except Exception as e:
            logger.error(f"Error getting active zone: {e}")
            return None

    def get_all_zones(self) -> pd.DataFrame:
        """Get all location zones"""
        conn = self.get_connection()
        if not conn:
            return pd.DataFrame()

        try:
            return pd.read_sql_query("""
                SELECT id, name, description, latitude, longitude, 
                       radius_meters, is_active, created_at
                FROM location_zones
                ORDER BY is_active DESC, created_at DESC
            """, conn)
        except Exception as e:
            logger.error(f"Error getting zones: {e}")
            return pd.DataFrame()

    def create_zone(self, name: str, description: str, lat: float, lon: float, 
                   radius: float, set_active: bool = False) -> bool:
        """Create a new location zone"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()

            if set_active:
                cursor.execute("UPDATE location_zones SET is_active = 0")

            cursor.execute("""
                INSERT INTO location_zones 
                (name, description, latitude, longitude, radius_meters, is_active, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'admin', datetime('now'))
            """, (name, description, lat, lon, radius, 1 if set_active else 0))

            conn.commit()
            logger.info(f"Zone created: {name}")
            return True
        except Exception as e:
            logger.error(f"Error creating zone: {e}")
            return False

    def activate_zone(self, zone_id: int) -> bool:
        """Activate a specific zone"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE location_zones SET is_active = 0")
            cursor.execute(
                "UPDATE location_zones SET is_active = 1, updated_at = datetime('now') WHERE id = ?",
                (zone_id,)
            )
            conn.commit()
            logger.info(f"Zone {zone_id} activated")
            return True
        except Exception as e:
            logger.error(f"Error activating zone: {e}")
            return False

    def get_attendance_stats(self, date_str: str = None) -> Dict:
        """Get attendance statistics"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        conn = self.get_connection()
        if not conn:
            return {'total': 0, 'present': 0, 'absent': 0, 'rate': 0}

        try:
            cursor = conn.cursor()

            # Get total registered users
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
            total_users = cursor.fetchone()[0]

            # Get present count for the date
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) 
                FROM attendance 
                WHERE date = ? AND status = 'Present'
            """, (date_str,))
            present = cursor.fetchone()[0]

            absent = total_users - present
            attendance_rate = (present / total_users * 100) if total_users > 0 else 0

            return {
                'total': total_users, 
                'present': present, 
                'absent': absent, 
                'rate': attendance_rate
            }
        except Exception as e:
            logger.error(f"Stats calculation error: {e}")
            return {'total': 0, 'present': 0, 'absent': 0, 'rate': 0}

    def mark_attendance(self, user_id: int, image_data: bytes, location: Dict, 
                       zone: Dict, distance: float) -> bool:
        """Mark attendance in database"""
        conn = self.get_connection()
        if not conn:
            return False

        try:
            cursor = conn.cursor()
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")

            cursor.execute("""
                INSERT INTO attendance 
                (user_id, date, time, status, image_data, latitude, longitude, 
                 distance_meters, zone_id, accuracy_meters, device_info, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                user_id, date_str, time_str, "Present", image_data,
                location['latitude'], location['longitude'],
                distance, zone['id'], 
                location.get('accuracy', 0),
                f"Browser: {st.context.headers.get('user-agent', 'Unknown')}"
            ))

            conn.commit()
            logger.info(f"Attendance marked: user_id={user_id} at {time_str}")
            return True
        except Exception as e:
            logger.error(f"Error marking attendance: {e}")
            return False

# --- Location Utilities ---
class LocationManager:
    """Location and GPS utilities"""

    @staticmethod
    def is_within_zone(student_loc: Dict, zone: Dict) -> Tuple[bool, Optional[float]]:
        """Enhanced zone validation with detailed logging"""
        try:
            # Input validation
            if not student_loc or not isinstance(student_loc, dict):
                logger.warning(f"Invalid student location: {student_loc}")
                return False, None

            if 'latitude' not in student_loc or 'longitude' not in student_loc:
                logger.warning(f"Missing coordinates in location: {student_loc}")
                return False, None

            if not zone:
                logger.warning("Zone is None")
                return False, None

            # Extract coordinates
            student_lat = float(student_loc['latitude'])
            student_lon = float(student_loc['longitude'])
            zone_lat = float(zone['latitude'])
            zone_lon = float(zone['longitude'])
            zone_radius = float(zone['radius_meters'])

            logger.debug(f"Student: ({student_lat:.6f}, {student_lon:.6f})")
            logger.debug(f"Zone: ({zone_lat:.6f}, {zone_lon:.6f}), radius: {zone_radius}m")

            # Calculate distance using geopy
            student_coords = (student_lat, student_lon)
            zone_coords = (zone_lat, zone_lon)

            distance_meters = geodesic(zone_coords, student_coords).meters

            logger.info(f"Distance from {zone['name']}: {distance_meters:.2f}m (max: {zone_radius}m)")

            is_within = distance_meters <= zone_radius

            return is_within, distance_meters

        except Exception as e:
            logger.error(f"Location validation error: {e}")
            return False, None

    @staticmethod
    def get_location_js() -> str:
        """Generate JavaScript code for location capture"""
        return """
        new Promise(function(resolve, reject) {
            // Check if geolocation is supported
            if (!navigator.geolocation) {
                reject("Geolocation is not supported by this browser");
                return;
            }

            console.log("Requesting high-accuracy location...");

            // High accuracy options
            const options = {
                enableHighAccuracy: true,
                timeout: 20000,     // 20 seconds timeout
                maximumAge: 0       // Don't use cached location
            };

            // Get current position
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const result = {
                        latitude: position.coords.latitude,
                        longitude: position.coords.longitude,
                        accuracy: position.coords.accuracy,
                        altitude: position.coords.altitude,
                        heading: position.coords.heading,
                        speed: position.coords.speed,
                        timestamp: Date.now()
                    };
                    console.log("Location obtained:", result);
                    resolve(result);
                },
                function(error) {
                    let errorMsg = "Unknown location error";
                    switch(error.code) {
                        case error.PERMISSION_DENIED:
                            errorMsg = "Location access denied by user. Please enable location services.";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMsg = "Location information unavailable. Check your GPS/WiFi.";
                            break;
                        case error.TIMEOUT:
                            errorMsg = "Location request timed out. Please try again.";
                            break;
                    }
                    console.error("Geolocation error:", errorMsg);
                    reject(errorMsg);
                },
                options
            );
        });
        """

# --- Image Utilities ---
class ImageValidator:
    """Image validation and processing"""

    @staticmethod
    def validate_image(img_buffer) -> Tuple[bool, str]:
        """Validate image size and format"""
        if not img_buffer:
            return False, "No image provided"

        try:
            # Check file size
            img_size_mb = len(img_buffer.getvalue()) / (1024 * 1024)
            if img_size_mb > Config.MAX_IMAGE_SIZE_MB:
                return False, f"Image too large ({img_size_mb:.1f}MB). Max: {Config.MAX_IMAGE_SIZE_MB}MB"

            # Validate image format
            img = Image.open(BytesIO(img_buffer.getvalue()))

            # Check image dimensions
            width, height = img.size
            if width < 100 or height < 100:
                return False, "Image too small. Minimum 100x100 pixels."

            if width > 4000 or height > 4000:
                return False, "Image too large. Maximum 4000x4000 pixels."

            logger.debug(f"Image validated: {img_size_mb:.2f}MB, {width}x{height}")
            return True, "Valid"

        except Exception as e:
            logger.error(f"Image validation error: {e}")
            return False, f"Invalid image format: {str(e)}"

# --- SMS Notifications (Optional) ---
class NotificationManager:
    """SMS and email notifications"""

    def __init__(self):
        self.twilio_client = None
        self.setup_twilio()

    def setup_twilio(self):
        """Setup Twilio client if credentials are available"""
        if not TWILIO_AVAILABLE:
            logger.info("Twilio not installed - SMS disabled")
            return

        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")

        if account_sid and auth_token and from_number:
            try:
                self.twilio_client = Client(account_sid, auth_token)
                self.from_number = from_number
                logger.info("✅ Twilio SMS client initialized")
            except Exception as e:
                logger.warning(f"Twilio setup failed: {e}")
        else:
            logger.info("📱 Twilio credentials not configured")

    def send_sms(self, to_number: str, message: str) -> bool:
        """Send SMS notification"""
        if not self.twilio_client:
            logger.warning("SMS not available - Twilio not configured")
            return False

        try:
            message_obj = self.twilio_client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )
            logger.info(f"SMS sent to {to_number} - SID: {message_obj.sid}")
            return True
        except Exception as e:
            logger.error(f"SMS failed to {to_number}: {e}")
            return False

# --- Initialize Global Objects ---
db_manager = DatabaseManager()
location_manager = LocationManager()
image_validator = ImageValidator()
notification_manager = NotificationManager()

# --- Streamlit App Components ---

def render_header():
    """Render application header"""
    st.title("🎓 College Webcam Attendance System")
    st.markdown("### 📍 GPS-Verified Attendance with Real-time Photo Capture")

    # Status indicators
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if db_manager.get_connection():
            st.success("🟢 Database Connected")
        else:
            st.error("🔴 Database Error")

    with col2:
        active_zone = db_manager.get_active_location_zone()
        if active_zone:
            st.success(f"🟢 Zone: {active_zone['name']}")
        else:
            st.warning("🟡 No Active Zone")

    with col3:
        current_time = datetime.now().time()
        start_time = st.session_state.get('start_time', Config.DEFAULT_START_TIME)
        end_time = st.session_state.get('end_time', Config.DEFAULT_END_TIME)

        if start_time <= current_time <= end_time:
            st.success("🟢 Attendance Open")
        else:
            st.warning("🟡 Outside Hours")

    with col4:
        stats = db_manager.get_attendance_stats()
        st.info(f"📊 Today: {stats['present']}/{stats['total']}")

def render_admin_sidebar():
    """Render admin control sidebar"""
    st.sidebar.title("🔐 Admin Panel")

    # Admin authentication
    admin_pass = st.sidebar.text_input(
        "Admin Password", 
        type="password", 
        key="admin_password"
    )

    if not admin_pass:
        st.sidebar.info("Enter admin password to access controls")
        return False

    if not Security.verify_admin_password(admin_pass):
        st.sidebar.error("❌ Invalid Password")
        st.sidebar.info("Default password: admin123")
        return False

    st.sidebar.success("✅ Admin Access Granted")

    # Current system status
    st.sidebar.markdown("### 📊 System Status")

    active_zone = db_manager.get_active_location_zone()
    if active_zone:
        st.sidebar.success(f"✅ Active Zone: {active_zone['name']}")
        st.sidebar.write(f"📍 Coordinates: {active_zone['latitude']:.4f}, {active_zone['longitude']:.4f}")
        st.sidebar.write(f"📏 Radius: {active_zone['radius_meters']:.0f}m")
    else:
        st.sidebar.error("❌ No active zone configured")
        if st.sidebar.button("🏫 Create Default Zone"):
            success = db_manager.create_zone(
                name="College Campus",
                description="Default college campus zone",
                lat=Config.DEFAULT_COLLEGE_LOCATION[0],
                lon=Config.DEFAULT_COLLEGE_LOCATION[1],
                radius=Config.DEFAULT_ALLOWED_RADIUS_KM * 1000,
                set_active=True
            )
            if success:
                st.sidebar.success("✅ Default zone created")
                st.rerun()
            else:
                st.sidebar.error("❌ Failed to create zone")

    # Quick zone controls
    st.sidebar.markdown("### 🗺️ Quick Zone Setup")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🏫 Campus Wide\n(5.5km)", key="wide_zone"):
            db_manager.create_zone(
                "Campus Wide", "Wide campus coverage",
                Config.DEFAULT_COLLEGE_LOCATION[0], Config.DEFAULT_COLLEGE_LOCATION[1],
                5500, set_active=True
            )
            st.rerun()

    with col2:
        if st.button("🚪 Classroom\n(50m)", key="precise_zone"):
            db_manager.create_zone(
                "Classroom", "Precise classroom attendance",
                Config.DEFAULT_COLLEGE_LOCATION[0], Config.DEFAULT_COLLEGE_LOCATION[1],
                50, set_active=True
            )
            st.rerun()

    # Time window configuration
    st.sidebar.markdown("### 🕒 Attendance Hours")

    start_time_key = 'start_time'
    end_time_key = 'end_time'

    if start_time_key not in st.session_state:
        st.session_state[start_time_key] = Config.DEFAULT_START_TIME
    if end_time_key not in st.session_state:
        st.session_state[end_time_key] = Config.DEFAULT_END_TIME

    st.session_state[start_time_key] = st.sidebar.time_input(
        "Start Time", 
        value=st.session_state[start_time_key]
    )
    st.session_state[end_time_key] = st.sidebar.time_input(
        "End Time", 
        value=st.session_state[end_time_key]
    )

    if st.session_state[start_time_key] >= st.session_state[end_time_key]:
        st.sidebar.error("⚠️ End time must be after start time")

    # Today's statistics
    st.sidebar.markdown("### 📈 Today's Statistics")
    stats = db_manager.get_attendance_stats()

    st.sidebar.metric("Total Students", stats['total'])
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Present", stats['present'])
    col2.metric("Absent", stats['absent'])

    if stats['total'] > 0:
        st.sidebar.progress(stats['rate'] / 100)
        st.sidebar.caption(f"Attendance Rate: {stats['rate']:.1f}%")

    # Admin actions
    st.sidebar.markdown("### ⚙️ Admin Actions")

    if st.sidebar.button("🗺️ Manage Zones"):
        st.session_state.show_zone_manager = True

    if st.sidebar.button("📊 View Dashboard"):
        st.session_state.show_dashboard = True

    if st.sidebar.button("📥 Export Data"):
        st.session_state.show_export = True

    return True

def render_zone_manager():
    """Render location zone management interface"""
    st.header("🗺️ Location Zone Manager")

    tab1, tab2 = st.tabs(["📍 Create Zone", "📋 Manage Zones"])

    with tab1:
        st.subheader("Create New Attendance Zone")

        col1, col2 = st.columns([2, 1])

        with col1:
            zone_name = st.text_input("Zone Name", placeholder="e.g., Computer Lab A")
            zone_desc = st.text_area("Description", placeholder="Optional description")

            col1a, col1b = st.columns(2)
            with col1a:
                latitude = st.number_input(
                    "Latitude", 
                    value=Config.DEFAULT_COLLEGE_LOCATION[0],
                    format="%.6f"
                )
            with col1b:
                longitude = st.number_input(
                    "Longitude", 
                    value=Config.DEFAULT_COLLEGE_LOCATION[1],
                    format="%.6f"
                )

            radius = st.slider(
                "Radius (meters)", 
                min_value=10, max_value=10000, 
                value=100, step=10
            )

            set_active = st.checkbox("Set as active zone", value=True)

        with col2:
            st.info("**Radius Guidelines:**\n\n🏫 Campus: 5000-10000m\n🚪 Classroom: 10-50m\n📚 Library: 30-100m\n🔬 Lab: 20-50m")

            if st.button("📍 Use My Location"):
                js_code = location_manager.get_location_js()
                with st.spinner("Getting location..."):
                    loc_data = streamlit_js_eval(js_expressions=js_code, want_output=True, key=f"admin_loc_{secrets.token_hex(4)}")
                    if isinstance(loc_data, dict) and 'latitude' in loc_data:
                        st.session_state.temp_lat = loc_data['latitude']
                        st.session_state.temp_lon = loc_data['longitude']
                        st.success(f"📍 Location: {loc_data['latitude']:.6f}, {loc_data['longitude']:.6f}")

            if 'temp_lat' in st.session_state:
                if st.button("✅ Use This Location"):
                    latitude = st.session_state.temp_lat
                    longitude = st.session_state.temp_lon
                    st.rerun()

        # Map preview
        if latitude and longitude:
            preview_map = folium.Map(location=[latitude, longitude], zoom_start=16)
            folium.Marker([latitude, longitude], popup=zone_name or "New Zone").add_to(preview_map)
            folium.Circle(
                location=[latitude, longitude],
                radius=radius,
                color='blue',
                fill=True,
                fillColor='blue',
                fillOpacity=0.3
            ).add_to(preview_map)
            folium_static(preview_map, width=700, height=300)

        if st.button("💾 Create Zone", type="primary"):
            if not zone_name:
                st.error("❌ Zone name is required")
            else:
                success = db_manager.create_zone(
                    zone_name, zone_desc or "", latitude, longitude, radius, set_active
                )
                if success:
                    st.success(f"✅ Zone '{zone_name}' created successfully!")
                    time_module.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Failed to create zone")

    with tab2:
        st.subheader("Manage Existing Zones")

        zones_df = db_manager.get_all_zones()

        if zones_df.empty:
            st.info("No zones created yet")
        else:
            for _, zone in zones_df.iterrows():
                with st.expander(
                    f"{'🟢' if zone['is_active'] else '⚪'} {zone['name']} - {zone['radius_meters']:.0f}m",
                    expanded=zone['is_active'] == 1
                ):
                    col1, col2, col3 = st.columns([2, 2, 1])

                    with col1:
                        st.write(f"**Description:** {zone['description'] or 'N/A'}")
                        st.write(f"**Coordinates:** {zone['latitude']:.6f}, {zone['longitude']:.6f}")
                        st.write(f"**Radius:** {zone['radius_meters']:.0f} meters")

                    with col2:
                        st.write(f"**Status:** {'✅ Active' if zone['is_active'] else '⚪ Inactive'}")
                        st.write(f"**Created:** {zone['created_at'][:16]}")

                        # Mini map
                        mini_map = folium.Map(location=[zone['latitude'], zone['longitude']], zoom_start=15)
                        folium.Circle(
                            location=[zone['latitude'], zone['longitude']],
                            radius=zone['radius_meters'],
                            color='red' if zone['is_active'] else 'gray',
                            fill=True,
                            fillOpacity=0.3
                        ).add_to(mini_map)
                        folium_static(mini_map, width=250, height=150)

                    with col3:
                        if zone['is_active'] == 0:
                            if st.button("Activate", key=f"activate_{zone['id']}"):
                                if db_manager.activate_zone(zone['id']):
                                    st.success("✅ Zone activated")
                                    st.rerun()

    if st.button("✖️ Close Zone Manager"):
        if 'show_zone_manager' in st.session_state:
            del st.session_state.show_zone_manager
        st.rerun()

def render_student_attendance():
    """Render student attendance marking section"""
    st.header("👤 Student Attendance")

    # Check prerequisites
    active_zone = db_manager.get_active_location_zone()
    if not active_zone:
        st.error("⚠️ No active attendance zone configured. Please contact admin.")
        return

    # Display zone information
    st.info(f"📍 **Active Zone:** {active_zone['name']}\n"
           f"You must be within **{active_zone['radius_meters']:.0f} meters** of the designated location.")

    # Step 1: Location Verification
    st.markdown("---")
    st.subheader("📍 Step 1: Verify Your Location")

    # Location status display
    location_status_col, refresh_col = st.columns([4, 1])

    with location_status_col:
        if 'location' in st.session_state and st.session_state.location:
            is_valid, distance = location_manager.is_within_zone(st.session_state.location, active_zone)

            if is_valid:
                st.success(f"✅ Location Verified! Distance: {distance:.1f}m from {active_zone['name']}")
            else:
                st.error(f"❌ Outside Zone! Distance: {distance:.1f}m (max: {active_zone['radius_meters']:.0f}m)")
        else:
            st.info("📍 Click button below to get your current location")

    with refresh_col:
        if 'location' in st.session_state and st.session_state.location:
            if st.button("🔄 Refresh"):
                del st.session_state.location
                st.rerun()

    # Get location button
    if st.button("🌍 Get My Location", type="primary", use_container_width=True):
        with st.spinner("🛰️ Getting your GPS location... Please allow location access."):
            js_code = location_manager.get_location_js()

            location_data = streamlit_js_eval(
                js_expressions=js_code,
                want_output=True,
                key=f"student_location_{secrets.token_hex(4)}"
            )

            # Wait for result
            time_module.sleep(1)

            if isinstance(location_data, dict) and 'latitude' in location_data:
                st.session_state.location = location_data
                st.session_state.location_timestamp = datetime.now()

                st.success("📍 Location captured successfully!")
                st.info(f"**Coordinates:** {location_data['latitude']:.6f}, {location_data['longitude']:.6f}")
                st.info(f"**Accuracy:** ±{location_data.get('accuracy', 0):.0f} meters")

                # Validate immediately
                is_valid, distance = location_manager.is_within_zone(location_data, active_zone)

                if is_valid:
                    st.success(f"✅ You are within the attendance zone! ({distance:.1f}m from center)")
                else:
                    st.error(f"❌ You are outside the attendance zone! ({distance:.1f}m from center)")

                st.rerun()
            else:
                st.error("❌ Could not get your location. Please ensure:")
                st.markdown("""
                - Location services are enabled on your device
                - You granted permission to this website  
                - You're using a modern browser (Chrome, Firefox, Safari)
                - You're not in incognito/private browsing mode
                """)

                if location_data and isinstance(location_data, str):
                    st.error(f"Error: {location_data}")

    # Step 2: Mark Attendance
    st.markdown("---")
    st.subheader("📸 Step 2: Take Photo & Mark Attendance")

    # Check if location is valid
    location_valid = False
    if 'location' in st.session_state and st.session_state.location:
        is_valid, distance = location_manager.is_within_zone(st.session_state.location, active_zone)
        location_valid = is_valid

        # Check location freshness
        if 'location_timestamp' in st.session_state:
            elapsed_minutes = (datetime.now() - st.session_state.location_timestamp).seconds / 60
            if elapsed_minutes > Config.LOCATION_EXPIRE_MINUTES:
                st.warning(f"⚠️ Location verification expired ({elapsed_minutes:.0f} min ago). Please refresh.")
                location_valid = False

    if not location_valid:
        st.info("👆 Complete Step 1 to verify your location before proceeding.")

    # Student name input
    name = st.text_input(
        "Enter your full name",
        placeholder="e.g., John Doe",
        disabled=not location_valid,
        help="Enter your complete name as registered"
    )

    # Camera input for photo
    img_buffer = st.camera_input(
        "📷 Take your photo for attendance verification",
        disabled=not location_valid,
        help="Look directly at the camera and ensure good lighting"
    )

    # Display photo preview
    if img_buffer:
        st.success("✅ Photo captured successfully")

        # Show small preview
        with st.expander("👀 Photo Preview"):
            img = Image.open(img_buffer)
            st.image(img, width=200, caption="Your attendance photo")

    # Mark attendance button
    attendance_button_disabled = not (location_valid and name.strip() and img_buffer)

    if st.button(
        "✅ Mark My Attendance", 
        type="primary", 
        use_container_width=True,
        disabled=attendance_button_disabled
    ):
        process_attendance_marking(name, img_buffer, active_zone)

def process_attendance_marking(name: str, img_buffer, active_zone: Dict):
    """Process the attendance marking"""
    try:
        # Validate inputs
        sanitized_name = Security.sanitize_name(name)
        if not sanitized_name:
            st.error("❌ Invalid name format. Please use only letters, spaces, and basic punctuation.")
            return

        # Validate image
        is_valid_img, img_msg = image_validator.validate_image(img_buffer)
        if not is_valid_img:
            st.error(f"❌ Image validation failed: {img_msg}")
            return

        # Check location validity
        if 'location' not in st.session_state or not st.session_state.location:
            st.error("❌ Location not verified. Please complete Step 1.")
            return

        # Validate location freshness
        if 'location_timestamp' in st.session_state:
            elapsed_minutes = (datetime.now() - st.session_state.location_timestamp).seconds / 60
            if elapsed_minutes > Config.LOCATION_EXPIRE_MINUTES:
                st.error("❌ Location verification expired. Please refresh your location.")
                return

        # Check zone proximity
        is_within, distance = location_manager.is_within_zone(st.session_state.location, active_zone)
        if not is_within:
            st.error(f"❌ Cannot mark attendance. You are {distance:.1f}m from {active_zone['name']} "
                    f"(maximum allowed: {active_zone['radius_meters']:.0f}m)")
            return

        # Check time window
        current_time = datetime.now().time()
        start_time = st.session_state.get('start_time', Config.DEFAULT_START_TIME)
        end_time = st.session_state.get('end_time', Config.DEFAULT_END_TIME)

        if not (start_time <= current_time <= end_time):
            st.error(f"❌ Attendance can only be marked between {start_time.strftime('%H:%M')} "
                    f"and {end_time.strftime('%H:%M')}")
            return

        # Get or create user
        conn = db_manager.get_connection()
        if not conn:
            st.error("❌ Database connection failed")
            return

        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE name=?", (sanitized_name,))
        result = cursor.fetchone()

        if not result:
            # Create new user
            cursor.execute("INSERT INTO users (name) VALUES (?)", (sanitized_name,))
            conn.commit()
            user_id = cursor.lastrowid
            logger.info(f"New user created: {sanitized_name} (ID: {user_id})")
        else:
            user_id = result[0]

        # Check for duplicate attendance
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT id, time FROM attendance WHERE user_id=? AND date=?", (user_id, today))
        existing = cursor.fetchone()

        if existing:
            st.warning(f"⚠️ Attendance already marked for '{sanitized_name.title()}' today at {existing[1]}")
            return

        # Mark attendance
        image_bytes = img_buffer.getvalue()
        success = db_manager.mark_attendance(
            user_id, image_bytes, st.session_state.location, active_zone, distance
        )

        if success:
            current_time_str = datetime.now().strftime("%H:%M:%S")

            # Success message
            st.success(f"""
            🎉 **Attendance Marked Successfully!**

            **Student:** {sanitized_name.title()}  
            **Time:** {current_time_str}  
            **Date:** {today}  
            **Location:** {active_zone['name']}  
            **Distance:** {distance:.1f}m from center  
            """)

            # Clear session data
            if 'location' in st.session_state:
                del st.session_state.location
            if 'location_timestamp' in st.session_state:
                del st.session_state.location_timestamp

            # Celebration effect
            st.balloons()

            # Auto-refresh after delay
            time_module.sleep(2)
            st.rerun()
        else:
            st.error("❌ Failed to mark attendance. Please try again.")

    except Exception as e:
        logger.error(f"Attendance marking error: {e}", exc_info=True)
        st.error(f"❌ An error occurred: {str(e)}")

def render_dashboard():
    """Render attendance dashboard"""
    st.header("📊 Attendance Dashboard")

    # Date selector
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        selected_date = st.date_input(
            "Select Date",
            value=datetime.now().date(),
            max_value=datetime.now().date()
        )

    with col2:
        # Date range for statistics
        date_range = st.selectbox(
            "Statistics Period",
            ["Today", "This Week", "This Month"],
            index=0
        )

    date_str = selected_date.strftime("%Y-%m-%d")

    # Statistics cards
    stats = db_manager.get_attendance_stats(date_str)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Students", stats['total'])
    col2.metric("Present Today", stats['present'])
    col3.metric("Absent Today", stats['absent'])
    col4.metric("Attendance Rate", f"{stats['rate']:.1f}%")

    # Progress bar
    if stats['total'] > 0:
        st.progress(stats['rate'] / 100)
        st.caption(f"Attendance Rate: {stats['rate']:.1f}%")

    # Attendance records
    st.markdown("---")
    st.subheader(f"📝 Attendance Records - {selected_date.strftime('%B %d, %Y')}")

    conn = db_manager.get_connection()
    if conn:
        try:
            df = pd.read_sql_query("""
                SELECT 
                    u.name as "Student Name",
                    a.time as "Time",
                    a.status as "Status",
                    lz.name as "Location Zone",
                    ROUND(a.distance_meters, 1) || 'm' as "Distance",
                    CASE WHEN a.image_data IS NOT NULL THEN '✅' ELSE '❌' END as "Photo",
                    ROUND(a.accuracy_meters, 0) || 'm' as "GPS Accuracy"
                FROM attendance a 
                JOIN users u ON a.user_id = u.id
                LEFT JOIN location_zones lz ON a.zone_id = lz.id
                WHERE a.date = ? 
                ORDER BY a.time DESC
            """, conn, params=(date_str,))

            if df.empty:
                st.info(f"📭 No attendance records found for {selected_date.strftime('%B %d, %Y')}")
            else:
                st.dataframe(
                    df, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Student Name": st.column_config.TextColumn(width="medium"),
                        "Time": st.column_config.TextColumn(width="small"),
                        "Status": st.column_config.TextColumn(width="small"),
                        "Location Zone": st.column_config.TextColumn(width="medium"),
                        "Distance": st.column_config.TextColumn(width="small"),
                        "Photo": st.column_config.TextColumn(width="small"),
                        "GPS Accuracy": st.column_config.TextColumn(width="small")
                    }
                )

                # Export options
                col1, col2 = st.columns(2)
                with col1:
                    csv_data = df.to_csv(index=False)
                    st.download_button(
                        "📥 Download CSV",
                        data=csv_data,
                        file_name=f"attendance_{date_str}.csv",
                        mime="text/csv"
                    )

                with col2:
                    # Show photos option
                    if st.button("📷 View Photos"):
                        show_attendance_photos(date_str)

        except Exception as e:
            st.error(f"❌ Error loading records: {e}")
            logger.error(f"Dashboard error: {e}")

    if st.button("✖️ Close Dashboard"):
        if 'show_dashboard' in st.session_state:
            del st.session_state.show_dashboard
        st.rerun()

def show_attendance_photos(date_str: str):
    """Display attendance photos for a specific date"""
    conn = db_manager.get_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.name, a.time, a.image_data
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE a.date = ? AND a.image_data IS NOT NULL
            ORDER BY a.time
        """, (date_str,))

        records = cursor.fetchall()

        if not records:
            st.info("No photos found for this date")
            return

        st.subheader(f"📷 Attendance Photos - {date_str}")

        cols = st.columns(3)
        for i, (name, time, image_data) in enumerate(records):
            col = cols[i % 3]
            with col:
                try:
                    img = Image.open(BytesIO(image_data))
                    st.image(img, caption=f"{name.title()}\n{time}", use_column_width=True)
                except Exception as e:
                    st.error(f"Error loading image for {name}")

    except Exception as e:
        st.error(f"Error loading photos: {e}")

# --- Main Application ---
def main():
    """Main application function"""
    try:
        # Initialize session state
        if 'show_zone_manager' not in st.session_state:
            st.session_state.show_zone_manager = False
        if 'show_dashboard' not in st.session_state:
            st.session_state.show_dashboard = False

        # Render header
        render_header()

        # Check database connection
        if not db_manager.ensure_tables_exist():
            st.error("❌ Database setup required. Please run: python db.py")
            st.stop()

        # Render admin sidebar
        is_admin = render_admin_sidebar()

        # Main content based on admin selections
        if st.session_state.get('show_zone_manager', False) and is_admin:
            render_zone_manager()
        elif st.session_state.get('show_dashboard', False):
            render_dashboard()
        else:
            # Default: Student attendance section
            render_student_attendance()

        # Footer
        st.markdown("---")
        st.markdown("### 💡 Tips for Best Results:")
        st.markdown("""
        - **Location**: Ensure GPS/location services are enabled
        - **Camera**: Use good lighting and look directly at camera  
        - **Browser**: Use Chrome, Firefox, or Safari for best compatibility
        - **Connection**: Stable internet connection recommended
        """)

        # System information
        with st.expander("ℹ️ System Information"):
            st.write("**Version:** 3.0")
            st.write("**Database:** SQLite with WAL mode")
            st.write("**Location:** GPS + Network positioning")
            st.write("**Security:** SHA-256 password hashing")

            if is_admin:
                info = db_manager.db_manager.get_database_info() if hasattr(db_manager, 'db_manager') else {}
                if info:
                    st.json(info)

    except Exception as e:
        logger.error(f"Main app error: {e}", exc_info=True)
        st.error(f"❌ Application error: {e}")
        st.info("Please check logs for details")

if __name__ == "__main__":
    main()
