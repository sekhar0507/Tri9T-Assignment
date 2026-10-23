import os
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ct200.db")
GENERATIONS_STORE = os.getenv("GENERATIONS_STORE", "./generated")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
