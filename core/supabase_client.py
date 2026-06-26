import requests
import os
import json
import uuid
from datetime import datetime

class SupabaseClient:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.enabled = bool(self.url and self.key)
        self._bucket_cache = set()

    def _headers(self, content_type="application/json"):
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": content_type,
            "Prefer": "return=minimal"
        }

    # ── Bucket management ──

    def ensure_bucket(self, bucket="friday-files", public=True):
        """Create the storage bucket if it doesn't exist."""
        if not self.enabled or bucket in self._bucket_cache:
            return True

        # Check if bucket exists
        res = requests.get(
            f"{self.url}/storage/v1/bucket/{bucket}",
            headers=self._headers()
        )
        if res.status_code == 200:
            self._bucket_cache.add(bucket)
            return True

        # Create it
        res = requests.post(
            f"{self.url}/storage/v1/bucket",
            headers=self._headers(),
            json={"name": bucket, "public": public}
        )
        if res.status_code in (200, 201):
            self._bucket_cache.add(bucket)
            return True

        print(f"[Supabase] Failed to create bucket '{bucket}': {res.text}")
        return False

    # ── Storage operations ──

    def upload_file(self, local_path, remote_name=None, bucket="friday-files"):
        """Upload a file to Supabase Storage. Returns the public URL or None."""
        if not self.enabled or not os.path.exists(local_path):
            return None

        if not self.ensure_bucket(bucket):
            return None

        if remote_name is None:
            remote_name = os.path.basename(local_path)

        # Prefix with a date folder and unique ID to avoid collisions
        date_prefix = datetime.now().strftime("%Y/%m/%d")
        unique_name = f"{uuid.uuid4().hex[:8]}_{remote_name}"
        remote_path = f"{date_prefix}/{unique_name}"

        with open(local_path, "rb") as f:
            res = requests.post(
                f"{self.url}/storage/v1/object/{bucket}/{remote_path}",
                headers={
                    "apikey": self.key,
                    "Authorization": f"Bearer {self.key}",
                },
                files={"file": (remote_name, f)}
            )

        if res.status_code in (200, 201):
            return self.get_public_url(remote_path, bucket)
        else:
            print(f"[Supabase] Upload failed: {res.status_code} {res.text}")
            return None

    def get_public_url(self, remote_path, bucket="friday-files"):
        """Get the public URL for a file in Supabase Storage."""
        if not self.enabled:
            return None
        return f"{self.url}/storage/v1/object/public/{bucket}/{remote_path}"

    def download_file(self, remote_path, local_path, bucket="friday-files"):
        """Download a file from Supabase Storage to a local path."""
        if not self.enabled:
            return False

        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)

        res = requests.get(
            f"{self.url}/storage/v1/object/{bucket}/{remote_path}",
            headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        )

        if res.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(res.content)
            return True

        print(f"[Supabase] Download failed: {res.status_code} {res.text}")
        return False

    def list_files(self, bucket="friday-files", prefix=""):
        """List files in a bucket, optionally filtered by prefix."""
        if not self.enabled:
            return []

        res = requests.post(
            f"{self.url}/storage/v1/object/list/{bucket}",
            headers=self._headers(),
            json={"prefix": prefix, "sortBy": {"column": "created_at", "order": "desc"}}
        )

        if res.status_code == 200:
            return res.json()
        return []

    def delete_file(self, remote_path, bucket="friday-files"):
        """Delete a file from Supabase Storage."""
        if not self.enabled:
            return False

        res = requests.delete(
            f"{self.url}/storage/v1/object/{bucket}/{remote_path}",
            headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        )

        return res.status_code in (200, 204)

    # ── Legacy: log file metadata to DB table ──

    def log_file(self, filename, path, size, download_url):
        """Logs file metadata to the 'friday_files' table."""
        if not self.enabled:
            return

        endpoint = f"{self.url}/rest/v1/friday_files"
        headers = self._headers()

        data = {
            "name": filename,
            "local_path": path,
            "size": size,
            "download_url": download_url,
            "created_at": datetime.now().isoformat()
        }

        try:
            res = requests.post(endpoint, headers=headers, json=data)
            res.raise_for_status()
            return True
        except Exception as e:
            print(f"[Supabase] Error logging file: {e}")
            return False

    # ── Conversation history ──

    def save_message(self, role, message):
        """Logs conversation history to 'friday_history' table."""
        if not self.enabled:
            return

        endpoint = f"{self.url}/rest/v1/friday_history"
        headers = self._headers()

        data = {
            "role": role,
            "content": message,
            "timestamp": datetime.now().isoformat()
        }

        try:
            requests.post(endpoint, headers=headers, json=data)
        except Exception:
            pass
