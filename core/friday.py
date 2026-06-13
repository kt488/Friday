from core.brain import FridayBrain
from core.executive import FridayExecutive
from core.database import Database

class FridayCore:
    def __init__(self):
        self.brain = FridayBrain()
        self.executive = FridayExecutive()
        self.db = Database()

    def process_message(self, message, image_path=None):
        """
        Takes a user message, processes it with the brain, 
        executes any tool calls, and returns the final response and any metadata.
        """
        if not message and not image_path:
            return "...", None

        # Get recent history for context
        history = self.db.get_conversation_history(limit=10)

        if message:
            self.db.save_message("user", message)
            self.executive.supabase.save_message("user", message)

        # Get MCP tools description
        extra_tools = self.executive.mcp.get_all_tools_description()

        # 1. Generate response from Brain
        raw_response = self.brain.generate_response(message, image_path=image_path, history=history, extra_tools=extra_tools)

        # 2. Parse and execute tools if necessary
        final_response, tool_used, metadata = self.executive.parse_and_execute(raw_response)
        
        self.db.save_message("friday", final_response)
        self.executive.supabase.save_message("friday", final_response)
        return final_response, metadata

    def process_message_stream(self, message, image_path=None):
        """
        Yields response chunks and handles tool execution at the end.
        """
        if not message and not image_path:
            yield "..."
            return

        # Get recent history for context
        history = self.db.get_conversation_history(limit=10)

        if message:
            self.db.save_message("user", message)
            self.executive.supabase.save_message("user", message)

        full_response = ""
        # Default prompt if only image is sent
        prompt = message if message else "Analyze this image."
        
        extra_tools = self.executive.mcp.get_all_tools_description()
        
        for chunk in self.brain.generate_stream(prompt, image_path=image_path, history=history, extra_tools=extra_tools):
            full_response += chunk
            yield chunk

        # After streaming completes, check for tool calls
        final_response, tool_used, metadata = self.executive.parse_and_execute(full_response)
        
        if tool_used:
            # If a tool was used, we yield the result as a new block
            tool_output = final_response.replace(full_response, '').strip()
            yield f"\n\n{tool_output}"
            
        self.db.save_message("friday", final_response)
        self.executive.supabase.save_message("friday", final_response)

if __name__ == "__main__":
    # Test
    friday = FridayCore()
    print(friday.process_message("What is your status?"))
