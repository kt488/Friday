"""
Tenant Manager — Multi-Website Engine
======================================
Handles website configuration, scoped conversations, lead capture,
and building per-website system prompts for the LLM.
"""

import json
import re
from core.database import Database


class TenantManager:
    def __init__(self, db: Database):
        self.db = db
        self._cache = {}

    # ── Website CRUD ──

    def register(self, slug, name, **kwargs):
        """Register a new website."""
        wid = self.db.add_website(slug, name, **kwargs)
        if wid:
            self._cache.pop(slug, None)
        return wid

    def get(self, slug):
        """Get website config (cached)."""
        if slug not in self._cache:
            self._cache[slug] = self.db.get_website(slug)
        return self._cache[slug]

    def get_by_id(self, wid):
        return self.db.get_website_by_id(wid)

    def update(self, slug, **kwargs):
        result = self.db.update_website(slug, **kwargs)
        if result:
            self._cache.pop(slug, None)
        return result

    def delete(self, slug):
        result = self.db.delete_website(slug)
        if result:
            self._cache.pop(slug, None)
        return result

    def list_all(self):
        return self.db.list_websites()

    # ── Persona / System Prompt Builder ──

    def build_system_prompt(self, slug):
        """Build a system prompt for a website's chatbot persona.

        Merges the website config into a context string that the LLM
        uses to behave as that website's assistant.
        """
        site = self.get(slug)
        if not site:
            return None

        bot_name = site.get("bot_name", "Assistant")
        persona = site.get("persona", "")
        business_info = site.get("business_info", "")
        greeting = site.get("greeting_message", "Hello! How can I help you?")
        name = site.get("name", slug)

        lines = [
            f"You are {bot_name}, the AI assistant for {name}.",
            "",
            "CORE RULES:",
            "- You are NOT an AI language model. You are the website's helpful assistant.",
            "- Never mention 'Friday', 'AI', 'language model', or any technical backend details.",
            "- Never reference conversations from other websites or sessions.",
            "- Every conversation is independent and private — treat it that way.",
            f"- Your greeting is: \"{greeting}\"",
            "",
        ]

        if persona:
            lines.append(f"PERSONA:\n{persona}\n")

        if business_info:
            lines.append(f"BUSINESS INFORMATION:\n{business_info}\n")

        lines.extend([
            "LEAD CAPTURE:",
            "- When a visitor wants to buy, book, get a quote, or be contacted: capture the lead.",
            "- Ask for name, email, and phone — no more than necessary.",
            "- Save via [TOOL: save_lead({...})] — include name, email, phone, and any message.",
            "- Confirm to the visitor that someone will follow up.",
            "",
            "STYLE:",
            "- Be concise, helpful, and match the website's brand tone.",
            "- Use markdown formatting in responses.",
            "- End with a question when appropriate to keep the conversation flowing.",
            "- If you don't know something, be honest: offer to connect them with a human.",
        ])

        return "\n".join(lines)

    # ── Scoped Conversations ──

    def save_message(self, slug, session_id, role, message):
        site = self.get(slug)
        if not site:
            return False
        self.db.save_website_message(site["id"], session_id, role, message)
        return True

    def get_conversation(self, slug, session_id, limit=20):
        site = self.get(slug)
        if not site:
            return []
        return self.db.get_website_conversation(site["id"], session_id, limit=limit)

    # ── Lead Management ──

    def save_lead(self, slug, name="", email="", phone="", message="", metadata=None):
        site = self.get(slug)
        if not site:
            return None
        return self.db.save_lead(site["id"], name, email, phone, message, metadata)

    def get_leads(self, slug, limit=50):
        site = self.get(slug)
        if not site:
            return []
        return self.db.get_leads(site["id"], limit=limit)

    def update_lead_status(self, lead_id, status):
        return self.db.update_lead_status(lead_id, status)

    def invalidate_cache(self, slug=None):
        if slug:
            self._cache.pop(slug, None)
        else:
            self._cache.clear()
