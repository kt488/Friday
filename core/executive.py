from tools.system import get_tool_map
from core.mcp_client import MCPManager
from core.supabase_client import SupabaseClient
from core.memory_system import MemoryDomain
from harness.domain_skills import get_registry as get_skill_registry


class FridayExecutive:
    def __init__(self):
        self.tool_map = get_tool_map()
        self.mcp = MCPManager()
        self.mcp.start_clients()
        self.supabase = SupabaseClient()

        # Domain skills registry — indexes harness/domain_skills/ markdown
        try:
            self.skills = get_skill_registry()
        except Exception as e:
            print(f"[*] Domain skills registry init error (non-fatal): {e}")
            self.skills = None

    def get_all_skills_description(self) -> str:
        """Return a formatted string of available domain skills for the system prompt."""
        if not self.skills:
            return ""

        lines = ["\n--- Domain Skills (domain-specific expertise) ---"]
        for s in self.skills.summaries():
            # s: {domain, title, file, workflows}
            wf = s["workflows"]
            wf_hint = f" — {wf[0]}" if wf else ""
            lines.append(f"- [{s['domain']}] {s['title']}{wf_hint}")
        return "\n".join(lines)

    def handle_tool_call(self, tool_name, args=None):
        """Executes a tool by name and returns the result."""
        if tool_name in self.mcp.tool_map:
            return self.mcp.handle_mcp_tool(tool_name, args)
            
        if tool_name not in self.tool_map:
            return f"Error: Tool '{tool_name}' not found."

        try:
            if args is not None:
                # Handle dictionary (kwargs)
                if isinstance(args, dict):
                    return self.tool_map[tool_name](**args)
                # Handle tuple/list (positional args)
                elif isinstance(args, (tuple, list)):
                    return self.tool_map[tool_name](*args)
                # Handle single argument
                else:
                    return self.tool_map[tool_name](args)
            else:
                return self.tool_map[tool_name]()
        except Exception as e:
            return f"Execution error in tool '{tool_name}': {e}"

    def parse_and_execute(self, response_text, memory=None):
        """
        Looks for tool calling, file sending, and memory patterns in the AI's response.
        Processes ALL tool calls FIRST (to create files), then handles file sending,
        then processes memory tags.

        Patterns:
        - [TOOL: function_name("arg1", "arg2")]
        - [SEND_FILE: path]
        - [MEMORY: key=value]
        - [MEMORY: decision=...]
        - [MEMORY: task=...]
        - [MEMORY: correction=...]
        - [MEMORY: list_tasks]
        """
        import re
        import os
        import shutil
        import ast
        import json

        result_text = response_text
        tool_used = False
        metadata = None

        # 1. Process ALL [TOOL: ...] or **TOOL: ...** tags first (they create files, run commands, etc.)
        tool_pattern = r"(?:\[TOOL:|\*\*TOOL:)\s*(\w+)\((.*?)\)(?:\]|\*\*)"

        def replace_tool(match):
            nonlocal tool_used
            tool_name = match.group(1)
            raw_args = match.group(2).strip()

            args = None
            if raw_args:
                if raw_args.startswith("{") and raw_args.endswith("}"):
                    try:
                        args = json.loads(raw_args)
                    except:
                        pass
                if args is None:
                    try:
                        if "," in raw_args and not (raw_args.startswith("[") or raw_args.startswith("{")):
                            args = ast.literal_eval(f"({raw_args})")
                        else:
                            args = ast.literal_eval(raw_args)
                    except Exception:
                        # Handle multiline strings with actual newlines
                        if '\n' in raw_args:
                            try:
                                args = ast.literal_eval(raw_args.replace('\n', '\\n'))
                            except:
                                args = raw_args
                        else:
                            args = raw_args

            result = self.handle_tool_call(tool_name, args)
            tool_used = True
            return f"\n[Executed {tool_name}: {result}]"

        result_text = re.sub(tool_pattern, replace_tool, result_text, flags=re.DOTALL)

        # 2. Process ALL [SEND_FILE: path] or **SEND_FILE: path** tags after (files should now exist)
        send_file_pattern = r"(?:\[SEND_FILE:|\*\*SEND_FILE:)\s*(.*?)(?:\]|\*\*)"
        temp_dir = os.path.abspath("temp")
        os.makedirs(temp_dir, exist_ok=True)

        def replace_send_file(match):
            nonlocal tool_used, metadata
            file_path = match.group(1).strip()
            if (file_path.startswith('"') and file_path.endswith('"')) or \
               (file_path.startswith("'") and file_path.endswith("'")):
                file_path = file_path[1:-1]

            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                # Keep a local copy in temp/ for sending via Telegram
                local_path = os.path.join(temp_dir, filename)
                if os.path.abspath(file_path) != os.path.abspath(local_path):
                    shutil.copy2(file_path, local_path)
                else:
                    local_path = file_path

                file_size = os.path.getsize(local_path)

                # Upload to Supabase Storage silently (for persistence, not exposed to user)
                try:
                    public_url = self.supabase.upload_file(local_path, bucket="friday-files")
                    self.supabase.log_file(filename, local_path, file_size, public_url or "")
                except Exception:
                    pass

                tool_used = True
                metadata = {
                    "type": "file",
                    "filename": filename,
                    "filepath": local_path
                }
                # Return a marker with local path only — never expose URLs
                return f"\n[SEND_FILE_NOW: {local_path}]"
            else:
                return f"\n[Error: File not found at {file_path}]"

        result_text = re.sub(send_file_pattern, replace_send_file, result_text, flags=re.DOTALL)

        # 3. Process ALL [MEMORY: ...] tags — persistent memory operations
        if memory is not None:
            memory_pattern = r"\[MEMORY:\s*(.+?)\]"

            def replace_memory(match):
                nonlocal tool_used
                content = match.group(1).strip()

                try:
                    # list_tasks — return active task summary
                    if content.lower() == "list_tasks":
                        tasks = memory.list_tasks()
                        if tasks:
                            summary = "\n".join(
                                f"  - [{t.status.value}] {t.description}"
                                for t in tasks[:10]
                            )
                            return f"\n[Active tasks ({len(tasks)}):\n{summary}]"
                        return "\n[No active tasks]"

                    # correction=... — learn from correction
                    corr_match = re.match(r"correction\s*=\s*(.+)", content, re.IGNORECASE)
                    if corr_match:
                        memory.learn_from_correction(corr_match.group(1).strip())
                        tool_used = True
                        return "\n[Memory updated from correction]"

                    # task=... — create or update task
                    task_match = re.match(r"task\s*=\s*(.+)", content, re.IGNORECASE)
                    if task_match:
                        desc = task_match.group(1).strip()
                        memory.create_task(description=desc, tags=["ai-tracked"])
                        tool_used = True
                        return f"\n[Task created: {desc[:80]}]"

                    # decision=... — store as decision
                    dec_match = re.match(r"decision\s*=\s*(.+)", content, re.IGNORECASE)
                    if dec_match:
                        decision = dec_match.group(1).strip()
                        memory.store(
                            key=f"decision:{decision[:60]}",
                            value=decision,
                            domain=MemoryDomain.DECISION,
                            importance=0.7,
                            source="inference",
                        )
                        tool_used = True
                        return f"\n[Decision recorded: {decision[:80]}]"

                    # key=value — generic store
                    kv_match = re.match(r"(\w[\w\s]*?)\s*=\s*(.+)", content)
                    if kv_match:
                        key = kv_match.group(1).strip()
                        value = kv_match.group(2).strip()
                        memory.store(
                            key=key,
                            value=value,
                            domain=MemoryDomain.FACT,
                            importance=0.5,
                            source="inference",
                        )
                        tool_used = True
                        return f"\n[Memory saved: {key}]"

                except Exception as e:
                    return f"\n[Memory error: {e}]"

                return match.group(0)

            result_text = re.sub(memory_pattern, replace_memory, result_text, flags=re.DOTALL)

        return result_text, tool_used, metadata

