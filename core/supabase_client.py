import requests
import os
import json
from datetime import datetime

class SupabaseClient:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.enabled = bool(self.url and self.key)
        
    def log_file(self, filename, path, size, download_url):
        """Logs file metadata to the 'friday_files' table."""
        if not self.enabled:
            return
            
        endpoint = f"{self.url}/rest/v1/friday_files"
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
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

    def save_message(self, role, message):
        """Logs conversation history to 'friday_history' table."""
        if not self.enabled:
            return
            
        endpoint = f"{self.url}/rest/v1/friday_history"
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "role": role,
            "content": message,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            requests.post(endpoint, headers=headers, json=data)
        except Exception:
            pass
