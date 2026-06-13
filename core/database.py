import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "friday.db")

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._initialize_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Conversations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Memory / Preferences table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def save_message(self, role, message):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (role, message, timestamp) VALUES (?, ?, ?)",
                (role, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()

    def get_conversation_history(self, limit=50):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, message, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            # Return in chronological order
            return [{"role": row[0], "message": row[1], "timestamp": row[2]} for row in reversed(rows)]

    def save_memory(self, key, value):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO memory (key, value, timestamp) VALUES (?, ?, ?)",
                (key, value, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()

    def get_memory(self, key):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM memory WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None
