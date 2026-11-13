import json
import os
import time
 
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
LOCK_FILE = STATE_FILE + ".lock"
LOCK_TIMEOUT_S = 2.0
LOCK_STALE_S = 5.0  
 
 
def _acquire_lock():
    start = time.time()
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(LOCK_FILE)
                if age > LOCK_STALE_S:
                    os.remove(LOCK_FILE)
                    continue
            except OSError:
                pass
 
            if time.time() - start > LOCK_TIMEOUT_S:
                return False
            time.sleep(0.01)
 
 
def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass
 
 
def read_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}
 
 
def update_state(patch: dict) -> dict:
    got_lock = _acquire_lock()
    try:
        state = read_state()
        state.update(patch)
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=4)
        for attempt in range(5):
            try:
                os.replace(tmp_path, STATE_FILE)
                break
            except PermissionError:
                time.sleep(0.05)  # Aspetta 50ms e riprova
        else:
            print("[WARNING] Impossibile aggiornare state.json: file bloccato.")
        return state
    finally:
        if got_lock:
            _release_lock()
 
 
def write_state(full_state: dict) -> None:
    got_lock = _acquire_lock()
    try:
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(full_state, f, indent=4)
        os.replace(tmp_path, STATE_FILE)
    finally:
        if got_lock:
            _release_lock()