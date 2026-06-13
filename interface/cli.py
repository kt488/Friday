from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

class FridayCLI:
    def __init__(self):
        self.console = Console()
        self.session = PromptSession(history=InMemoryHistory())
        self._welcome_message()

    def _welcome_message(self):
        welcome_text = Text("Welcome, I am Friday. How can I assist you today?", style="bold cyan")
        self.console.print(Panel(welcome_text, title="SYSTEM", border_style="cyan"))

    def get_input(self):
        """Gets user input from the prompt."""
        try:
            user_input = self.session.prompt("User > ")
            return user_input.strip()
        except (KeyboardInterrupt, EOFError):
            return "exit"

    def print_response(self, text):
        """Prints Friday's response in a formatted panel."""
        response_text = Text(text, style="green")
        self.console.print(Panel(response_text, title="FRIDAY", border_style="green"))

    def print_system(self, text, style="yellow"):
        """Prints a system message."""
        self.console.print(f"[{style}]* {text}[/{style}]")

if __name__ == "__main__":
    # Quick test loop
    cli = FridayCLI()
    while True:
        text = cli.get_input()
        if text.lower() == "exit":
            cli.print_system("Shutting down...")
            break
        cli.print_response(f"You said: {text}")
