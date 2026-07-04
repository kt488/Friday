"""
Service Connections & OAuth — universal "App Connections" system.

Manages OAuth 2.0 (PKCE), API-key connections, encrypted credential storage,
and AI context injection for 25+ third-party services across 8 categories.
"""

import hashlib
import json
import os
import secrets
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet

# ══════════════════════════════════════════════════════════════
# Provider Registry
# ══════════════════════════════════════════════════════════════

APP_PROVIDERS = {
    # ── Communications ──
    "slack": {
        "name": "Slack",
        "description": "Team communication and collaboration",
        "category": "communications",
        "auth_type": "oauth2",
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": ["channels:read", "chat:write", "users:read"],
        "client_id_env": "FRIDAY_SLACK_CLIENT_ID",
        "client_secret_env": "FRIDAY_SLACK_CLIENT_SECRET",
    },
    # ── Google Workspace ──
    "google": {
        "name": "Google Workspace",
        "description": "Calendar, Gmail, Drive, Docs, Sheets, Slides",
        "category": "google_workspace",
        "auth_type": "oauth2",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "base_scopes": ["openid", "email", "profile"],
        "client_id_env": "FRIDAY_GOOGLE_CLIENT_ID",
        "client_secret_env": "FRIDAY_GOOGLE_CLIENT_SECRET",
        "sub_services": {
            "calendar": {
                "name": "Google Calendar",
                "description": "Create and manage events",
                "scopes": ["https://www.googleapis.com/auth/calendar"],
                "api_base": "https://www.googleapis.com/calendar/v3",
            },
            "gmail": {
                "name": "Gmail",
                "description": "Read, send, and manage emails",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly",
                           "https://www.googleapis.com/auth/gmail.send"],
                "api_base": "https://gmail.googleapis.com/gmail/v1",
            },
            "drive": {
                "name": "Google Drive",
                "description": "Store and access files",
                "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
                "api_base": "https://www.googleapis.com/drive/v3",
            },
            "docs": {
                "name": "Google Docs",
                "description": "Read and edit documents",
                "scopes": ["https://www.googleapis.com/auth/documents.readonly"],
                "api_base": "https://docs.googleapis.com/v1",
            },
            "sheets": {
                "name": "Google Sheets",
                "description": "Read and edit spreadsheets",
                "scopes": ["https://www.googleapis.com/auth/spreadsheets.readonly"],
                "api_base": "https://sheets.googleapis.com/v4",
            },
            "slides": {
                "name": "Google Slides",
                "description": "Read and edit presentations",
                "scopes": ["https://www.googleapis.com/auth/presentations.readonly"],
                "api_base": "https://slides.googleapis.com/v1",
            },
        },
    },
    # ── Microsoft 365 ──
    "microsoft": {
        "name": "Microsoft 365",
        "description": "Outlook, OneDrive, Word, Excel, Teams via Graph API",
        "category": "microsoft_365",
        "auth_type": "oauth2",
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "base_scopes": ["offline_access", "openid", "profile"],
        "client_id_env": "FRIDAY_MICROSOFT_CLIENT_ID",
        "client_secret_env": "FRIDAY_MICROSOFT_CLIENT_SECRET",
        "sub_services": {
            "outlook_mail": {
                "name": "Outlook Mail",
                "description": "Read and send emails",
                "scopes": ["Mail.Read", "Mail.Send", "MailboxSettings.Read"],
                "api_base": "https://graph.microsoft.com/v1.0",
            },
            "outlook_calendar": {
                "name": "Outlook Calendar",
                "description": "Manage calendar and events",
                "scopes": ["Calendars.Read", "Calendars.ReadWrite"],
                "api_base": "https://graph.microsoft.com/v1.0",
            },
            "onedrive": {
                "name": "OneDrive",
                "description": "Store and access files",
                "scopes": ["Files.Read.All", "Files.ReadWrite.All"],
                "api_base": "https://graph.microsoft.com/v1.0",
            },
            "word": {
                "name": "Word",
                "description": "Read and edit Word documents",
                "scopes": ["Files.Read.All"],
                "api_base": "https://graph.microsoft.com/v1.0",
            },
            "excel": {
                "name": "Excel",
                "description": "Read and edit spreadsheets",
                "scopes": ["Files.Read.All"],
                "api_base": "https://graph.microsoft.com/v1.0",
            },
            "teams": {
                "name": "Microsoft Teams",
                "description": "Teams messages and channels",
                "scopes": ["Channel.ReadBasic.All", "Chat.Read",
                           "Team.ReadBasic.All"],
                "api_base": "https://graph.microsoft.com/v1.0",
            },
        },
    },
    # ── Apple ──
    "apple": {
        "name": "Apple",
        "description": "Calendar, Notes, Reminders (requires Apple Developer)",
        "category": "apple",
        "auth_type": "oauth2",
        "authorize_url": "https://appleid.apple.com/auth/authorize",
        "token_url": "https://appleid.apple.com/auth/token",
        "scopes": ["name", "email"],
        "client_id_env": "FRIDAY_APPLE_CLIENT_ID",
        "client_secret_env": "FRIDAY_APPLE_CLIENT_SECRET",
        "sub_services": {
            "calendar": {
                "name": "Apple Calendar",
                "description": "Calendar via CalDAV/CloudKit",
                "scopes": [],
                "api_base": None,
            },
            "notes": {
                "name": "Apple Notes",
                "description": "Notes via CloudKit",
                "scopes": [],
                "api_base": None,
            },
            "reminders": {
                "name": "Apple Reminders",
                "description": "Reminders via CloudKit",
                "scopes": [],
                "api_base": None,
            },
        },
    },
    # ── Productivity ──
    "notion": {
        "name": "Notion",
        "description": "All-in-one workspace for notes and docs",
        "category": "productivity",
        "auth_type": "oauth2",
        "authorize_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": [],
        "client_id_env": "FRIDAY_NOTION_CLIENT_ID",
        "client_secret_env": "FRIDAY_NOTION_CLIENT_SECRET",
    },
    "evernote": {
        "name": "Evernote",
        "description": "Note-taking and organization",
        "category": "productivity",
        "auth_type": "oauth2",
        "authorize_url": "https://www.evernote.com/OAuth.action",
        "token_url": "https://www.evernote.com/oauth/v2/token",
        "scopes": ["note_store"],
        "client_id_env": "FRIDAY_EVERNOTE_CLIENT_ID",
        "client_secret_env": "FRIDAY_EVERNOTE_CLIENT_SECRET",
    },
    "obsidian": {
        "name": "Obsidian",
        "description": "Local knowledge base (REST API key or MCP)",
        "category": "productivity",
        "auth_type": "api_key",
        "scopes": [],
        "client_id_env": None,
        "client_secret_env": None,
    },
    "todoist": {
        "name": "Todoist",
        "description": "Task management and to-do lists",
        "category": "productivity",
        "auth_type": "oauth2",
        "authorize_url": "https://todoist.com/oauth/authorize",
        "token_url": "https://todoist.com/oauth/access_token",
        "scopes": ["data:read", "data:write"],
        "client_id_env": "FRIDAY_TODOIST_CLIENT_ID",
        "client_secret_env": "FRIDAY_TODOIST_CLIENT_SECRET",
    },
    "ticktick": {
        "name": "TickTick",
        "description": "To-do list and task management",
        "category": "productivity",
        "auth_type": "oauth2",
        "authorize_url": "https://ticktick.com/oauth/authorize",
        "token_url": "https://ticktick.com/oauth/token",
        "scopes": ["tasks:read", "tasks:write"],
        "client_id_env": "FRIDAY_TICKTICK_CLIENT_ID",
        "client_secret_env": "FRIDAY_TICKTICK_CLIENT_SECRET",
    },
    "anydo": {
        "name": "Any.do",
        "description": "Task management and to-do lists",
        "category": "productivity",
        "auth_type": "oauth2",
        "authorize_url": "https://api.any.do/oauth/authorize",
        "token_url": "https://api.any.do/oauth/token",
        "scopes": ["tasks:read", "tasks:write"],
        "client_id_env": "FRIDAY_ANYDO_CLIENT_ID",
        "client_secret_env": "FRIDAY_ANYDO_CLIENT_SECRET",
    },
    # ── Project Management ──
    "trello": {
        "name": "Trello",
        "description": "Visual project management with boards and cards",
        "category": "project_management",
        "auth_type": "oauth2",
        "authorize_url": "https://trello.com/1/authorize",
        "token_url": "https://trello.com/1/OAuthGetAccessToken",
        "scopes": ["read", "write"],
        "client_id_env": "FRIDAY_TRELLO_API_KEY",
        "client_secret_env": "FRIDAY_TRELLO_API_SECRET",
    },
    "asana": {
        "name": "Asana",
        "description": "Team project and task management",
        "category": "project_management",
        "auth_type": "oauth2",
        "authorize_url": "https://app.asana.com/-/oauth_authorize",
        "token_url": "https://app.asana.com/-/oauth_token",
        "scopes": ["default"],
        "client_id_env": "FRIDAY_ASANA_CLIENT_ID",
        "client_secret_env": "FRIDAY_ASANA_CLIENT_SECRET",
    },
    "clickup": {
        "name": "ClickUp",
        "description": "All-in-one project management platform",
        "category": "project_management",
        "auth_type": "oauth2",
        "authorize_url": "https://app.clickup.com/oauth/authorize",
        "token_url": "https://api.clickup.com/api/v2/oauth/token",
        "scopes": ["tasks:read", "tasks:write", "spaces:read"],
        "client_id_env": "FRIDAY_CLICKUP_CLIENT_ID",
        "client_secret_env": "FRIDAY_CLICKUP_CLIENT_SECRET",
    },
    "monday": {
        "name": "Monday.com",
        "description": "Visual project management (GraphQL API)",
        "category": "project_management",
        "auth_type": "oauth2",
        "authorize_url": "https://auth.monday.com/oauth2/authorize",
        "token_url": "https://auth.monday.com/oauth2/token",
        "scopes": ["boards:read", "boards:write"],
        "client_id_env": "FRIDAY_MONDAY_CLIENT_ID",
        "client_secret_env": "FRIDAY_MONDAY_CLIENT_SECRET",
    },
    "airtable": {
        "name": "Airtable",
        "description": "Spreadsheet-database hybrid platform",
        "category": "project_management",
        "auth_type": "oauth2",
        "authorize_url": "https://airtable.com/oauth2/v1/authorize",
        "token_url": "https://airtable.com/oauth2/v1/token",
        "scopes": ["data.records:read", "data.records:write",
                   "schema.bases:read"],
        "client_id_env": "FRIDAY_AIRTABLE_CLIENT_ID",
        "client_secret_env": "FRIDAY_AIRTABLE_CLIENT_SECRET",
    },
    "coda": {
        "name": "Coda",
        "description": "All-in-one collaborative workspace",
        "category": "project_management",
        "auth_type": "oauth2",
        "authorize_url": "https://coda.io/oauth/v1/authorize",
        "token_url": "https://coda.io/oauth/v1/token",
        "scopes": ["read", "write"],
        "client_id_env": "FRIDAY_CODA_CLIENT_ID",
        "client_secret_env": "FRIDAY_CODA_CLIENT_SECRET",
    },
    # ── Developer Tools ──
    "github": {
        "name": "GitHub",
        "description": "Code hosting and version control",
        "category": "developer",
        "auth_type": "oauth2",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:user"],
        "client_id_env": "FRIDAY_GITHUB_CLIENT_ID",
        "client_secret_env": "FRIDAY_GITHUB_CLIENT_SECRET",
    },
    # ── Entertainment ──
    "spotify": {
        "name": "Spotify",
        "description": "Music streaming and discovery",
        "category": "entertainment",
        "auth_type": "oauth2",
        "authorize_url": "https://accounts.spotify.com/authorize",
        "token_url": "https://accounts.spotify.com/api/token",
        "scopes": ["user-read-private", "user-read-email"],
        "client_id_env": "FRIDAY_SPOTIFY_CLIENT_ID",
        "client_secret_env": "FRIDAY_SPOTIFY_CLIENT_SECRET",
    },
}

