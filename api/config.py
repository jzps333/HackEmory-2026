import os

from dotenv import load_dotenv

load_dotenv()

JEV_API_KEY = os.getenv("JEV_API_KEY", "")
JEV_BASE_URL = os.getenv("JEV_BASE_URL", "")  # empty = OpenRouter Decisions API
JEV_MODEL = os.getenv("JEV_MODEL", "typesafe/jev-1.14")
BLOCK_SCORE = float(os.getenv("BLOCK_SCORE", "0.8"))
SECOND_LOOK_SCORE = float(os.getenv("SECOND_LOOK_SCORE", "0.5"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

SANDBOX_URL = os.getenv("SANDBOX_URL", "")      # empty = return mock results
SANDBOX_TOKEN = os.getenv("SANDBOX_TOKEN", "")
