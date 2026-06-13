from core.mcp_client import MCPManager
import time

def test_mcp():
    print("Initializing MCP Manager...")
    mcp = MCPManager()
    
    print("Starting clients...")
    mcp.start_clients()
    
    # Wait a moment for clients to initialize and fetch tools
    time.sleep(2)
    
    print("\n--- Available Tools ---")
    tools_desc = mcp.get_all_tools_description()
    if tools_desc:
        print(tools_desc)
    else:
        print("No tools found. Check client initialization.")
        
    print("\nShutting down clients...")
    mcp.stop_all()
    print("Test complete.")

if __name__ == "__main__":
    test_mcp()
