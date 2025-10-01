#!/usr/bin/env python3
"""
Database Setup and Management for College Attendance System
Created: October 2025
Version: 2.0 (Fixed Schema)
"""

import sqlite3
import logging
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('attendance_db.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_COLLEGE_LOCATION = {
    'latitude': 10.678922,
    'longitude': 77.032420,
    'name': 'College Campus Main',
    'radius_meters': 5500
}

class AttendanceDatabase:
    """Database manager for attendance system"""

    def __init__(self, db_path="attendance.db"):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")  # Better concurrency
            logger.info(f"✅ Connected to database: {self.db_path}")
            return self.conn
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            raise

    def create_tables(self):
        """Create all necessary tables with proper schema"""
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        try:
            # 1. Users Table (Enhanced)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                phone TEXT,
                roll_number TEXT UNIQUE,
                department TEXT,
                year_of_study INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

            # 2. Location Zones Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS location_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                radius_meters REAL NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Constraints
                CONSTRAINT check_latitude CHECK (latitude >= -90 AND latitude <= 90),
                CONSTRAINT check_longitude CHECK (longitude >= -180 AND longitude <= 180),
                CONSTRAINT check_radius CHECK (radius_meters > 0),
                CONSTRAINT check_active CHECK (is_active IN (0, 1))
            )""")

            # 3. Attendance Table (Complete)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Present',
                image_data BLOB,
                latitude REAL,
                longitude REAL,
                distance_meters REAL,
                zone_id INTEGER,
                accuracy_meters REAL,
                device_info TEXT,
                ip_address TEXT,
                user_agent TEXT,
                notes TEXT,
                verified_by TEXT,
                is_manual INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Foreign Keys
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(zone_id) REFERENCES location_zones(id) ON DELETE SET NULL,

                -- Constraints
                CONSTRAINT check_status CHECK (status IN ('Present', 'Absent', 'Late', 'Excused')),
                CONSTRAINT check_distance CHECK (distance_meters >= 0),
                CONSTRAINT check_manual CHECK (is_manual IN (0, 1)),

                -- Unique constraint to prevent duplicate attendance
                UNIQUE(user_id, date)
            )""")

            # 4. Parent/Guardian Contacts Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS parent_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                parent_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                relationship TEXT DEFAULT 'Parent',
                is_primary INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT check_relationship CHECK (relationship IN ('Parent', 'Guardian', 'Emergency Contact')),
                CONSTRAINT check_primary CHECK (is_primary IN (0, 1)),
                CONSTRAINT check_active CHECK (is_active IN (0, 1))
            )""")

            # 5. Attendance Sessions Table (for tracking attendance periods)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                zone_id INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(zone_id) REFERENCES location_zones(id),
                CONSTRAINT check_session_active CHECK (is_active IN (0, 1))
            )""")

            # 6. Admin Users Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT UNIQUE,
                full_name TEXT,
                role TEXT DEFAULT 'admin',
                is_active INTEGER DEFAULT 1,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                CONSTRAINT check_role CHECK (role IN ('admin', 'super_admin', 'teacher')),
                CONSTRAINT check_admin_active CHECK (is_active IN (0, 1))
            )""")

            # 7. Attendance Logs Table (for audit trail)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attendance_id INTEGER,
                action TEXT NOT NULL,
                old_values TEXT,
                new_values TEXT,
                performed_by TEXT,
                ip_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(attendance_id) REFERENCES attendance(id) ON DELETE CASCADE,
                CONSTRAINT check_action CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'VERIFY'))
            )""")

            # Create Indexes for Performance
            self._create_indexes(cursor)

            # Create Triggers for Audit Trail
            self._create_triggers(cursor)

            # Insert Default Data
            self._insert_default_data(cursor)

            self.conn.commit()
            logger.info("✅ All database tables created successfully!")

            # Verify table creation
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            logger.info(f"📋 Created tables: {', '.join(tables)}")

        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ Table creation failed: {e}")
            raise

    def _create_indexes(self, cursor):
        """Create database indexes for better performance"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_name ON users(name)",
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_roll_number ON users(roll_number)",
            "CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)",

            "CREATE INDEX IF NOT EXISTS idx_attendance_user_id ON attendance(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance(user_id, date)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_zone_id ON attendance(zone_id)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_status ON attendance(status)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_created_at ON attendance(created_at)",

            "CREATE INDEX IF NOT EXISTS idx_location_zones_active ON location_zones(is_active)",
            "CREATE INDEX IF NOT EXISTS idx_location_zones_name ON location_zones(name)",

            "CREATE INDEX IF NOT EXISTS idx_parent_contacts_user_id ON parent_contacts(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_parent_contacts_primary ON parent_contacts(is_primary)",

            "CREATE INDEX IF NOT EXISTS idx_attendance_sessions_active ON attendance_sessions(is_active)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_sessions_dates ON attendance_sessions(start_date, end_date)",

            "CREATE INDEX IF NOT EXISTS idx_admin_users_username ON admin_users(username)",
            "CREATE INDEX IF NOT EXISTS idx_admin_users_active ON admin_users(is_active)",

            "CREATE INDEX IF NOT EXISTS idx_attendance_logs_attendance_id ON attendance_logs(attendance_id)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_logs_timestamp ON attendance_logs(timestamp)"
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)

        logger.info("✅ Database indexes created")

    def _create_triggers(self, cursor):
        """Create triggers for automatic timestamping and audit logging"""

        # Trigger to update 'updated_at' timestamp
        triggers = [
            """
            CREATE TRIGGER IF NOT EXISTS update_users_timestamp 
            AFTER UPDATE ON users
            BEGIN
                UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS update_location_zones_timestamp 
            AFTER UPDATE ON location_zones
            BEGIN
                UPDATE location_zones SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS update_attendance_timestamp 
            AFTER UPDATE ON attendance
            BEGIN
                UPDATE attendance SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
            """,

            # Audit trigger for attendance changes
            """
            CREATE TRIGGER IF NOT EXISTS audit_attendance_insert 
            AFTER INSERT ON attendance
            BEGIN
                INSERT INTO attendance_logs (attendance_id, action, new_values)
                VALUES (NEW.id, 'CREATE', json_object(
                    'user_id', NEW.user_id,
                    'date', NEW.date,
                    'time', NEW.time,
                    'status', NEW.status,
                    'zone_id', NEW.zone_id,
                    'distance_meters', NEW.distance_meters
                ));
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS audit_attendance_update 
            AFTER UPDATE ON attendance
            BEGIN
                INSERT INTO attendance_logs (attendance_id, action, old_values, new_values)
                VALUES (NEW.id, 'UPDATE', 
                    json_object(
                        'status', OLD.status,
                        'notes', OLD.notes,
                        'verified_by', OLD.verified_by
                    ),
                    json_object(
                        'status', NEW.status,
                        'notes', NEW.notes,
                        'verified_by', NEW.verified_by
                    )
                );
            END
            """
        ]

        for trigger_sql in triggers:
            cursor.execute(trigger_sql)

        logger.info("✅ Database triggers created")

    def _insert_default_data(self, cursor):
        """Insert default data if tables are empty"""

        # Check if location zones exist
        cursor.execute("SELECT COUNT(*) FROM location_zones")
        zone_count = cursor.fetchone()[0]

        if zone_count == 0:
            # Insert default college location
            cursor.execute("""
                INSERT INTO location_zones 
                (name, description, latitude, longitude, radius_meters, is_active, created_by)
                VALUES (?, ?, ?, ?, ?, 1, 'System')
            """, (
                DEFAULT_COLLEGE_LOCATION['name'],
                'Main college campus attendance zone',
                DEFAULT_COLLEGE_LOCATION['latitude'],
                DEFAULT_COLLEGE_LOCATION['longitude'],
                DEFAULT_COLLEGE_LOCATION['radius_meters']
            ))

            # Insert additional sample zones
            sample_zones = [
                ('Library', 'College library building', 10.678500, 77.032100, 50),
                ('Computer Lab', 'Main computer laboratory', 10.678800, 77.032300, 30),
                ('Auditorium', 'College main auditorium', 10.679000, 77.032500, 100),
                ('Sports Complex', 'Athletic facilities', 10.679200, 77.032800, 200)
            ]

            for name, desc, lat, lon, radius in sample_zones:
                cursor.execute("""
                    INSERT INTO location_zones 
                    (name, description, latitude, longitude, radius_meters, is_active, created_by)
                    VALUES (?, ?, ?, ?, ?, 0, 'System')
                """, (name, desc, lat, lon, radius))

            logger.info(f"✅ Inserted {len(sample_zones) + 1} default location zones")

        # Check if admin user exists
        cursor.execute("SELECT COUNT(*) FROM admin_users")
        admin_count = cursor.fetchone()[0]

        if admin_count == 0:
            # Insert default admin (password: admin123)
            import hashlib
            default_password_hash = hashlib.sha256("admin123".encode()).hexdigest()

            cursor.execute("""
                INSERT INTO admin_users 
                (username, password_hash, email, full_name, role, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                'admin',
                default_password_hash,
                'admin@college.edu',
                'System Administrator',
                'super_admin'
            ))

            logger.info("✅ Default admin user created (username: admin, password: admin123)")

    def backup_database(self, backup_path=None):
        """Create database backup"""
        if not backup_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"attendance_backup_{timestamp}.db"

        try:
            if self.conn:
                backup_conn = sqlite3.connect(backup_path)
                self.conn.backup(backup_conn)
                backup_conn.close()
                logger.info(f"✅ Database backed up to: {backup_path}")
                return backup_path
        except Exception as e:
            logger.error(f"❌ Backup failed: {e}")
            raise

    def get_database_info(self):
        """Get database statistics and information"""
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()
        info = {}

        # Get table counts
        tables = ['users', 'location_zones', 'attendance', 'parent_contacts', 
                 'attendance_sessions', 'admin_users', 'attendance_logs']

        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                info[f"{table}_count"] = cursor.fetchone()[0]
            except:
                info[f"{table}_count"] = 0

        # Database file size
        if os.path.exists(self.db_path):
            info['db_size_mb'] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)

        # Get active zones
        cursor.execute("SELECT COUNT(*) FROM location_zones WHERE is_active = 1")
        info['active_zones'] = cursor.fetchone()[0]

        # Latest attendance
        cursor.execute("SELECT MAX(created_at) FROM attendance")
        latest = cursor.fetchone()[0]
        info['latest_attendance'] = latest if latest else 'None'

        return info

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("✅ Database connection closed")


