import os

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# Optional LiveKit environment from the retained Chert bridge starter.
load_dotenv(Path(__file__).resolve().parent.parent / "chert" / "scansafe-agent" / ".env.local",
            override=False)

JEV_API_KEY = os.getenv("JEV_API_KEY", "")
JEV_BASE_URL = os.getenv("JEV_BASE_URL", "")  # empty = OpenRouter Decisions API
JEV_MODEL = os.getenv("JEV_MODEL", "typesafe/jev-1.14")
BLOCK_SCORE = float(os.getenv("BLOCK_SCORE", "0.8"))
SECOND_LOOK_SCORE = float(os.getenv("SECOND_LOOK_SCORE", "0.5"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

SANDBOX_URL = os.getenv("SANDBOX_URL", "")      # empty = QR capability unavailable
SANDBOX_TOKEN = os.getenv("SANDBOX_TOKEN", "")

# Detection extras (api/signals.py). Kill switches in case a lookup misbehaves during a demo.
SIGNALS_RDAP = os.getenv("SIGNALS_RDAP", "1") != "0"   # domain age via rdap.org (3 s, cached)
SECOND_LOOK = os.getenv("SECOND_LOOK", "1") != "0"     # Gemini double-checks "suspicious" pages
