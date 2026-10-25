"""Менеджер профилей: лучший пресет для каждой карты под каждый алгоритм."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ..models import OcSettings


@dataclass
class Profile:
    gpu_uid: str
    gpu_name: str
    algorithm: str
    settings: OcSettings
    hashrate: float = 0.0
    power_w: float = 0.0
    net_per_day: float = 0.0
    created_at: float = field(default_factory=time.time)
    note: str = ""

    @property
    def efficiency(self) -> float:
        return self.hashrate / self.power_w if self.power_w else 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["settings"] = self.settings.to_dict()
        return data

    @staticmethod
    def from_dict(data: dict) -> "Profile":
        data = dict(data)
        data["settings"] = OcSettings.from_dict(data.get("settings", {}))
        known = Profile.__dataclass_fields__
        return Profile(**{k: v for k, v in data.items() if k in known})


class ProfileStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Profile]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._data = {uid: {algo: Profile.from_dict(p) for algo, p in algos.items()} for uid, algos in raw.items()}

    def _save(self) -> None:
        raw = {uid: {algo: p.to_dict() for algo, p in algos.items()} for uid, algos in self._data.items()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def put(self, profile: Profile) -> None:
        with self._lock:
            self._data.setdefault(profile.gpu_uid, {})[profile.algorithm] = profile
            self._save()

    def get(self, gpu_uid: str, algorithm: str) -> Optional[Profile]:
        return self._data.get(gpu_uid, {}).get(algorithm)

    def delete(self, gpu_uid: str, algorithm: str) -> None:
        with self._lock:
            if self._data.get(gpu_uid, {}).pop(algorithm, None) is not None:
                self._save()

    def all(self) -> list[Profile]:
        return [p for algos in self._data.values() for p in algos.values()]

    def algorithms(self) -> list[str]:
        return sorted({p.algorithm for p in self.all()})