def create_tables():
    """Main function to create all database tables"""
    db = AttendanceDatabase()
    try:
        db.connect()
        db.create_tables()

        # Display database info
        info = db.get_database_info()
        print("\n📊 Database Information:")
        print("=" * 50)
        for key, value in info.items():
            print(f"{key}: {value}")

        return True
    except Exception as e:
        logger.error(f"❌ Database setup failed: {e}")
        return False
    finally:
        db.close()


def reset_database():
    """Reset database - WARNING: Deletes all data"""
    db_path = "attendance.db"

    if os.path.exists(db_path):
        # Create backup before reset
        db = AttendanceDatabase(db_path)
        try:
            db.connect()
            backup_path = db.backup_database()
            print(f"✅ Backup created: {backup_path}")
            db.close()
        except Exception as e:
            print(f"⚠️ Backup failed: {e}")

        # Remove old database
        os.remove(db_path)
        print(f"🗑️ Deleted old database: {db_path}")

    # Create new database
    return create_tables()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='College Attendance Database Manager')
    parser.add_argument('--reset', action='store_true', help='Reset database (WARNING: Deletes all data)')
    parser.add_argument('--backup', action='store_true', help='Create database backup')
    parser.add_argument('--info', action='store_true', help='Show database information')

    args = parser.parse_args()

    if args.reset:
        confirm = input("⚠️ This will DELETE ALL DATA. Type 'yes' to confirm: ")
        if confirm.lower() == 'yes':
            if reset_database():
                print("✅ Database reset completed!")
            else:
                print("❌ Database reset failed!")
        else:
            print("❌ Reset cancelled")

    elif args.backup:
        db = AttendanceDatabase()
        try:
            db.connect()
            backup_path = db.backup_database()
            print(f"✅ Backup created: {backup_path}")
        except Exception as e:
            print(f"❌ Backup failed: {e}")
        finally:
            db.close()

    elif args.info:
        db = AttendanceDatabase()
        try:
            db.connect()
            info = db.get_database_info()
            print("\n📊 Database Information:")
            print("=" * 50)
            for key, value in info.items():
                print(f"{key}: {value}")
        except Exception as e:
            print(f"❌ Info retrieval failed: {e}")
        finally:
            db.close()

    else:
        if create_tables():
            print("✅ Database setup completed successfully!")
            print("\n🔑 Default Admin Credentials:")
            print("Username: admin")
            print("Password: admin123")
            print("\n💡 Run 'python db.py --help' for more options")
        else:
            print("❌ Database setup failed!")
