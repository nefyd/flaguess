import json
import os

from dotenv import load_dotenv
from interactions import Intents

from flaguess import Flaguess

load_dotenv()
TOKEN = os.getenv("TOKEN")

with open("countries.json", "r", encoding="utf-8") as f:
  country_names: list[str] = json.load(f)

bot = Flaguess(
  intents=Intents.DEFAULT | Intents.MESSAGE_CONTENT,
  send_not_ready_messages=True,
  country_names=country_names,
  rest_countries_version=3.1,
  token=TOKEN,
)

bot.start()
