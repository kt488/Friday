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
        self._rag = None  # Lazy initialized RAG pipeline

    def _get_rag(self):
        if self._rag is None:
            try:
                from core.rag.pipeline import RAGPipeline
                self._rag = RAGPipeline()
                self._rag.initialize()
            except Exception as e:
                print(f"[*] RAG init error (non-fatal): {e}")
                self._rag = False  # Mark as unavailable
        return self._rag if self._rag else None

    def _extract_agent_tag(self, text):
        """Check for [AGENT: name] or [CLEAR_AGENT] tags in user input.
        Returns (cleaned_text, agent_name_or_none).
        """
        if "[CLEAR_AGENT]" in text:
            text = text.replace("[CLEAR_AGENT]", "").strip()

        m = re.search(r'\[AGENT:\s*(\w+[\w-]*)\]', text)
        if m:
            agent_name = m.group(1).strip()
            text = re.sub(r'\[AGENT:\s*\w+[\w-]*\]', '', text).strip()
            return text, agent_name

        return text, None

    def process_message(self, user_text, image_path=None,
                        conversation_context=None, agent_name=None):
        """Non-streaming process. All context must be passed in."""
        full = ""
        for chunk in self.process_message_stream(
            user_text, image_path=image_path,
            conversation_context=conversation_context, agent_name=agent_name
        ):
            full += chunk
        return full

    def process_message_stream(self, user_text, image_path=None,
                                conversation_context=None, agent_name=None,
                                rag_workspace_id=None, rag_user_id=None):
        """Core streaming pipeline — fully stateless.

        All conversation context must be passed in via ``conversation_context``
        (a list of dicts with ``role`` and ``message`` keys).  No database
        lookups or writes are performed for conversation state.

        RAG: If ``rag_workspace_id`` or ``rag_user_id`` is provided, the RAG
        engine enriches the prompt with retrieved knowledge before generation.
        """
        # 1. Use provided conversation context or empty
        history = conversation_context or []

        # 2. Check for agent tags in user input
        cleaned_text, agent_tag = self._extract_agent_tag(user_text)
        active_agent = agent_tag or agent_name
        user_input = cleaned_text or user_text

        # 3. Load active agent prompt if one is set
        agent_prompt = ""
        if active_agent:
            agent_prompt = self.brain.load_agent_prompt(active_agent) or ""

        # 4. Load MCP tools + domain skills
        mcp_desc = self.executive.mcp.get_all_tools_description()
        skills_desc = self.executive.get_all_skills_description()
        extra_tools = "\n".join(filter(None, [mcp_desc, skills_desc]))

        # 5. RAG enrichment
        rag = self._get_rag()
        rag_context = ""
        if rag and (rag_workspace_id or rag_user_id):
            try:
                ctx = rag.query(
                    user_input,
                    workspace_id=rag_workspace_id or "default",
                    user_id=rag_user_id,
                    conversation_context=history,
                )
                if ctx.context_text:
                    rag_context = ctx.context_text
            except Exception as e:
                print(f"[*] RAG query error (non-fatal): {e}")

        # Inject RAG context into user input
        if rag_context:
            user_input = (
                f"{rag_context}\n"
                f"## User Query\n{user_input}"
            )

        # 6. Stream from brain
        full_response = ""
        for chunk in self.brain.generate_stream(
            user_input,
            image_path=image_path,
            history=history,
            extra_tools=extra_tools,
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

        # 8. Handle file delivery from metadata — emit clean SEND_FILE_NOW tag
        if metadata and metadata.get("type") == "file":
            yield f"\n[SEND_FILE_NOW: {metadata['filepath']}]\n"

    def process_website_message_stream(self, slug, user_text, session_id,
                                        image_path=None, conversation_context=None):
        """Streaming pipeline for a tenant website's chatbot — stateless.

        Uses the website's persona/business-info to build the system prompt.
        No messages are persisted; context must be passed in.
        """
        site = self.tenants.get(slug)
        if not site:
            yield "[Error: Website not found]"
            return

        system_prompt = self.tenants.build_system_prompt(slug)
        mcp_desc = self.executive.mcp.get_all_tools_description()
        skills_desc = self.executive.get_all_skills_description()
        extra_tools = "\n".join(filter(None, [mcp_desc, skills_desc]))
        history = conversation_context or []

        full_response = ""
        for chunk in self.brain.generate_stream(
            user_text,
            image_path=image_path,
            history=history,
            extra_tools=extra_tools,
            system_prompt_override=system_prompt
        ):
            full_response += chunk
            yield chunk

        # Post-process: execute tools and handle file delivery
        processed, tool_used, metadata = self.executive.parse_and_execute(full_response)

        if processed != full_response:
            extra = processed[len(full_response):]
            if extra.strip():
                yield extra

        # Handle file delivery from metadata
        if metadata and metadata.get("type") == "file":
            yield f"\n[SEND_FILE_NOW: {metadata['filepath']}]\n"

    def process_website_message(self, slug, user_text, session_id,
                                 image_path=None, conversation_context=None):
        """Non-streaming wrapper for website-scoped chat."""
        full = ""
        for chunk in self.process_website_message_stream(
            slug, user_text, session_id, image_path=image_path,
            conversation_context=conversation_context
        ):
            full += chunk
        return full
