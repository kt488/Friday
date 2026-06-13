from tools.system import get_tool_map
from core.mcp_client import MCPManager
from core.supabase_client import SupabaseClient

class FridayExecutive:
    def __init__(self):
        self.tool_map = get_tool_map()
        self.mcp = MCPManager()
        self.mcp.start_clients()
        self.supabase = SupabaseClient()

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

    def parse_and_execute(self, response_text):
        """
        Looks for tool calling and file sending patterns in the AI's response.
        Patterns: 
        - [TOOL: function_name("arg1", "arg2")]
        - [SEND_FILE: path]
        """
        import re
        import os
        import shutil
        import ast
        import json
        
        # 1. Handle [SEND_FILE: path]
        send_file_pattern = r"\[SEND_FILE:\s*(.*?)\]"
        send_match = re.search(send_file_pattern, response_text)
        if send_match:
            file_path = send_match.group(1).strip()
            # Clean up quotes
            if (file_path.startswith('"') and file_path.endswith('"')) or \
               (file_path.startswith("'") and file_path.endswith("'")):
                file_path = file_path[1:-1]
            
            workspace_dir = os.path.abspath("workspace")
            os.makedirs(workspace_dir, exist_ok=True)
            
            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                dest_path = os.path.join(workspace_dir, filename)
                
                try:
                    # If it's not already in the workspace, copy it there
                    if os.path.abspath(file_path) != os.path.abspath(dest_path):
                        shutil.copy2(file_path, dest_path)
                    
                    file_size = os.path.getsize(dest_path)
                    download_url = f"/download/{filename}"
                    
                    # Log to Supabase automatically
                    self.supabase.log_file(filename, dest_path, file_size, download_url)
                    
                    clean_text = re.sub(send_file_pattern, f"\n[File ready for download: {filename}]", response_text)
                    return clean_text, True, {"type": "file", "filename": filename, "url": download_url}
                except Exception as e:
                    clean_text = re.sub(send_file_pattern, f"\n[Error preparing file: {e}]", response_text)
                    return clean_text, True, None
            else:
                clean_text = re.sub(send_file_pattern, f"\n[Error: File not found at {file_path}]", response_text)
                return clean_text, True, None

        # 2. Handle [TOOL: function_name(args)]
        tool_pattern = r"\[TOOL:\s*(\w+)\((.*?)\)\]"
        match = re.search(tool_pattern, response_text)
        
        if match:
            tool_name = match.group(1)
            raw_args = match.group(2).strip()
            
            args = None
            if raw_args:
                # Try to parse as JSON first
                if raw_args.startswith("{") and raw_args.endswith("}"):
                    try:
                        args = json.loads(raw_args)
                    except:
                        pass
                
                # If not JSON or JSON failed, try ast.literal_eval for Python-style args
                if args is None:
                    try:
                        # Wrap in tuple if it contains commas but isn't already a list/dict
                        if "," in raw_args and not (raw_args.startswith("[") or raw_args.startswith("{")):
                            args = ast.literal_eval(f"({raw_args})")
                        else:
                            args = ast.literal_eval(raw_args)
                    except Exception as e:
                        # Fallback to raw string if it's just a simple string without quotes
                        args = raw_args
                
            result = self.handle_tool_call(tool_name, args)
            
            # Clean up the response text by removing the tool call tag
            clean_text = re.sub(tool_pattern, f"\n[Executed {tool_name}: {result}]", response_text)
            return clean_text, True, None
            
        return response_text, False, None

