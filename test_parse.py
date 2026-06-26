from core.executive import FridayExecutive
exec = FridayExecutive()

# Use \n escape sequences (what the LLM generates - backslash followed by n)
response = '[TOOL: create_file("workspace/test.csv", "id,name,email\\n1,John,john@test.com\\n2,Jane,jane@test.com")]\nSome response text.\n[SEND_FILE: workspace/test.csv]'
result, tool_used, metadata = exec.parse_and_execute(response)
print(f"tool_used={tool_used}")
print(f"metadata={metadata}")
print(f"result={result!r}")

# Check if file exists
import os
if os.path.exists("workspace/test.csv"):
    print("\nFile contents:")
    with open("workspace/test.csv") as f:
        print(f.read())
else:
    print("\nFile NOT created")
