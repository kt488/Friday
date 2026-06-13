import subprocess
import shutil
import pyttsx3

class FridayVoice:
    def __init__(self):
        # Check if termux-tts-speak is available (most reliable on Android)
        self.use_termux_api = shutil.which("termux-tts-speak") is not None
        
        self.engine = None
        if not self.use_termux_api:
            try:
                self.engine = pyttsx3.init()
            except Exception:
                self.engine = None

    def speak(self, text):
        """Converts text to speech using the best available engine."""
        if not text:
            return

        # 1. Try Termux API (Native Android TTS)
        if self.use_termux_api:
            try:
                # Use subprocess to call termux-tts-speak
                # -p 1.3 makes the voice slightly higher (more female)
                # -v 1 or -v female often selects a female variant depending on engine
                subprocess.run(["termux-tts-speak", "-p", "1.3", "-v", "female", text], check=True)
                return
            except Exception:
                try:
                    # Fallback to just pitch if variant fails
                    subprocess.run(["termux-tts-speak", "-p", "1.3", text], check=True)
                    return
                except Exception:
                    pass

        # 2. Try pyttsx3 (Fallback)
        if self.engine:
            try:
                # Set female voice if available in pyttsx3
                voices = self.engine.getProperty('voices')
                for voice in voices:
                    if "female" in voice.name.lower():
                        self.engine.setProperty('voice', voice.id)
                        break
                self.engine.setProperty('pitch', 1.3)
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception:
                pass

if __name__ == "__main__":
    # Quick test
    voice = FridayVoice()
    print("Testing speech...")
    voice.speak("System test. If you can hear this, my voice is online.")
