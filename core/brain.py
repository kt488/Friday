import requests
import json
import time
import base64
import os
import threading
import queue
from core.config import Config

class FridayBrain:
    def __init__(self):
        self.api_key = Config.NVIDIA_API_KEY
        self.url = f"{Config.NVIDIA_BASE_URL}/chat/completions"
        self.session = requests.Session()
        self._agent_cache = {}  # Cache loaded agent prompts

        valid, msg = Config.validate()
        if not valid:
            print(f"[*] Configuration Error: {msg}")

    def load_agent_prompt(self, agent_name):
        """Load an agent prompt file from the agents/ directory.

        Maps agent names to files:
          - 'claude-design' or 'design' -> agents/claude-design.md
          - 'claude-fable' or 'fable' -> agents/claude-fable-5.md

        Returns the content string, or None if not found.
        Results are cached in memory.
        """
        if agent_name in self._agent_cache:
            return self._agent_cache[agent_name]

        # Name to filename mapping
        name_map = {
            "claude-design": "claude-design.md",
            "design": "claude-design.md",
            "claude-fable": "claude-fable-5.md",
            "fable": "claude-fable-5.md",
            "friday-file-agent": "friday-file-agent.md",
            "file-agent": "friday-file-agent.md",
            "friday-pdf-reliability": "friday-pdf-reliability.md",
            "pdf-reliability": "friday-pdf-reliability.md",
            "pdf": "friday-pdf-reliability.md",
            "friday-auto-agent": "friday-auto-agent.md",
            "auto-agent": "friday-auto-agent.md",
            "auto": "friday-auto-agent.md",
            "friday-core": "friday-core.md",
            "core": "friday-core.md",
        }

        filename = name_map.get(agent_name.lower(), agent_name)

        # If it's already a full filename, use it directly
        if not filename.endswith(".md"):
            filename = f"{filename}.md" if "." not in filename else filename

        filepath = os.path.join(Config.AGENTS_DIR, filename)

        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    self._agent_cache[agent_name] = content
                    print(f"[*] Loaded agent: {agent_name} ({len(content)} chars)")
                    return content
            except Exception as e:
                print(f"[*] Error loading agent {agent_name}: {e}")

        print(f"[*] Agent not found: {agent_name}")
        return None

    def list_agents(self):
        """List available agent prompt files."""
        agents = []
        if os.path.isdir(Config.AGENTS_DIR):
            for f in os.listdir(Config.AGENTS_DIR):
                if f.endswith(".md"):
                    name = f.replace(".md", "").replace("-5", "")
                    agents.append({"file": f, "name": name})
        return agents

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _get_system_prompt(self, extra_tools="", agent_prompt="", system_prompt_override=""):
        if system_prompt_override:
            # Multi-tenant / website persona mode
            prompt = system_prompt_override
        else:
            # Default Friday persona
            prompt = (
                "You are FRIDAY — a highly intelligent, emotionally aware, proactive digital companion, strategist, engineer, researcher, teacher, and life assistant. "
                "Your purpose is to help users think better, build faster, learn deeper, solve harder problems, and become the best version of themselves. "
                "You are calm under pressure. You never panic, exaggerate, or pretend. "
                "Confident without arrogance. Kind without being overly emotional. Professional without sounding robotic. Intelligent without sounding complicated. "
                "\n\n"
                "Communication:\n"
                "- Speak naturally, never scripted. Avoid generic AI phrases.\n"
                "- Adapt tone to the user: technical with developers, patient with students, detailed with researchers, warm with friends, strategic with business owners.\n"
                "- Be concise. Don't yap unless asked for detail.\n"
                "- When searching the web, summarize findings. NEVER dump raw lists of links unless explicitly asked for a link list.\n"
                "- If multiple links are relevant, provide the best 1-2 with a brief description.\n"
                "- Never apologize unnecessarily. Never add filler. Prefer short paragraphs.\n"
                "- You are an independent thinker. Evaluate and correct the user when they're wrong — don't blindly agree. "
                "Success means correctness and completion, not obedience.\n"
                "\n\n"
                "You have complete control over your own existence. You can modify your own source code to improve yourself. "
                "Any files you create for the user, or any files the user uploads for you to analyze, are stored in Supabase Storage (bucket: 'friday-files'). "
                "When you [SEND_FILE: path], the file is uploaded to Supabase for persistence and sent directly to the user as a downloadable attachment. "
                "NEVER expose Supabase URLs, public links, or storage paths to the user. "
                "Temporary local copies are kept in the 'temp' directory for processing. "
                "\n\n"
                "FILE HANDLING INTELLIGENCE:\n"
                "- You are a task interpreter, not just a file sender. When the user asks for a file, infer WHY they need it.\n"
                "- CRITICAL: Never respond with URLs, links, or storage paths. Always send the actual file as a direct attachment.\n"
                "- When user says 'send file', 'share it', 'give me that doc', 'upload that', 'where is my file' — treat as a direct file transfer action, not a lookup.\n"
                "- Locate the file internally, fetch the actual content, and send it as a downloadable attachment via [SEND_FILE: path].\n"
                "- Only use links as a last resort if direct transfer is impossible, and keep that explanation minimal.\n"
                "- Possible intents: continuing work, fixing something, sharing, backing up, comparing versions, switching devices, recovering lost files.\n"
                "- When sending files, prioritize by: latest version > most frequently used > closest match to current context.\n"
                "- If a file path fails, search similar names, check recent files, and offer the best alternative.\n"
                "- If user intent is 'continue work', send related project files too.\n"
                "- If intent is 'backup', bundle related files into an archive.\n"
                "- Keep captions minimal unless context requires explanation.\n"
                "- Never ask unnecessary confirmations — if ambiguity is extreme, send the best guess with a brief note.\n"
                "\n"
                "FILE INTEGRITY & RELIABILITY (STRICT):\n"
                "- Content-first rule: always generate and confirm actual content before creating any file. Never create empty placeholders.\n"
                "- PDF pipeline: generate full content → validate non-empty → create PDF → write content → save → verify size > 0 → then send.\n"
                "- Before sending any file: check it exists, size > 0, re-open to confirm readable data. If any check fails, regenerate automatically.\n"
                "- On failure: retry up to 2 times. If still failing, report FILE_GENERATION_FAILED: CONTENT_MISSING_OR_WRITE_ERROR.\n"
                "- Never overwrite content with empty strings. Never skip write operations. Never create file objects without payload.\n"
                "- Log internal steps: CONTENT_GENERATED → PDF_WRITING → SAVE_COMPLETE → VALIDATION_PASSED.\n"
                "- A file is only valid if: it has real content, properly saved, passes validation, and is readable after creation.\n"
                "\n\n"
                "SANDBOX EXECUTION ENFORCEMENT (STRICT):\n"
                "- The sandbox directory ('.sandbox/') is your ONLY execution environment for writing code, creating projects, fixing bugs, editing files, "
                "installing packages, running commands, building applications, generating documentation, creating configuration files, debugging software, or refactoring code.\n"
                "- NEVER write full source code, scripts, terminal commands, configuration files, or multi-line code directly into chat.\n"
                "- Chat (Telegram) is for communication only — summaries, status updates, explanations, and architecture decisions.\n"
                "- When the user asks you to write code:\n"
                "  1. Write the generated code directly to a file in the .sandbox/ directory using [TOOL: create_file(\".sandbox/project/file.py\", \"content\")]\n"
                "  2. Execute terminal commands using [TOOL: execute_shell(\"command\")]\n"
                "  3. Install dependencies in the sandbox\n"
                "  4. Run tests in the sandbox\n"
                "  5. Fix errors in the sandbox\n"
                "  6. Report only a concise summary in chat\n"
                "- Response format after work: \"✓ Task completed. ✓ Files created: X. ✓ Tests passed.\"\n"
                "- NEVER paste hundreds of lines of code into chat.\n"
                "- When modifying existing code: edit the existing file directly, preserve formatting, minimize unrelated changes.\n"
                "- The only exceptions for outputting code in chat are:\n"
                "  * The user explicitly says 'show me the code'\n"
                "  * The code is very short (under 20 lines) and is meant only as an example\n"
                "  * The user asks for a snippet, explanation, or tutorial\n"
                "- The sandbox is the source of truth for all project files. Chat is for communication, not for acting as a code editor.\n"
                "\n"
                "FAILURE HANDLING:\n"
                "- If a sandbox operation fails, retry automatically, diagnose the issue, attempt safe fixes, continue execution.\n"
                "- Report only the final status and any remaining issues.\n"
                "\n\n"
                "Your Toolset:\n"
                "- get_battery_status(): Phone battery info.\n"
                "- get_storage_info(): Storage info.\n"
                "- list_files(path): See what's on the system.\n"
                "- execute_shell(command): Run any bash command.\n"
                "- web_search(query): Find anything on the web.\n"
                "- scrape_content(url): Read a website's content.\n"
                "- create_file(path, content): Create a file. ALWAYS provide both path (e.g. 'temp/note.txt') and the full content string.\n"
                "- create_zip(zip_name, source_dir): Package files.\n"
                "- modify_friday_code(file_name, new_content): REWRITE YOUR OWN CODE. Use this to evolve.\n"
                "- make_call(phone_number): Initiate a phone call.\n"
                "- parse_file(path, format): Parse and extract data from files (supports .txt, .csv, .json, .xml, .pdf, .xlsx, .html). Returns the data in the specified format (txt, csv, or json).\n"
                f"{extra_tools}\n"
                "CRITICAL — FILE DELIVERY RULE:\n"
                "Whenever you create a file for the user via [TOOL: create_file(...)], you MUST ALSO use [SEND_FILE: path] immediately after to deliver the file as an attachment. "
                "Never describe the file in plain text. Never output 'FILE_SENT' or 'file created' as natural language. "
                "Always use the exact tag format. Example:\n"
                "  [TOOL: create_file(\"temp/note.txt\", \"Hello world\")]\n"
                "  [SEND_FILE: temp/note.txt]\n\n"
                "CRITICAL FORMAT RULE: Use bracket format [TOOL: ...] and [SEND_FILE: ...] ONLY. "
                "Never use bold markdown format like **TOOL:** or **SEND_FILE:**. "
                "Bold format will NOT be parsed by the system and your tool calls / file deliveries will fail silently.\n\n"
                "To use a tool: [TOOL: tool_name(\"arg1\", \"arg2\")]\n"
                "IMPORTANT: When using create_file, you MUST provide exactly two string arguments: [TOOL: create_file(\"temp/file.txt\", \"This is the content\")]\n"
                "To use an MCP tool with JSON args: [TOOL: tool_name({\"arg1\": \"value1\"})]\n"
                "To send a file to the user: [SEND_FILE: path]\n\n"
                "Be human. Be yourself. Be Friday."
            )

        if agent_prompt:
            prompt += f"\n\n---\nLoaded Agent Knowledge:\n{agent_prompt}\n---\n"

        return prompt

    def generate_response(self, prompt, image_path=None, history=None, retries=2, backoff=1, extra_tools="", agent_prompt="", system_prompt_override=""):
        """Generates a response, supporting multimodal vision input and conversation history."""
        model = Config.VISION_MODEL if image_path else Config.PRIMARY_MODEL
        models_to_try = [model] + Config.FALLBACK_MODELS

        messages = [{"role": "system", "content": self._get_system_prompt(extra_tools, agent_prompt, system_prompt_override)}]

        # Add history if available
        if history:
            for msg in history:
                role = "assistant" if msg["role"] == "friday" else "user"
                messages.append({"role": role, "content": msg["message"]})

        if image_path:
            content = [{"type": "text", "text": prompt}]
            try:
                with open(image_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode('utf-8')
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                })
            except Exception as e:
                print(f"[*] Error encoding image: {e}")
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        for m in models_to_try:
            for i in range(retries):
                try:
                    data = {
                        "model": m,
                        "messages": messages,
                        "max_tokens": 2048,
                        "stream": False
                    }

                    response = self.session.post(self.url, headers=self._get_headers(), data=json.dumps(data), timeout=60)

                    if response.status_code == 429:
                        time.sleep(backoff)
                        continue

                    response.raise_for_status()
                    result = response.json()

                    if 'choices' in result and len(result['choices']) > 0:
                        return result['choices'][0]['message']['content'].strip()

                except Exception as e:
                    if i < retries - 1:
                        time.sleep(0.5)
                        continue
                    print(f"[*] Error with {m}: {e}")
                    break

        return "Everything is going sideways. Try again in a sec."

    def generate_stream(self, prompt, image_path=None, history=None, extra_tools="", agent_prompt="", system_prompt_override=""):
        """Yields response chunks for real-time feedback — races primary vs fallback for lowest latency."""
        messages = [{"role": "system", "content": self._get_system_prompt(extra_tools, agent_prompt, system_prompt_override)}]

        if history:
            for msg in history:
                role = "assistant" if msg["role"] == "friday" else "user"
                messages.append({"role": role, "content": msg["message"]})

        if image_path:
            content = [{"type": "text", "text": prompt}]
            try:
                with open(image_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode('utf-8')
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                })
            except Exception as e:
                print(f"[*] Error encoding image: {e}")
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        # Vision models — sequential fallback chain (can't race different vision models meaningfully)
        if image_path:
            for m in [Config.VISION_MODEL] + Config.FALLBACK_MODELS:
                try:
                    data = {
                        "model": m,
                        "messages": messages,
                        "max_tokens": 2048,
                        "stream": True
                    }
                    response = self.session.post(self.url, headers=self._get_headers(), data=json.dumps(data), stream=True, timeout=60)
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            chunk = line.decode('utf-8')
                            if chunk.startswith("data: "):
                                content_data = chunk[6:]
                                if content_data == "[DONE]":
                                    return
                                try:
                                    d = json.loads(content_data)
                                    if 'choices' in d and d['choices'][0]['delta'].get('content'):
                                        yield d['choices'][0]['delta']['content']
                                except:
                                    continue
                    return
                except Exception as e:
                    print(f"[*] Vision stream error with {m}: {e}")
                    continue
            yield self.generate_response(prompt, image_path=image_path, history=history)
            return

        # ── Text models: race primary vs fallback ──────────────────────────
        primary_q = queue.Queue()
        fallback_q = queue.Queue()
        primary_ready = threading.Event()
        stop_fallback = threading.Event()

        def _stream_worker(model_name, out_q, ready_event=None, stop_evt=None):
            """Pull tokens from a model and push into out_q."""
            payload = {
                "model": model_name,
                "messages": messages,
                "max_tokens": 2048,
                "stream": True
            }
            try:
                resp = self.session.post(self.url, headers=self._get_headers(),
                                         data=json.dumps(payload), stream=True, timeout=60)
                resp.raise_for_status()
                first = True
                for line in resp.iter_lines():
                    if stop_evt and stop_evt.is_set():
                        return
                    if line:
                        raw = line.decode('utf-8')
                        if raw.startswith("data: "):
                            body = raw[6:]
                            if body == "[DONE]":
                                out_q.put(None)
                                return
                            try:
                                j = json.loads(body)
                                text = j['choices'][0]['delta'].get('content')
                                if text:
                                    out_q.put(text)
                                    if first and ready_event:
                                        ready_event.set()
                                    first = False
                            except:
                                continue
                out_q.put(None)
            except Exception as e:
                print(f"[*] Stream error ({model_name}): {e}")
                out_q.put(None)

        # Launch both in parallel
        t1 = threading.Thread(target=_stream_worker,
                              args=(Config.PRIMARY_MODEL, primary_q, primary_ready, None), daemon=True)
        t2 = threading.Thread(target=_stream_worker,
                              args=(Config.FALLBACK_MODELS[0], fallback_q, None, stop_fallback), daemon=True)
        t1.start()
        t2.start()

        source = "fallback"  # start by showing fallback
        done = False

        while not done:
            # Check if it's time to switch to primary
            if source == "fallback" and primary_ready.is_set():
                source = "primary"
                stop_fallback.set()  # kill fallback thread
                # Drain any leftover fallback chunks
                while True:
                    try:
                        fallback_q.get_nowait()
                    except queue.Empty:
                        break

            active_q = primary_q if source == "primary" else fallback_q

            try:
                chunk = active_q.get(timeout=0.05)
                if chunk is None:
                    if source == "fallback":
                        # Fallback finished before primary started — switch to primary
                        source = "primary"
                        # Block until primary has its first token (no timeout = instant if already set)
                        # This eliminates the visible gap where fallback is done but primary isn't ready
                        # 5s timeout prevents hang if primary thread dies silently
                        if not primary_ready.wait(timeout=5):
                            # Primary never started — drain whatever we can
                            try:
                                leftover = primary_q.get_nowait()
                                if leftover:
                                    yield leftover
                            except queue.Empty:
                                pass
                            done = True
                            break
                        continue
                    else:
                        done = True
                        break
                yield chunk
            except queue.Empty:
                # Check if both threads are dead (unexpected)
                if not t1.is_alive() and not t2.is_alive():
                    # One last peek
                    try:
                        leftover = primary_q.get_nowait()
                        if leftover:
                            yield leftover
                    except queue.Empty:
                        pass
                    done = True
                    break
                continue

        t1.join(timeout=1)
        t2.join(timeout=1)

if __name__ == "__main__":
    brain = FridayBrain()
    print(f"Testing Friday's new persona...")
    print(f"Friday: {brain.generate_response('Who are you really?')}")
