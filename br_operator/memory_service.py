"""
Memory Service - Conversation history storage for BlackRoad OS Operator
Stores conversation turns for context-aware chat responses

For Railway deployment, uses JSON file storage
For Cloudflare Workers, can be adapted to use KV

@owner Alexa Louise Amundson
@system BlackRoad OS
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Configuration
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "false").lower() in ("true", "1", "yes")
MEMORY_MAX_TURNS = int(os.getenv("MEMORY_MAX_TURNS", "20"))
MEMORY_STORAGE_PATH = Path(os.getenv("MEMORY_STORAGE_PATH", "/tmp/cece_memory"))


class ConversationMemory:
    """Manages conversation memory for users."""

    def __init__(self, storage_path: Optional[Path] = None, max_turns: int = MEMORY_MAX_TURNS):
        self.storage_path = storage_path or MEMORY_STORAGE_PATH
        self.max_turns = max_turns
        self.enabled = MEMORY_ENABLED

        # Ensure storage directory exists
        if self.enabled:
            self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_user_file(self, user_id: str) -> Path:
        """Get the storage file path for a user."""
        # Sanitize user_id to prevent directory traversal
        safe_user_id = "".join(c for c in user_id if c.isalnum() or c in ("-", "_"))
        return self.storage_path / f"{safe_user_id}.json"

    def _load_memory(self, user_id: str) -> List[Dict[str, Any]]:
        """Load conversation memory for a user."""
        if not self.enabled:
            return []

        user_file = self._get_user_file(user_id)

        if not user_file.exists():
            return []

        try:
            with open(user_file, "r") as f:
                data = json.load(f)
                return data.get("turns", [])
        except (json.JSONDecodeError, IOError):
            # If file is corrupted, start fresh
            return []

    def _save_memory(self, user_id: str, turns: List[Dict[str, Any]]) -> None:
        """Save conversation memory for a user."""
        if not self.enabled:
            return

        user_file = self._get_user_file(user_id)

        # Keep only the last max_turns
        if len(turns) > self.max_turns:
            turns = turns[-self.max_turns:]

        data = {
            "user_id": user_id,
            "turns": turns,
            "updated_at": datetime.utcnow().isoformat(),
        }

        try:
            with open(user_file, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            # Log error but don't crash - memory is not critical
            print(f"Warning: Failed to save memory for {user_id}: {e}")

    def store_turn(
        self,
        user_id: str,
        user_message: str,
        assistant_reply: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Store a conversation turn.

        Args:
            user_id: User identifier
            user_message: User's message
            assistant_reply: Assistant's reply
            metadata: Optional metadata (model, trace, etc.)

        Returns:
            Dict with status information
        """
        if not self.enabled:
            return {
                "stored": False,
                "reason": "memory_disabled",
                "user_id": user_id,
            }

        turns = self._load_memory(user_id)

        turn = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_message": user_message,
            "assistant_reply": assistant_reply,
            "metadata": metadata or {},
        }

        turns.append(turn)
        self._save_memory(user_id, turns)

        return {
            "stored": True,
            "user_id": user_id,
            "turn_count": len(turns),
            "max_turns": self.max_turns,
        }

    def get_history(
        self,
        user_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get conversation history for a user.

        Args:
            user_id: User identifier
            limit: Optional limit on number of turns to return

        Returns:
            List of conversation turns (most recent first)
        """
        if not self.enabled:
            return []

        turns = self._load_memory(user_id)

        # Most recent first
        turns = list(reversed(turns))

        if limit is not None and limit > 0:
            turns = turns[:limit]

        return turns

    def clear_history(self, user_id: str) -> Dict[str, Any]:
        """
        Clear conversation history for a user.

        Args:
            user_id: User identifier

        Returns:
            Dict with status information
        """
        if not self.enabled:
            return {
                "cleared": False,
                "reason": "memory_disabled",
                "user_id": user_id,
            }

        user_file = self._get_user_file(user_id)

        if user_file.exists():
            try:
                user_file.unlink()
                return {
                    "cleared": True,
                    "user_id": user_id,
                }
            except IOError as e:
                return {
                    "cleared": False,
                    "reason": f"delete_failed: {e}",
                    "user_id": user_id,
                }
        else:
            return {
                "cleared": True,
                "user_id": user_id,
                "note": "no_history_found",
            }

    def build_context_prompt(
        self,
        user_id: str,
        num_turns: int = 5,
    ) -> str:
        """
        Build a context prompt from recent conversation history.

        Args:
            user_id: User identifier
            num_turns: Number of recent turns to include

        Returns:
            Formatted context string for inclusion in prompts
        """
        if not self.enabled:
            return ""

        turns = self.get_history(user_id, limit=num_turns)

        if not turns:
            return ""

        context_lines = ["Recent conversation history:"]

        # Turns are already in reverse order (most recent first)
        # Reverse again to show chronologically
        for turn in reversed(turns):
            context_lines.append(f"User: {turn['user_message']}")
            context_lines.append(f"Assistant: {turn['assistant_reply']}")
            context_lines.append("")

        return "\n".join(context_lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get memory service statistics."""
        if not self.enabled:
            return {
                "enabled": False,
                "total_users": 0,
            }

        # Count user files
        try:
            user_files = list(self.storage_path.glob("*.json"))
            total_users = len(user_files)

            return {
                "enabled": True,
                "total_users": total_users,
                "max_turns_per_user": self.max_turns,
                "storage_path": str(self.storage_path),
            }
        except Exception as e:
            return {
                "enabled": True,
                "error": str(e),
            }


# Singleton instance
_memory_service: Optional[ConversationMemory] = None


def get_memory_service() -> ConversationMemory:
    """Get the singleton memory service instance."""
    global _memory_service

    if _memory_service is None:
        _memory_service = ConversationMemory()

    return _memory_service
