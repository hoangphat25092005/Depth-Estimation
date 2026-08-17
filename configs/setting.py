import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (configs/ is one level below project root)
load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
STORAGE_DOMAIN = os.getenv("STORAGE_DOMAIN", "http://localhost:9000")
STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY")
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY")
DEPTH_MODEL_PATH = os.getenv("DEPTH_MODEL_PATH")
REDIS_WORKER_URL = os.getenv("REDIS_WORKER_URL")
REDIS_BACKEND_URL = os.getenv("REDIS_BACKEND_URL")