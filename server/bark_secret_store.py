#!/usr/bin/env python3
import json
import re
import threading
from pathlib import Path

from storage_security import (
    atomic_write_private,
    ensure_private_directory,
    ensure_private_file,
)


_DESTINATION_ID = re.compile(r"^[A-Za-z0-9_-]{3,96}$")


class BarkSecretStore:
    """Small private key store kept outside the public destination database."""

    def __init__(self, path):
        self.path = Path(path)
        ensure_private_directory(self.path.parent)
        self.lock = threading.RLock()
        ensure_private_file(self.path, required=False)

    def _validated_id(self, destination_id):
        value = str(destination_id or "").strip()
        if not _DESTINATION_ID.fullmatch(value):
            raise ValueError("invalid Bark destination id")
        return value

    def _load(self):
        if not ensure_private_file(self.path, required=False):
            return {}
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except Exception as exc:
            raise RuntimeError("Bark secret store is unreadable") from exc
        if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in data.items()
        ):
            raise RuntimeError("Bark secret store has invalid data")
        return data

    def _save(self, data):
        atomic_write_private(
            self.path,
            json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            ),
        )

    def put(self, destination_id, device_key):
        destination_id = self._validated_id(destination_id)
        device_key = str(device_key or "").strip()
        if len(device_key) < 16 or len(device_key) > 512:
            raise ValueError("invalid Bark device key")
        with self.lock:
            data = self._load()
            data[destination_id] = device_key
            self._save(data)

    def get(self, destination_id):
        destination_id = self._validated_id(destination_id)
        with self.lock:
            return self._load().get(destination_id)

    def delete(self, destination_id):
        destination_id = self._validated_id(destination_id)
        with self.lock:
            data = self._load()
            if destination_id not in data:
                return False
            data.pop(destination_id, None)
            self._save(data)
            return True
