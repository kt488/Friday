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

    def process_message_stream(self, user_text, image_path=None):
        """Core streaming pipeline: load context, stream LLM response,
        execute tools, yield final output."""
        # 1. Load conversation history (last 10 messages)
        history = self.db.get_conversation_history(limit=10)

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
        self.db.save_message("user", user_input)
        try:
            self.executive.supabase.save_message("user", user_input)
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
            self.db.save_message("friday", save_text)
            try:
                self.executive.supabase.save_message("friday", save_text)
            except Exception:
                pass

    def process_message(self, user_text, image_path=None):
        """Non-streaming wrapper — collects all chunks and returns (response, metadata).

        Metadata is populated when a file is generated (via [SEND_FILE_NOW: path]).
        """
        full_response = ""
        for chunk in self.process_message_stream(user_text, image_path=image_path):
            full_response += chunk

        # Extract file metadata from SEND_FILE_NOW markers
        metadata = None
        file_match = re.search(r'\[SEND_FILE_NOW:\s*(.*?)\]', full_response)
        if file_match:
            file_path = file_match.group(1).strip()
            if (file_path.startswith('"') and file_path.endswith('"')) or \
               (file_path.startswith("'") and file_path.endswith("'")):
                file_path = file_path[1:-1]
            if os.path.exists(file_path):
                metadata = {
                    "type": "file",
                    "filename": os.path.basename(file_path),
                    "filepath": file_path
                }

        return full_response, metadata

    def clear_history(self):
        """Delete all conversation history from the local database."""
        self.db.clear_conversations()
        return True
