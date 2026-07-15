import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Config:
    # API Settings
    # Using NVIDIA NIM Endpoint
    NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

    # Model Settings
    PRIMARY_MODEL = os.getenv("MODEL_NAME", "deepseek-ai/deepseek-v4-pro")
    VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"

    # Fallback models
    FALLBACK_MODELS = [
        "qwen/qwen3.5-397b-a17b",
        "openai/gpt-oss-120b"
    ]
    
    # Directory Settings
    TEMP_DIR = os.path.abspath("temp")
    AGENTS_DIR = os.path.abspath("agents")
    
    # JWT Settings (used by SaaS auth)
    FRIDAY_JWT_SECRET = os.getenv("FRIDAY_JWT_SECRET", "")
    FRIDAY_JWT_EXPIRY = int(os.getenv("FRIDAY_JWT_EXPIRY", "72"))
    FRIDAY_JWT_ALGORITHM = "HS256"

    # App Settings
    APP_NAME = "Friday Assistant"
    REFERER = "https://github.com/friday-assistant"

    @classmethod
    def validate(cls):
        """Validates that essential config is present."""
        os.makedirs(cls.TEMP_DIR, exist_ok=True)
        if not cls.NVIDIA_API_KEY:
            return False, "Missing NVIDIA_API_KEY in .env"
        if not cls.NVIDIA_API_KEY.startswith("nvapi-"):
            return False, "Invalid NVIDIA API key format — must start with nvapi-"
        return True, "OK"
