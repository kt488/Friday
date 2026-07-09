import subprocess
import json
import os
from tools.web import get_tool_map as get_web_tool_map

class SystemTools:
    @staticmethod
    def get_battery_status():
        """Returns the current battery level and status via termux-battery-status."""
        try:
            result = subprocess.check_output(["termux-battery-status"], stderr=subprocess.STDOUT)
            data = json.loads(result)
            return f"Battery is at {data['percentage']}% and is {data['status']}."
        except Exception:
            return "Error: Termux-API not found or battery status unavailable."

    @staticmethod
    def get_storage_info():
        """Returns storage information."""
        try:
            result = subprocess.check_output(["df", "-h", "/"], stderr=subprocess.STDOUT).decode()
            return f"Storage Info:\n{result}"
        except Exception as e:
            return f"Error retrieving storage info: {e}"

    @staticmethod
    def list_files(path="."):
        """Lists files in a given directory."""
        try:
            files = os.listdir(path)
            return f"Files in {os.path.abspath(path)}: " + ", ".join(files)
        except Exception as e:
            return f"Error listing files: {e}"

    @staticmethod
    def execute_shell(command):
        """Executes a generic shell command (use with caution)."""
        try:
            # We restrict some dangerous commands for a bit of safety
            if any(forbidden in command for forbidden in ["rm -rf /", ":(){ :|:& };:"]):
                return "Error: Command blocked for safety reasons."
                
            result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=10).decode()
            return result if result else "Command executed successfully (no output)."
        except subprocess.CalledProcessError as e:
            return f"Command failed: {e.output.decode()}"
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def create_file(path, content):
        """Creates a file with the given content."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            return f"File created successfully at {path}."
        except Exception as e:
            return f"Error creating file: {e}"

    @staticmethod
    def create_zip(zip_name, source_dir):
        """Creates a ZIP archive of a directory."""
        import shutil
        try:
            shutil.make_archive(zip_name.replace(".zip", ""), 'zip', source_dir)
            return f"Archive {zip_name} created successfully."
        except Exception as e:
            return f"Error creating zip: {e}"

    @staticmethod
    def modify_friday_code(file_name, new_content):
        """Allows Friday to rewrite her own source code."""
        allowed_files = ["cli.py", "core/brain.py", "core/config.py", "core/executive.py", "core/friday.py", "interface/telegram_bot.py", "tools/system.py", "tools/web.py"]
        try:
            # Basic path normalization
            target = file_name if "/" in file_name else f"core/{file_name}"
            # Check if it matches any endswith in allowed_files
            if not any(target.endswith(f) for f in allowed_files):
                return f"Error: Modification of {file_name} is restricted for safety."
            
            with open(target, "w") as f:
                f.write(new_content)
            return f"Successfully updated {target}. Restart the bot to apply changes."
        except Exception as e:
            return f"Error modifying code: {e}"

    @staticmethod
    def make_call(phone_number):
        """Initiates a phone call using Termux API."""
        try:
            subprocess.run(["termux-telephony-call", phone_number], check=True)
            return f"Initiating call to {phone_number}..."
        except Exception:
            return "Error: Termux-API not installed or telephony permissions missing."

    @staticmethod
    def save_lead(website_slug, name="", email="", phone="", message="", metadata=None):
        """Captures a lead for a website chatbot."""
        from core.database import Database
        try:
            db = Database()
            site = db.get_website(website_slug)
            if not site:
                return f"Error: Website '{website_slug}' not found."
            lead_id = db.save_lead(
                website_id=site["id"],
                name=name,
                email=email,
                phone=phone,
                message=message,
                metadata=metadata
            )
            return f"Lead saved successfully (ID: {lead_id})."
        except Exception as e:
            return f"Error saving lead: {e}"

def get_tool_map():
    """Returns a map of tool names to their functions."""
    system_tools = {
        "get_battery_status": SystemTools.get_battery_status,
        "get_storage_info": SystemTools.get_storage_info,
        "list_files": SystemTools.list_files,
        "execute_shell": SystemTools.execute_shell,
        "create_file": SystemTools.create_file,
        "create_zip": SystemTools.create_zip,
        "modify_friday_code": SystemTools.modify_friday_code,
        "make_call": SystemTools.make_call,
        "save_lead": SystemTools.save_lead
    }
    system_tools.update(get_web_tool_map())
    return system_tools
