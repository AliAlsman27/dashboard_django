import firebase_admin
from firebase_admin import credentials, db

_initialized = False

def init_firebase():
    global _initialized
    if _initialized:
        return

    cred = credentials.Certificate("demo/creds/slu-project-3bc4e-firebase-adminsdk-fbsvc-23abff6e4b.json")
    firebase_admin.initialize_app(cred, {
        "databaseURL": "https://slu-project-3bc4e-default-rtdb.firebaseio.com/"
    })
    _initialized = True

def read_device(device_id: str):
    init_firebase()
    # Adjust if your path is different
    return db.reference(f"stations/{device_id}").get()
