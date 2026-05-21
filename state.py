import json
import logging
import os
import tempfile
import threading

logger = logging.getLogger(__name__)

# On Railway, point STATE_FILE at a mounted volume to survive redeploys.
STATE_FILE = os.getenv("STATE_FILE", "state.json")
WRITTEN_CAP_PER_CHANNEL = 1000

_lock = threading.Lock()
_state: dict = {}
_loaded = False


def _ensure_loaded() -> None:
    global _state, _loaded
    if _loaded:
        return
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state file, starting fresh: {e}")
            _state = {}
    else:
        _state = {}
    _state.setdefault("channels", {})
    _loaded = True


def _channel_state(channel: str) -> dict:
    return _state["channels"].setdefault(
        channel, {"last_seen_id": 0, "written_ids": []}
    )


def _persist() -> None:
    dir_name = os.path.dirname(os.path.abspath(STATE_FILE)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_last_seen(channel: str) -> int:
    with _lock:
        _ensure_loaded()
        return _channel_state(channel)["last_seen_id"]


def mark_seen(channel: str, message_id: int) -> None:
    with _lock:
        _ensure_loaded()
        cs = _channel_state(channel)
        if message_id > cs["last_seen_id"]:
            cs["last_seen_id"] = message_id
            _persist()


def was_written(channel: str, message_id: int) -> bool:
    with _lock:
        _ensure_loaded()
        return message_id in _channel_state(channel)["written_ids"]


def mark_written(channel: str, message_id: int) -> None:
    with _lock:
        _ensure_loaded()
        cs = _channel_state(channel)
        if message_id in cs["written_ids"]:
            return
        cs["written_ids"].append(message_id)
        if len(cs["written_ids"]) > WRITTEN_CAP_PER_CHANNEL:
            cs["written_ids"] = cs["written_ids"][-WRITTEN_CAP_PER_CHANNEL:]
        _persist()
