"""
Persistence layer for conversations.

Each chat is stored as a single JSON file under:
  ~/.local/share/localai/chats/<uuid>.json

Public API
----------
ChatStore.list_chats()        -> [Chat, ...]   sorted newest first
ChatStore.load_chat(id)       -> Chat | None
ChatStore.save_chat(chat)     -> None          (create or overwrite)
ChatStore.delete_chat(id)     -> None
ChatStore.new_chat(...)       -> Chat
"""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


# XDG data dir: ~/.local/share/localai/chats/
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "localai" / "chats"


@dataclass
class Message:
    role: str           # "user" | "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Chat:
    id: str
    title: str
    created_at: str
    model: Optional[str]            # hf_id of the model used (may be None)
    system_prompt: str
    messages: List[Message] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Serialisation helpers
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Chat":
        msgs = [Message(**m) for m in d.get("messages", [])]
        return cls(
            id=d["id"],
            title=d["title"],
            created_at=d["created_at"],
            model=d.get("model"),
            system_prompt=d.get("system_prompt", "You are a helpful assistant."),
            messages=msgs,
        )

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #

    def auto_title(self) -> str:
        """Return a title derived from the first user message (first ~6 words)."""
        for m in self.messages:
            if m.role == "user" and m.content.strip():
                words = m.content.strip().split()
                return " ".join(words[:6]) + ("…" if len(words) > 6 else "")
        return "New Chat"

    def last_updated(self) -> str:
        """ISO timestamp of the most recent message, or created_at."""
        if self.messages:
            return self.messages[-1].timestamp
        return self.created_at


class ChatStore:
    """Static helper methods — no instance needed."""

    @staticmethod
    def _path(chat_id: str) -> Path:
        return DATA_DIR / f"{chat_id}.json"

    @staticmethod
    def _ensure_dir():
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_chats() -> List[Chat]:
        """Return all chats sorted by most recently updated."""
        ChatStore._ensure_dir()
        chats = []
        for p in DATA_DIR.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    chats.append(Chat.from_dict(json.load(f)))
            except (json.JSONDecodeError, KeyError, OSError):
                continue  # skip corrupted files
        chats.sort(key=lambda c: c.last_updated(), reverse=True)
        return chats

    @staticmethod
    def load_chat(chat_id: str) -> Optional[Chat]:
        p = ChatStore._path(chat_id)
        if not p.exists():
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return Chat.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    @staticmethod
    def save_chat(chat: Chat) -> None:
        ChatStore._ensure_dir()
        with open(ChatStore._path(chat.id), "w", encoding="utf-8") as f:
            json.dump(chat.to_dict(), f, indent=2, ensure_ascii=False)

    @staticmethod
    def delete_chat(chat_id: str) -> None:
        p = ChatStore._path(chat_id)
        if p.exists():
            p.unlink()

    @staticmethod
    def new_chat(system_prompt: str, model: Optional[str] = None) -> Chat:
        """Create a new Chat object (not yet persisted)."""
        now = datetime.now(timezone.utc).isoformat()
        return Chat(
            id=str(uuid.uuid4()),
            title="New Chat",
            created_at=now,
            model=model,
            system_prompt=system_prompt,
            messages=[],
        )