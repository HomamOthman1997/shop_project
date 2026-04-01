import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "pvadeals_services.json")

with open(_PATH, encoding="utf-8") as f:
    DATA = json.load(f)
