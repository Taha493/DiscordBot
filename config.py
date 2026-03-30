import os
from dotenv import load_dotenv

load_dotenv()

# Discord
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
COMMAND_PREFIX = "/"

# Monitoring
DEFAULT_INTERVAL = 30          # seconds between checks
MIN_INTERVAL = 10              # minimum allowed interval
MAX_SITES = 3                  # maximum sites per guild

# Browser
REQUEST_TIMEOUT = 30           # seconds (playwright needs more than aiohttp)

# Storage
DB_PATH = "data/sites.db"