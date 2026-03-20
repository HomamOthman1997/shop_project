import json
import os

BASE_DIR = os.path.dirname(__file__)
USAGE_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "usage_stats.json"))
TOP_FILE = os.path.normpath(os.path.join(BASE_DIR, "..", "data", "top_services.json"))


def load_usage():
    if not os.path.exists(USAGE_FILE):
        return {}

    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_usage(data):
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_top_services():
    usage = load_usage()

    sorted_usage = dict(
        sorted(usage.items(), key=lambda x: x[1], reverse=True)[:10]
    )

    with open(TOP_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_usage, f, indent=2, ensure_ascii=False)

    return sorted_usage


def increment_usage(service_name: str):
    service_name = service_name.lower().strip()

    usage = load_usage()

    if service_name not in usage:
        usage[service_name] = 0

    usage[service_name] += 1

    save_usage(usage)
    generate_top_services()

    return usage[service_name]