# Backward-compatible alias for code expecting OAUTH_SERVICES
OAUTH_SERVICES = {
    k: v for k, v in APP_PROVIDERS.items() if v["auth_type"] == "oauth2"
}

CATEGORY_LABELS = {
    "communications": "Communications",
    "google_workspace": "Google Workspace",
    "microsoft_365": "Microsoft 365",
    "apple": "Apple",
    "productivity": "Productivity",
    "project_management": "Project Management",
    "developer": "Developer Tools",
    "entertainment": "Entertainment",
}

CONNECTION_LIMITS = {"free": 3, "starter": 10, "professional": 50, "enterprise": 999}


class ConnectionManager:
    """Manages OAuth 2.0 (PKCE) and API-key connections for all providers."""

    def __init__(self, db, encryption_key=None):
        self.db = db
        key = encryption_key or os.getenv("FRIDAY_ENCRYPTION_KEY")
        if not key:
            key = Fernet.generate_key()
            os.environ["FRIDAY_ENCRYPTION_KEY"] = key.decode()
        if isinstance(key, str):
            key = key.encode()
        self.cipher = Fernet(key)

    # ── Encryption ──────────────────────────────────────────

    def encrypt_credentials(self, data):
        """Encrypt a dict of credentials to a Fernet ciphertext string."""
        return self.cipher.encrypt(json.dumps(data).encode()).decode()

    def decrypt_credentials(self, ciphertext):
        """Decrypt a Fernet ciphertext string back to a dict."""
        return json.loads(self.cipher.decrypt(ciphertext.encode()).decode())

    # ── PKCE helpers ────────────────────────────────────────

    @staticmethod
    def _generate_code_verifier():
        return secrets.token_urlsafe(64)

    @staticmethod
    def _generate_code_challenge(verifier):
        digest = hashlib.sha256(verifier.encode()).digest()
        return urlsafe_b64encode(digest).rstrip(b"=").decode()

    # ── Provider registry ───────────────────────────────────

    def get_providers(self, category=None):
        """List all provider definitions, optionally filtered by category."""
        items = list(APP_PROVIDERS.values())
        if category:
            items = [p for p in items if p["category"] == category]
        return items

    def get_provider(self, provider_key):
        """Get a single provider definition or None."""
        return APP_PROVIDERS.get(provider_key)

    def get_categories(self):
        """Return category groups with their providers and sub-services."""
        groups = {}
        for key, prov in APP_PROVIDERS.items():
            cat = prov["category"]
            if cat not in groups:
                groups[cat] = {
                    "category": cat,
                    "label": CATEGORY_LABELS.get(cat, cat),
                    "providers": [],
                }
            entry = {
                "key": key,
                "name": prov["name"],
                "description": prov["description"],
                "auth_type": prov["auth_type"],
            }
            if "sub_services" in prov:
                entry["sub_services"] = [
                    {"key": sk, "name": sv["name"], "description": sv["description"]}
                    for sk, sv in prov["sub_services"].items()
                ]
            groups[cat]["providers"].append(entry)
        return list(groups.values())

    # ── Client config helpers ───────────────────────────────

    def _get_client_config(self, service):
        """Get provider config, falling back to OAUTH_SERVICES."""
        prov = APP_PROVIDERS.get(service)
        if prov:
            return prov
        legacy = OAUTH_SERVICES.get(service)
        if legacy:
            return legacy
        raise ValueError(f"Unknown service provider: {service}")

    def _load_client_credentials(self, service):
        """Load OAuth client ID and secret from environment."""
        prov = APP_PROVIDERS.get(service)
        if not prov:
            raise ValueError(f"Unknown provider: {service}")
        cid_env = prov.get("client_id_env")
        cs_env = prov.get("client_secret_env")
        client_id = os.getenv(cid_env) if cid_env else None
        client_secret = os.getenv(cs_env) if cs_env else None
        if not client_id or not client_secret:
            raise ValueError(
                f"Missing credentials for {service}: "
                f"set {cid_env} and {cs_env}"
            )
        return client_id, client_secret

    def _build_scopes(self, service, sub_services=None):
        """Combine base scopes and selected sub-service scopes."""
        prov = APP_PROVIDERS.get(service)
        if not prov:
            return []
        scope_list = list(prov.get("base_scopes", prov.get("scopes", [])))
        if sub_services and "sub_services" in prov:
            for sk in sub_services:
                ss = prov["sub_services"].get(sk)
                if ss:
                    scope_list.extend(ss.get("scopes", []))
        seen = set()
        return [s for s in scope_list if not (s in seen or seen.add(s))]

    # ── OAuth Authorization URL ─────────────────────────────

    def get_authorization_url(self, user_id, service, redirect_uri,
                               scopes=None, sub_services=None):
        """Generate an OAuth 2.0 authorization URL with PKCE.

        For suite providers (Google, Microsoft), pass *sub_services* to
        request combined scopes in a single consent screen.
        Returns (authorization_url, state).
        """
        prov = self._get_client_config(service)
        client_id, _ = self._load_client_credentials(service)

        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)
        state = secrets.token_urlsafe(32)

        final_scopes = scopes or self._build_scopes(service, sub_services)
        scope_str = " ".join(final_scopes) if final_scopes else ""

        self.db.create_oauth_state(
            user_id=user_id,
            service=service,
            state=state,
            code_verifier=code_verifier,
            scopes=scope_str,
            redirect_uri=redirect_uri,
        )

        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scope_str:
            params["scope"] = scope_str

        auth_url = f"{prov['authorize_url']}?{urlencode(params)}"
        return auth_url, state

    # ── Token Exchange ──────────────────────────────────────

    def exchange_code(self, user_id, service, authorization_code, redirect_uri):
        """Exchange an authorization code for tokens (basic, no PKCE)."""
        prov = self._get_client_config(service)
        client_id, client_secret = self._load_client_credentials(service)

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            resp = requests.post(prov["token_url"], data=payload, timeout=30)
            data = resp.json()
        except Exception as e:
            return False, f"Token exchange failed: {e}", None

        if "access_token" not in data and "error" in data:
            return False, data.get("error_description", data["error"]), None
        if "access_token" not in data:
            return False, "No access_token in response", None

        conn_id = self._store_tokens(user_id, service, data)
        return True, "Connected successfully", {"connection_id": conn_id, "service": service}

    def exchange_code_with_state(self, user_id, service, authorization_code,
                                  state, redirect_uri):
        """Exchange an authorization code using PKCE (verifier from state)."""
        prov = self._get_client_config(service)
        client_id, client_secret = self._load_client_credentials(service)

        state_data = self.db.consume_oauth_state(state)
        if not state_data:
            return False, "OAuth state not found or expired — restart the connection flow", None

        code_verifier = state_data["code_verifier"]
        stored_scopes = state_data.get("scopes", "")

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }

        try:
            resp = requests.post(prov["token_url"], data=payload, timeout=30)
            data = resp.json()
        except Exception as e:
            return False, f"Token exchange failed: {e}", None

        if "access_token" not in data and "error" in data:
            return False, data.get("error_description", data["error"]), None
        if "access_token" not in data:
            return False, "No access_token in response", None

        conn_id = self._store_tokens(user_id, service, data, scopes=stored_scopes)
        return True, "Connected successfully", {"connection_id": conn_id, "service": service}

    def _store_tokens(self, user_id, service, token_data, scopes=None):
        """Encrypt and store OAuth token data as a new connection."""
        credentials = {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "token_type": token_data.get("token_type", "Bearer"),
            "scope": token_data.get("scope", scopes or ""),
        }
        encrypted = self.encrypt_credentials(credentials)
        provider = self.get_provider(service)
        expires_in = token_data.get("expires_in")
        expires_at = None
        if expires_in:
            expires_at = (datetime.utcnow() + timedelta(seconds=int(expires_in))).isoformat()

        return self.db.create_connection(
            user_id=user_id,
            service=service,
            service_type=provider["auth_type"] if provider else "oauth2",
            credentials_encrypted=encrypted,
            label=provider["name"] if provider else service,
            scopes=scopes or "",
        )

    # ── API Key Connection ──────────────────────────────────

    def connect_api_key(self, user_id, service, api_key, api_base_url=None,
                         label=None):
        """Store a connection using an API key (non-OAuth providers)."""
        prov = self.get_provider(service)
        if not prov:
            return False, f"Unknown provider: {service}", None
        if prov.get("auth_type") != "api_key":
            return False, f"{service} does not support API key connections", None

        metadata = {}
        if api_base_url:
            metadata["api_base_url"] = api_base_url

        credentials = {"api_key": api_key}
        if metadata:
            credentials["metadata"] = metadata

        encrypted = self.encrypt_credentials(credentials)
        display_label = label or prov["name"]

        conn_id = self.db.create_connection(
            user_id=user_id,
            service=service,
            service_type="api_key",
            credentials_encrypted=encrypted,
            label=display_label,
            scopes=None,
        )
        return True, f"Connected to {prov['name']}", {"connection_id": conn_id}

    # ── Connection CRUD ─────────────────────────────────────

    def get_connection(self, connection_id, user_id):
        """Get a connection with decrypted credentials."""
        row = self.db.get_connection(connection_id, user_id)
        if not row:
            return None
        try:
            row["credentials"] = self.decrypt_credentials(row["credentials_encrypted"])
        except Exception:
            row["credentials"] = {"error": "decryption_failed"}
        row.pop("credentials_encrypted", None)

        if row.get("scopes"):
            try:
                parsed = json.loads(row["scopes"])
                if isinstance(parsed, list):
                    row["sub_services"] = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        return row

    def list_connections(self, user_id, service=None):
        """List connections without exposing credentials."""
        rows = self.db.get_connections_for_user(user_id, service=service)
        result = []
        for r in rows:
            entry = {
                "id": r["id"],
                "service": r["service"],
                "service_type": r["service_type"],
                "label": r["label"],
                "status": r["status"],
                "expires_at": r["expires_at"],
                "last_verified_at": r["last_verified_at"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            if r.get("scopes"):
                try:
                    parsed = json.loads(r["scopes"])
                    if isinstance(parsed, list):
                        entry["sub_services"] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass
            prov = self.get_provider(r["service"])
            if prov:
                entry["provider_name"] = prov["name"]
                entry["category"] = prov["category"]
            result.append(entry)
        return result

    def update_connection(self, connection_id, user_id, **kwargs):
        """Update connection metadata. Re-encrypts if 'credentials' passed."""
        if "credentials" in kwargs:
            kwargs["credentials_encrypted"] = self.encrypt_credentials(
                kwargs.pop("credentials")
            )
        if "sub_services" in kwargs:
            kwargs["scopes"] = json.dumps(kwargs.pop("sub_services"))
        return self.db.update_connection(connection_id, user_id, **kwargs)

    def delete_connection(self, connection_id, user_id):
        """Remove a connection."""
        return self.db.delete_connection(connection_id, user_id)

    def check_connection_limit(self, user_id, plan="free"):
        """Check if user has reached their connection limit."""
        current = self.db.count_connections(user_id)
        limit = CONNECTION_LIMITS.get(plan, 3)
        return current < limit, current, limit

    # ── Token Refresh ───────────────────────────────────────

    def refresh_expired_token(self, connection_id, user_id):
        """Refresh an expired OAuth token using the stored refresh token."""
        row = self.db.get_connection(connection_id, user_id)
        if not row:
            return False, "Connection not found"

        try:
            creds = self.decrypt_credentials(row["credentials_encrypted"])
        except Exception:
            return False, "Failed to decrypt credentials"

        refresh_token = creds.get("refresh_token")
        if not refresh_token:
            return False, "No refresh token — reconnect the service"

        prov = self._get_client_config(row["service"])
        client_id, client_secret = self._load_client_credentials(row["service"])

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            resp = requests.post(prov["token_url"], data=payload, timeout=30)
            data = resp.json()
        except Exception as e:
            return False, f"Token refresh failed: {e}"

        if "access_token" not in data:
            return False, "Token refresh denied — reconnect"

        creds["access_token"] = data["access_token"]
        if data.get("refresh_token"):
            creds["refresh_token"] = data["refresh_token"]

        encrypted = self.encrypt_credentials(creds)
        expires_in = data.get("expires_in")
        expires_at = None
        if expires_in:
            expires_at = (datetime.utcnow() + timedelta(seconds=int(expires_in))).isoformat()

        self.db.update_connection(
            connection_id, user_id,
            credentials_encrypted=encrypted,
            expires_at=expires_at,
            last_verified_at=datetime.utcnow().isoformat(),
        )
        return True, "Token refreshed"

    # ── AI Context Injection ────────────────────────────────

    def get_connection_context(self, user_id, services=None):
        """Build a structured context dict for AI system prompts.

        Returns a dict mapping provider → metadata (no credentials exposed).
        """
        rows = self.db.get_connections_for_user(user_id)
        context = {}
        for r in rows:
            if services and r["service"] not in services:
                continue
            if r["status"] != "active":
                continue

            prov = self.get_provider(r["service"])
            entry = {
                "service": r["service"],
                "provider": prov["name"] if prov else r["service"],
                "category": prov["category"] if prov else "unknown",
                "status": r["status"],
                "auth_type": r["service_type"],
                "connected_at": r["created_at"],
            }
            if r.get("scopes"):
                try:
                    parsed = json.loads(r["scopes"])
                    if isinstance(parsed, list):
                        entry["sub_services"] = parsed
                        if prov and "sub_services" in prov:
                            entry["sub_service_names"] = [
                                prov["sub_services"].get(s, {}).get("name", s)
                                for s in parsed if s in prov["sub_services"]
                            ]
                except (json.JSONDecodeError, TypeError):
                    pass

            context[r["service"]] = entry

        return context
