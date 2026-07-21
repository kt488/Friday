import json
import subprocess
import threading
import sys
import uuid
import time
import os
from typing import Dict, Any, List, Optional

class MCPClient:
    def __init__(self, name: str, command: List[str]):
        self.name = name
        self.command = command
        self.process = None
        self.pending_requests: Dict[str, dict] = {}
        self.tools = []
        self._lock = threading.Lock()
        self.is_running = False
        
    def start(self):
        print(f"[{self.name}] Starting server with command: {' '.join(self.command)}")
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1 # Line buffered
            )
        except Exception as e:
            raise Exception(f"Failed to spawn process: {e}")
        
        self.is_running = True
        
        # Start reading threads
        self.stdout_thread = threading.Thread(target=self._read_stdout_loop, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr_loop, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()
        
        # Small sleep to let process start and potentially crash
        time.sleep(0.5)
        if self.process.poll() is not None:
            raise Exception(f"Process terminated immediately with exit code {self.process.returncode}")
        
        # Initialize
        print(f"[{self.name}] Sending 'initialize' request...")
        init_res = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Friday", "version": "1.0.0"}
        })
        
        self.send_notification("notifications/initialized", {})
        
        # Fetch tools
        print(f"[{self.name}] Fetching tools...")
        tools_res = self.send_request("tools/list", {})
        if "tools" in tools_res:
            self.tools = tools_res["tools"]
            print(f"[{self.name}] Successfully loaded {len(self.tools)} tools.")

    def _read_stdout_loop(self):
        try:
            for line in self.process.stdout:
                line = line.strip()
                if not line:
                    continue
                # print(f"DEBUG [{self.name}] RECV: {line}")
                try:
                    msg = json.loads(line)
                    if "id" in msg:
                        req_id = str(msg["id"])
                        with self._lock:
                            if req_id in self.pending_requests:
                                self.pending_requests[req_id] = msg
                    elif "method" in msg:
                        # Handle server notifications/requests here if needed
                        pass
                except Exception as e:
                    print(f"[{self.name}] Error parsing JSON from stdout: {e}. Line: {line}")
        except Exception as e:
            if self.is_running:
                print(f"[{self.name}] Stdout reader error: {e}")
        finally:
            self.is_running = False

    def _read_stderr_loop(self):
        try:
            for line in self.process.stderr:
                line = line.strip()
                if line:
                    print(f"[{self.name}] STDERR: {line}", file=sys.stderr)
        except Exception:
            pass

    def send_notification(self, method: str, params: dict):
        if not self.is_running or self.process.poll() is not None:
            return
            
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        try:
            self.process.stdin.write(json.dumps(msg) + "\n")
            self.process.stdin.flush()
        except Exception as e:
            print(f"[{self.name}] Error sending notification: {e}")

    def send_request(self, method: str, params: dict, timeout=10) -> Any:
        if not self.is_running or self.process.poll() is not None:
            raise Exception(f"Server '{self.name}' is not running.")
            
        req_id = str(uuid.uuid4())
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        with self._lock:
            self.pending_requests[req_id] = None
            
        try:
            self.process.stdin.write(json.dumps(msg) + "\n")
            self.process.stdin.flush()
        except Exception as e:
            raise Exception(f"Failed to write to stdin of '{self.name}': {e}")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.process.poll() is not None:
                raise Exception(f"Server '{self.name}' crashed during request.")
                
            with self._lock:
                res = self.pending_requests.get(req_id)
                if res is not None:
                    del self.pending_requests[req_id]
                    if "error" in res:
                        error_msg = res["error"].get("message", str(res["error"]))
                        raise Exception(f"Server error: {error_msg}")
                    return res.get("result", {})
            time.sleep(0.05)
            
        with self._lock:
            if req_id in self.pending_requests:
                del self.pending_requests[req_id]
        raise Exception(f"Timeout waiting for MCP response from '{self.name}'")

    def call_tool(self, name: str, arguments: dict):
        res = self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        if "content" in res:
            texts = []
            for item in res["content"]:
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    texts.append("[Image data received]")
            return "\n".join(texts)
        return str(res)

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

