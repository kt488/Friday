import sqlite3
import os
import json
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

            # ── Multi-tenant tables ──

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS websites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    domain TEXT DEFAULT '',
                    bot_name TEXT DEFAULT 'Assistant',
                    persona TEXT DEFAULT '',
                    business_info TEXT DEFAULT '',
                    greeting_message TEXT DEFAULT 'Hello! How can I help you?',
                    theme TEXT DEFAULT '{}',
                    is_active INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (website_id) REFERENCES websites(id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    website_id INTEGER NOT NULL,
                    name TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'new',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (website_id) REFERENCES websites(id)
                )
            ''')

            # Migrate legacy conversations: add website_id column if missing
            # (graceful — websites table may exist from prior run without these)
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

    def clear_conversations(self):
        """Delete all conversation history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversations")
            conn.commit()

    # ── Multi-tenant helpers ──

    def add_website(self, slug, name, **kw):
        """Register a new website. Returns the row id or None."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO websites (slug, name, domain, bot_name, persona,
                        business_info, greeting_message, theme)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    slug, name,
                    kw.get('domain', ''),
                    kw.get('bot_name', 'Assistant'),
                    kw.get('persona', ''),
                    kw.get('business_info', ''),
                    kw.get('greeting_message', 'Hello! How can I help you?'),
                    json.dumps(kw.get('theme', {}))
                ))
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                print(f"[DB] add_website error: {e}")
                return None

    def get_website(self, slug):
        """Get website config by slug. Returns dict or None."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM websites WHERE slug = ?", (slug,))
            row = cursor.fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                d['theme'] = json.loads(d.get('theme', '{}'))
            except (json.JSONDecodeError, TypeError):
                d['theme'] = {}
            return d

    def get_website_by_id(self, wid):
        """Get website config by internal id."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM websites WHERE id = ?", (wid,))
            row = cursor.fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                d['theme'] = json.loads(d.get('theme', '{}'))
            except (json.JSONDecodeError, TypeError):
                d['theme'] = {}
            return d

    def update_website(self, slug, **kw):
        """Update website fields. Returns True on success."""
        allowed = {'name', 'domain', 'bot_name', 'persona', 'business_info',
                   'greeting_message', 'theme', 'is_active'}
        fields = {k: v for k, v in kw.items() if k in allowed}
        if not fields:
            return False
        if 'theme' in fields and isinstance(fields['theme'], dict):
            fields['theme'] = json.dumps(fields['theme'])
        fields['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [slug]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE websites SET {set_clause} WHERE slug = ?", values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_website(self, slug):
        """Remove a website and its data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Get id first
            cursor.execute("SELECT id FROM websites WHERE slug = ?", (slug,))
            row = cursor.fetchone()
            if row is None:
                return False
            wid = row[0]
            cursor.execute("DELETE FROM leads WHERE website_id = ?", (wid,))
            cursor.execute("DELETE FROM website_conversations WHERE website_id = ?", (wid,))
            cursor.execute("DELETE FROM websites WHERE id = ?", (wid,))
            conn.commit()
            return True

    def list_websites(self):
        """List all registered websites."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, slug, name, domain, bot_name, is_active, "
                "created_at, updated_at FROM websites ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]

    def save_website_message(self, website_id, session_id, role, message):
        """Save a message scoped to a website + session."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO website_conversations "
                "(website_id, session_id, role, message, timestamp) VALUES (?, ?, ?, ?, ?)",
                (website_id, session_id, role, message,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()

    def get_website_conversation(self, website_id, session_id, limit=20):
        """Get conversation history for a website session."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, message, timestamp FROM website_conversations "
                "WHERE website_id = ? AND session_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (website_id, session_id, limit)
            )
            rows = cursor.fetchall()
            return [{"role": r["role"], "message": r["message"],
                     "timestamp": r["timestamp"]} for r in reversed(rows)]

    def save_lead(self, website_id, name="", email="", phone="", message="", metadata=None):
        """Capture a lead for a website."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO leads (website_id, name, email, phone, message, metadata, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'new')",
                (website_id, name, email, phone, message,
                 json.dumps(metadata or {}))
            )
            conn.commit()
            return cursor.lastrowid

    def get_leads(self, website_id, limit=50):
        """Get leads for a website."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM leads WHERE website_id = ? ORDER BY created_at DESC LIMIT ?",
                (website_id, limit)
            )
            rows = cursor.fetchall()
            leads = []
            for r in rows:
                d = dict(r)
                try:
                    d['metadata'] = json.loads(d.get('metadata', '{}'))
                except (json.JSONDecodeError, TypeError):
                    d['metadata'] = {}
                leads.append(d)
            return leads

    def update_lead_status(self, lead_id, status):
        """Update a lead's status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE leads SET status = ? WHERE id = ?",
                           (status, lead_id))
            conn.commit()
            return cursor.rowcount > 0
