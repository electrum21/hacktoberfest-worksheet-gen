import os

MODEL = os.getenv("WS_MODEL", "gemma3:4b")
HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DB_PATH = os.getenv("WS_DB", "worksheets.db")

# Optional: hosted portal (hybrid mode). Can also be set in the app's Portal tab.
PORTAL_URL = os.getenv("WS_PORTAL_URL", "")
PORTAL_TOKEN = os.getenv("WS_PORTAL_TOKEN", "")
