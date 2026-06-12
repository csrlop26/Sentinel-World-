import json
import os
from datetime import datetime, timedelta

from data.models import ArbOpportunity

_TRACKER_FILE = "data/seen_opportunities.json"
_COOLDOWN_HOURS = 2  # re-alert same opportunity after 2 hours


class ArbitrageTracker:
    def __init__(self):
        self._seen: dict[str, str] = {}
        self._load()

    def _load(self):
        if os.path.exists(_TRACKER_FILE):
            try:
                with open(_TRACKER_FILE) as f:
                    self._seen = json.load(f)
            except Exception:
                self._seen = {}

    def _save(self):
        os.makedirs("data", exist_ok=True)
        with open(_TRACKER_FILE, "w") as f:
            json.dump(self._seen, f, indent=2)

    def seen(self, opp: ArbOpportunity) -> bool:
        key = opp.unique_key()
        if key not in self._seen:
            return False
        last_seen = datetime.fromisoformat(self._seen[key])
        return datetime.now() - last_seen < timedelta(hours=_COOLDOWN_HOURS)

    def mark_seen(self, opp: ArbOpportunity):
        self._seen[opp.unique_key()] = datetime.now().isoformat()
        self._save()

    def cleanup_old(self):
        cutoff = datetime.now() - timedelta(hours=24)
        self._seen = {
            k: v
            for k, v in self._seen.items()
            if datetime.fromisoformat(v) > cutoff
        }
        self._save()
