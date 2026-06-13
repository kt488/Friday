from interface.cli import FridayCLI
from core.brain import FridayBrain
from core.executive import FridayExecutive
from peripherals.voice import FridayVoice
import sys

def main():
    # Initialize components
    cli = FridayCLI()
    
    cli.print_system("Initializing Voice engine...")
    voice = FridayVoice()
    
    cli.print_system("Connecting to OpenRouter (Dolphin-Mistral)...")
    brain = FridayBrain()

    cli.print_system("Loading Executive systems...")
    executive = FridayExecutive()
    
    cli.print_system("Friday is online.")

    try:
        while True:
            # 1. Get input
            user_input = cli.get_input()
            
            # 2. Check for exit command
            if user_input.lower() in ["exit", "quit", "bye"]:
                cli.print_system("Goodbye!")
                voice.speak("Goodbye.")
                break
                
            if not user_input:
                continue
                
            # 3. Process with Brain
            cli.print_system("Thinking...", style="dim yellow")
            response = brain.generate_response(user_input)

            # 4. Check for and execute tool calls
            final_response, tool_used = executive.parse_and_execute(response)
            
            # 5. Output response
            cli.print_response(final_response)
            voice.speak(final_response)
            
    except KeyboardInterrupt:
        cli.print_system("\nForced shutdown. Goodbye.")
        sys.exit(0)

if __name__ == "__main__":
    main()
