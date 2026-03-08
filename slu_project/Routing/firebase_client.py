import os
import json
import firebase_admin
from firebase_admin import credentials, db

_initialized = False

def init_firebase():
    global _initialized
    if _initialized:
        return

    # 1. Try to get JSON content from environment variable
    json_creds = os.environ.get("FIREBASE_CREDENTIALS_JSON")

    if json_creds:
        try:
            cred_dict = json.loads(json_creds)
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            print(f"Error parsing FIREBASE_CREDENTIALS_JSON: {e}")
            cred = None
    else:
        # 2. Fall back to file path from environment or hardcoded default
        default_path = "demo/creds/slu-project-3bc4e-firebase-adminsdk-fbsvc-23abff6e4b.json"
        cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", default_path)

        # Make path absolute if it's relative to BASE_DIR (one level up from demo)
        if not os.path.isabs(cred_path):
            from django.conf import settings
            cred_path = os.path.join(settings.BASE_DIR, cred_path)

        cred = credentials.Certificate(cred_path)

    db_url = os.environ.get(
        "FIREBASE_DATABASE_URL",
        "https://slu-project-3bc4e-default-rtdb.firebaseio.com/",
    )

    firebase_admin.initialize_app(cred, {"databaseURL": db_url})
    _initialized = True


def read_device(device_id: str):
    init_firebase()
    return db.reference(f"stations/{device_id}").get()


def get_all_stations() -> dict:
    """Return all stations from Firebase as a flat dict {id: data}."""
    init_firebase()
    return db.reference("stations").get() or {}


def get_stations_by_zone(zone_name: str) -> dict:
    """Return stations belonging to a specific zone."""
    all_stations = get_all_stations()
    return {
        k: v
        for k, v in all_stations.items()
        if isinstance(v, dict) and v.get("zone") == zone_name
    }


def get_zone_names() -> list:
    """Return sorted list of unique zone names."""
    all_stations = get_all_stations()
    zones = set()
    for s in all_stations.values():
        if isinstance(s, dict) and s.get("zone"):
            zones.add(s["zone"])
    return sorted(zones)
