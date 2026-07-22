import os
import re
import uuid
from datetime import datetime
from core.database import Database
from core.brain import FridayBrain
from core.executive import FridayExecutive
from core.tenant_manager import TenantManager
from core.memory_system import PersistentMemory, MemoryDomain, TaskStatus


class FridayCore:
    def __init__(self):
        self.db = Database()
        self.brain = FridayBrain()
        self.executive = FridayExecutive()
        self.tenants = TenantManager(self.db)
        self._rag = None  # Lazy initialized RAG pipeline
        self.memory = PersistentMemory(db_path="data/persistent_memory.db")

    def get_memory_context(self, user_text: str, conv_id: str) -> str:
        """Gather relevant memory context for prompt injection."""
        parts = []

        # 1. Conversation history summary
        conv_ctx = self.memory.get_conversation_context(conv_id)
        if conv_ctx:
            decisions = conv_ctx.get("decisions", [])
            if decisions:
                parts.append("Previous decisions: " + "; ".join(decisions[-3:]))

        # 2. Relevant memory search
        mem_context = self.memory.get_relevant_context(user_text, max_items=5)
        if mem_context:
            parts.append(mem_context)

        # 3. Active tasks summary
        active = self.memory.list_tasks(TaskStatus.ACTIVE)
        if active:
            parts.append("Active tasks:\n" + "\n".join(
                f"  - {t.description} {'[' + t.project + ']' if t.project else ''}"
                for t in active[:5]
            ))

        # 4. Self-check
        check = self.memory.self_check(user_text)
        if not check["has_relevant_context"]:
            # No relevant memory found — don't inject empty context
            return ""

        return "\n\n".join(parts)

    def _extract_memories_from_exchange(self, user_text: str, response: str, conv_id: str) -> None:
        """Auto-extract important information from a conversation exchange."""
        # Store the conversation turn as context
        now = datetime.utcnow().isoformat() + "Z"

        # Extract potential user preferences from the message
        pref_patterns = [
            r"(?:I |we |my |our ).*?(?:like|prefer|want|need|use|have|don't like|hate|dislike)\s+(.+?)[\.!]",
            r"(?:call me|my name is|I'm|I am)\s+(.+?)[\.!]",
            r"(?:favorite|preferred)\s+(.+?)(?:is|are)\s+(.+?)[\.!]",
        ]
        user_text_lower = user_text.lower()
        for pattern in pref_patterns:
            m = re.search(pattern, user_text, re.IGNORECASE)
            if m:
                self.memory.store(
                    key=f"preference:{m.group(0)[:60].strip()}",
                    value=m.group(0).strip(),
                    domain=MemoryDomain.PREFERENCE,
                    importance=0.6,
                    source="inference",
                    tags=["auto-extracted"],
                )

        # Detect project mentions
        project_match = re.search(r"(?:project|app|system|tool|called|named)\s+['\"]?(\w[\w\s-]{2,30}?)['\"]?", user_text, re.IGNORECASE)
        if project_match:
            proj_name = project_match.group(1).strip()
            self.memory.track_project(proj_name, f"Mentioned in conversation", tags=["auto-extracted"])

        # Detect task-like requests
        task_patterns = [
            r"(?:can you|please|could you|I need you to|your task is|your job is)\s+(.+?)[\.!]",
            r"(?:todo|to-do|to do):\s*(.+?)[\.!\n]",
        ]
        for pattern in task_patterns:
            m = re.search(pattern, user_text, re.IGNORECASE)
            if m:
                self.memory.create_task(
                    description=m.group(1).strip()[:100],
                    project=project_match.group(1).strip() if project_match else None,
                    priority=1,
                    tags=["auto-extracted"],
                )

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
                        conversation_context=None, agent_name=None,
                        conv_id=None):
        """Non-streaming process. All context must be passed in."""
        full = ""
        for chunk in self.process_message_stream(
            user_text, image_path=image_path,
            conversation_context=conversation_context, agent_name=agent_name,
            conv_id=conv_id
        ):
            full += chunk
        return full

    def process_message_stream(self, user_text, image_path=None,
                                conversation_context=None, agent_name=None,
                                rag_workspace_id=None, rag_user_id=None,
                                conv_id=None):
        """Core streaming pipeline — now with persistent memory.

        All conversation context must be passed in via ``conversation_context``
        (a list of dicts with ``role`` and ``message`` keys).  No database
        lookups or writes are performed for conversation state.

        RAG: If ``rag_workspace_id`` or ``rag_user_id`` is provided, the RAG
        engine enriches the prompt with retrieved knowledge before generation.

        Memory: If ``conv_id`` is provided, relevant memories are injected into
        the prompt before generation. Memories are auto-extracted afterward.
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

        # 4b. Persistent Memory — inject relevant context
        if conv_id:
            mem_context = self.get_memory_context(user_input, conv_id)
            if mem_context:
                extra_tools = extra_tools + "\n\n## Persistent Memory Context\n" + mem_context if extra_tools else "## Persistent Memory Context\n" + mem_context

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

        # 7. Post-process: execute tools, handle file delivery, process memory tags
        processed, tool_used, metadata = self.executive.parse_and_execute(full_response, memory=self.memory)

        # 7b. Persistent Memory — auto-extract from exchange
        if conv_id:
            try:
                self._extract_memories_from_exchange(user_input, full_response, conv_id)
                self.memory.summarize_conversation(
                    conv_id,
                    [{"role": "user", "message": user_input},
                     {"role": "assistant", "message": full_response[:500]}],
                )
            except Exception as e:
                print(f"[*] Memory extraction error (non-fatal): {e}")

        # Yield any tool execution markers that weren't already part of the stream
        if processed != full_response:
            extra = processed[len(full_response):]
            if extra.strip():
                yield extra

        # 8. Handle file delivery from metadata — emit clean SEND_FILE_NOW tag
        if metadata and metadata.get("type") == "file":
            yield f"\n[SEND_FILE_NOW: {metadata['filepath']}]\n"

    def process_website_message_stream(self, slug, user_text, session_id,
                                        image_path=None, conversation_context=None,
                                        conv_id=None):
        """Streaming pipeline for a tenant website's chatbot — stateless.

        Uses the website's persona/business-info to build the system prompt.
        No messages are persisted; context must be passed in.

        Memory: If ``conv_id`` is provided (or auto-derived from session_id),
        relevant memories are injected before generation and auto-extracted afterward.
        """
        site = self.tenants.get(slug)
        if not site:
            yield "[Error: Website not found]"
            return

        # Auto-generate conv_id from session_id if not provided
        if conv_id is None:
            conv_id = f"web:{slug}:{session_id}"

        system_prompt = self.tenants.build_system_prompt(slug)
        mcp_desc = self.executive.mcp.get_all_tools_description()
        skills_desc = self.executive.get_all_skills_description()
        extra_tools = "\n".join(filter(None, [mcp_desc, skills_desc]))
        history = conversation_context or []

        # Inject persistent memory context
        mem_context = self.get_memory_context(user_text, conv_id)
        if mem_context:
            extra_tools = extra_tools + "\n\n## Persistent Memory Context\n" + mem_context if extra_tools else "## Persistent Memory Context\n" + mem_context

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

        # Post-process: execute tools, handle file delivery, process memory tags
        processed, tool_used, metadata = self.executive.parse_and_execute(full_response, memory=self.memory)

        # Auto-extract memories from exchange
        try:
            self._extract_memories_from_exchange(user_text, full_response, conv_id)
            self.memory.summarize_conversation(
                conv_id,
                [{"role": "user", "message": user_text},
                 {"role": "assistant", "message": full_response[:500]}],
            )
        except Exception as e:
            print(f"[*] Memory extraction error (non-fatal): {e}")

        if processed != full_response:
            extra = processed[len(full_response):]
            if extra.strip():
                yield extra

        # Handle file delivery from metadata
        if metadata and metadata.get("type") == "file":
            yield f"\n[SEND_FILE_NOW: {metadata['filepath']}]\n"

    def process_website_message(self, slug, user_text, session_id,
                                 image_path=None, conversation_context=None,
                                 conv_id=None):
        """Non-streaming wrapper for website-scoped chat."""
        full = ""
        for chunk in self.process_website_message_stream(
            slug, user_text, session_id, image_path=image_path,
            conversation_context=conversation_context, conv_id=conv_id
        ):
            full += chunk
        return full