class MCPManager:
    def __init__(self):
        self.clients: List[MCPClient] = []
        self.tool_map: Dict[str, MCPClient] = {}
        
    def start_clients(self):
        # Detect if we are on Android/Termux
        is_android = os.path.exists("/system/bin/app_process") or "com.termux" in os.environ.get("PATH", "")
        
        # 1. Filesystem MCP
        fs_server_path = "/data/data/com.termux/files/usr/lib/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
        if os.path.exists(fs_server_path):
            fs_client = MCPClient("Filesystem", [
                "node", 
                fs_server_path, 
                "/data/data/com.termux/files/home"
            ])
            self._attempt_start(fs_client)
        else:
            print("[MCP] Filesystem server not found at expected path.")

        # 2. Playwright MCP (Skipped on Android as it's unsupported)
        if not is_android:
            pw_server_path = "/data/data/com.termux/files/usr/lib/node_modules/@playwright/mcp/cli.js"
            if os.path.exists(pw_server_path):
                pw_client = MCPClient("Playwright", ["node", pw_server_path])
                self._attempt_start(pw_client)
        else:
            print("[MCP] Skipping Playwright MCP as it is not supported on Android.")

        # 3. Astryx Design MCP
        astryx_server_path = "/data/data/com.termux/files/home/Friday/astryx-mcp/index.js"
        if os.path.exists(astryx_server_path):
            astryx_client = MCPClient("Astryx Design", ["node", astryx_server_path])
            self._attempt_start(astryx_client)
        else:
            print("[MCP] Astryx Design MCP server not found at expected path.")
            
    def _attempt_start(self, client: MCPClient):
        try:
            client.start()
            self.clients.append(client)
            for tool in client.tools:
                self.tool_map[tool["name"]] = client
        except Exception as e:
            print(f"[MCP] Error starting {client.name}: {e}")

    def get_all_tools_description(self):
        desc = ""
        # Group by client to look nicer
        for client in self.clients:
            if not client.tools:
                continue
            desc += f"\n--- {client.name} Tools ---\n"
            for t in client.tools:
                desc += f"- {t['name']}(...): {t.get('description', '')}\n"
        return desc.strip()
        
    def handle_mcp_tool(self, tool_name: str, args: Any):
        if tool_name not in self.tool_map:
            return f"MCP Tool {tool_name} not found."
            
        client = self.tool_map[tool_name]
        tool_def = next((t for t in client.tools if t["name"] == tool_name), None)
        
        args_dict = {}
        try:
            if isinstance(args, str):
                args_str = args.strip()
                # Check if it looks like JSON
                if args_str.startswith("{") and args_str.endswith("}"):
                    try:
                        args_dict = json.loads(args_str)
                    except json.JSONDecodeError:
                        return f"Error: Tool {tool_name} received invalid JSON: {args_str}"
                elif tool_def:
                    # Not JSON, try to wrap it based on schema
                    schema = tool_def.get("inputSchema", {})
                    properties = schema.get("properties", {})
                    required = schema.get("required", [])
                    
                    if len(required) == 1:
                        args_dict = {required[0]: args}
                    elif len(properties) == 1:
                        args_dict = {list(properties.keys())[0]: args}
                    elif not required and len(properties) > 1:
                        # Ambiguous, but let's try 'path' if it exists as it's common
                        if "path" in properties:
                            args_dict = {"path": args}
                        else:
                            return f"Error: Tool {tool_name} expects multiple arguments in JSON format."
                    else:
                        # Fallback for tools with no required args or complex schemas
                        if not properties and not required:
                            args_dict = {}
                        else:
                            return f"Error: Tool {tool_name} expects JSON arguments. Received: {args}"
                else:
                    return f"Error: Tool {tool_name} definition not found."
            else:
                args_dict = args if args else {}
        except Exception as e:
            return f"Error processing arguments for {tool_name}: {e}"
            
        try:
            return client.call_tool(tool_name, args_dict)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

    def stop_all(self):
        for c in self.clients:
            c.stop()
