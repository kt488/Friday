import os
import re
from core.database import Database
from core.brain import FridayBrain
from core.executive import FridayExecutive
from core.tenant_manager import TenantManager


class FridayCore:
    def __init__(self):
        self.db = Database()
        self.brain = FridayBrain()
        self.executive = FridayExecutive()
        self.tenants = TenantManager(self.db)
        self._active_agent = None
        self._last_conversation_id = None

    def _extract_agent_tag(self, text):
        """Check for [AGENT: name] or [CLEAR_AGENT] tags in user input.
        Returns (cleaned_text, agent_name_or_none).
        """
        # Check for clear agent tag
        if "[CLEAR_AGENT]" in text:
            self._active_agent = None
            text = text.replace("[CLEAR_AGENT]", "").strip()

        # Check for agent activation
        m = re.search(r'\[AGENT:\s*(\w+[\w-]*)\]', text)
        if m:
            agent_name = m.group(1).strip()
            text = re.sub(r'\[AGENT:\s*\w+[\w-]*\]', '', text).strip()
            return text, agent_name

        return text, None

    def process_message(self, user_text, image_path=None, user_id=None, conversation_id=None):
        """Legacy non-streaming process."""
        full = ""
        for chunk in self.process_message_stream(user_text, image_path=image_path, user_id=user_id, conversation_id=conversation_id):
            full += chunk
        return full

    def process_message_stream(self, user_text, image_path=None, user_id=None, conversation_id=None):
        """Core streaming pipeline: load user-scoped context, stream LLM response,
        execute tools, yield final output."""
        # 1. Validate or auto-create conversation
        if user_id and not conversation_id:
            conversation_id = self.db.create_conversation(user_id)
        elif user_id and conversation_id:
            # Verify conversation belongs to this user
            conv = self.db.get_conversation(user_id, conversation_id)
            if not conv:
                conversation_id = self.db.create_conversation(user_id)
        self._last_conversation_id = conversation_id

        # 2. Load conversation history (last 10 messages, scoped to user + conversation)
        if user_id and conversation_id:
            history = self.db.get_conversation_history(user_id=user_id, conversation_id=conversation_id, limit=10)
        else:
            history = self.db.get_conversation_history(limit=10)  # legacy fallback

        # 2. Check for agent tags in user input
        cleaned_text, agent_tag = self._extract_agent_tag(user_text)
        if agent_tag:
            self._active_agent = agent_tag
        user_input = cleaned_text or user_text

        # 3. Load active agent prompt if one is set
        agent_prompt = ""
        if self._active_agent:
            agent_prompt = self.brain.load_agent_prompt(self._active_agent) or ""

        # 4. Save user message to both databases
        self.db.save_message("user", user_input, user_id=user_id, conversation_id=conversation_id)
        try:
            self.executive.supabase.save_message("user", user_input, user_id=user_id, conversation_id=conversation_id)
        except Exception:
            pass

        # 5. Load MCP tools description
        mcp_desc = self.executive.mcp.get_all_tools_description()

        # 6. Stream from brain
        full_response = ""
        for chunk in self.brain.generate_stream(
            user_input,
            image_path=image_path,
            history=history,
            extra_tools=mcp_desc,
            agent_prompt=agent_prompt
        ):
            full_response += chunk
            yield chunk

        # 7. Post-process: execute tools and handle file delivery
        processed, tool_used, metadata = self.executive.parse_and_execute(full_response)

        # Yield any tool execution markers that weren't already part of the stream
        if processed != full_response:
            extra = processed[len(full_response):]
            if extra.strip():
                yield extra

        # 8. Save final response to both databases
        # Strip internal markers from the saved response text
        save_text = re.sub(r'(?:\[TOOL:|\*\*TOOL:).*?(?:\]|\*\*)', '', processed, flags=re.DOTALL)
        save_text = re.sub(r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:).*?(?:\]|\*\*)', '', save_text, flags=re.DOTALL)
        save_text = re.sub(r'(?:\[Executed|\*\*\[?Executed).*?(?:\]|\*\*)', '', save_text, flags=re.DOTALL)
        save_text = save_text.strip()
        if save_text:
            self.db.save_message("friday", save_text, user_id=user_id, conversation_id=conversation_id)
            try:
                self.executive.supabase.save_message("friday", save_text, user_id=user_id, conversation_id=conversation_id)
            except Exception:
                pass

    def clear_history(self, user_id=None, conversation_id=None):
        """Delete conversation history scoped to user + conversation."""
        self.db.clear_conversation_history(user_id=user_id, conversation_id=conversation_id)
        return True

    def process_website_message_stream(self, slug, user_text, session_id, image_path=None):
        """Streaming pipeline for a tenant website's chatbot.

        Uses the website's persona/business-info to build the system prompt
        and saves messages scoped to the website + session.
        """
        site = self.tenants.get(slug)
        if not site:
            yield "[Error: Website not found]"
            return

        website_id = site["id"]
        system_prompt = self.tenants.build_system_prompt(slug)

        # Load MCP tools description
        mcp_desc = self.executive.mcp.get_all_tools_description()

        # Save user message scoped to website session
        self.db.save_website_message(website_id, session_id, "user", user_text)

        # Stream from brain with website system prompt
        full_response = ""
        for chunk in self.brain.generate_stream(
            user_text,
            image_path=image_path,
            history=[],  # website sessions don't use main conversation history
            extra_tools=mcp_desc,
            agent_prompt=system_prompt,
            system_prompt_override=system_prompt
        ):
            full_response += chunk
            yield chunk

        # Post-process: execute tools and handle file delivery
        processed, tool_used, metadata = self.executive.parse_and_execute(full_response)

        # Yield extra tool execution markers
        if processed != full_response:
            extra = processed[len(full_response):]
            if extra.strip():
                yield extra

        # Save final response
        save_text = re.sub(r'(?:\[TOOL:|\*\*TOOL:).*?(?:\]|\*\*)', '', processed, flags=re.DOTALL)
        save_text = re.sub(r'(?:\[SEND_FILE_NOW:|\*\*SEND_FILE_NOW:).*?(?:\]|\*\*)', '', save_text, flags=re.DOTALL)
        save_text = re.sub(r'(?:\[Executed|\*\*\[?Executed).*?(?:\]|\*\*)', '', save_text, flags=re.DOTALL)
        save_text = save_text.strip()
        if save_text:
            self.db.save_website_message(website_id, session_id, "assistant", save_text)

    def process_website_message(self, slug, user_text, session_id, image_path=None):
        """Non-streaming wrapper for website-scoped chat."""
        full = ""
        for chunk in self.process_website_message_stream(slug, user_text, session_id, image_path=image_path):
            full += chunk
        return full
