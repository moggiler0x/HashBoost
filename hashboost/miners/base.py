"""Общий интерфейс клиентов API майнеров."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from ..models import MinerStats


class MinerApiError(RuntimeError):
    """Майнер не отвечает или вернул непонятный ответ."""


class MinerClient(ABC):
    name = "miner"

    def __init__(self, api_url: str, timeout: float = 3.0):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    @abstractmethod
    def parse(self, payload: Any) -> MinerStats:
        """Разбор JSON-ответа майнера (отделён от сети, чтобы тестировать на образцах)."""

    def fetch(self) -> MinerStats:
        return self.parse(self._get_json(self.api_url + "/"))

    def _get_json(self, url: str) -> Any:
        try:
            # Локальный API майнера: прокси здесь не нужен и только мешает
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise MinerApiError(f"{self.name}: API {url} недоступен: {exc}") from exc


def dig(data: Any, path: str, default: Any = None) -> Any:
    """Достаёт значение по пути ``a.b.0.c``; на любом промахе возвращает ``default``."""
    if not path:
        return data
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return cur


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def now() -> float:
    return time.monotonic()
