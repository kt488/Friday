import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Config:
    # API Settings
    # Using NVIDIA NIM Endpoint
    NVIDIA_API_KEY = os.getenv("OPENROUTER_API_KEY") 
    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
    
    # Model Settings
    # Using Llama 3.1 8B for ultra-low latency and stability
    PRIMARY_MODEL = "meta/llama-3.1-8b-instruct"
    VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
    
    # Fallback models
    FALLBACK_MODELS = [
        "nvidia/llama-3.3-nemotron-70b-instruct",
        "deepseek-ai/deepseek-v4-flash"
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
            return False, "Missing NVIDIA_API_KEY (OPENROUTER_API_KEY) in .env"
        # Support both OpenRouter and NVIDIA/DeepSeek key formats
        if not (cls.NVIDIA_API_KEY.startswith("sk-or-v1") or cls.NVIDIA_API_KEY.startswith("nvapi-")):
            return False, "Invalid API key format in .env"
        return True, "OK"
