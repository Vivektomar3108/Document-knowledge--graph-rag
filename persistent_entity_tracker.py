"""
Persistent Entity ID Tracker

This module provides a thread-safe, persistent tracking mechanism for processed entity IDs
during the entity merging pipeline. It maintains an in-memory set for fast lookups while
ensuring all changes are immediately persisted to disk via JSON files.

The tracker uses atomic writes to prevent data corruption and supports graceful recovery
from interruptions or crashes.
"""

import json
import os
import threading
from datetime import datetime
from typing import Set, List, Optional
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)


class PersistentEntityIDTracker:
    """
    Thread-safe persistent tracker for processed entity IDs.

    Features:
    - In-memory set for O(1) lookup performance
    - Immediate persistence on every add operation
    - Atomic writes to prevent corruption
    - Thread-safe operations with lock
    - Automatic recovery from existing files
    - Batch operations for efficiency

    Usage:
        tracker = PersistentEntityIDTracker("path/to/processed_entity_ids.json")
        tracker.add("entity-uuid-123")
        if tracker.contains("entity-uuid-123"):
            print("Already processed")
    """

    def __init__(self, file_path: str, auto_save: bool = True):
        """
        Initialize the persistent entity ID tracker.

        Args:
            file_path: Path to the JSON file for persistence
            auto_save: If True, automatically save on every add operation
        """
        self.file_path = Path(file_path)
        self.auto_save = auto_save
        self._entity_ids: Set[str] = set()
        self._lock = threading.Lock()
        self._modified = False

        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing data if file exists
        self._load()

        logger.info(f"📊 PersistentEntityIDTracker initialized at {self.file_path}")
        logger.info(f"   Loaded {len(self._entity_ids)} existing entity IDs")

    def _load(self) -> None:
        """
        Load entity IDs from persistent storage.
        Internal method called during initialization.
        """
        if not self.file_path.exists():
            logger.info(f"   No existing tracker file found. Starting fresh.")
            return

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate data structure
            if not isinstance(data, dict):
                logger.warning(f"   Invalid tracker file format. Starting fresh.")
                return

            entity_ids = data.get('processed_entity_ids', [])
            if not isinstance(entity_ids, list):
                logger.warning(f"   Invalid entity IDs format. Starting fresh.")
                return

            self._entity_ids = set(entity_ids)
            last_updated = data.get('last_updated', 'Unknown')
            total_count = data.get('total_count', len(self._entity_ids))

            logger.info(f"   ✅ Loaded {total_count} entity IDs from tracker")
            logger.info(f"   📅 Last updated: {last_updated}")

        except json.JSONDecodeError as e:
            logger.error(f"   ❌ Failed to parse tracker file: {e}")
            logger.warning(f"   Starting with empty tracker")
            self._entity_ids = set()
        except Exception as e:
            logger.error(f"   ❌ Error loading tracker file: {e}")
            logger.warning(f"   Starting with empty tracker")
            self._entity_ids = set()

    def _save(self) -> None:
        """
        Save entity IDs to persistent storage using atomic write.
        Uses temp file + rename pattern to ensure atomicity.
        """
        try:
            # Prepare data structure
            data = {
                'processed_entity_ids': sorted(list(self._entity_ids)),
                'last_updated': datetime.now().isoformat(),
                'total_count': len(self._entity_ids)
            }

            # Write to temporary file first (atomic write pattern)
            temp_file = self.file_path.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename (replaces existing file)
            temp_file.replace(self.file_path)

            self._modified = False

            logger.debug(f"   💾 Saved {len(self._entity_ids)} entity IDs to tracker")

        except Exception as e:
            logger.error(f"   ❌ Failed to save tracker file: {e}")
            # Don't raise - we can continue with in-memory tracking

    def add(self, entity_id: str) -> bool:
        """
        Add a single entity ID to the tracker.

        Args:
            entity_id: The entity ID to add

        Returns:
            True if the entity was newly added, False if it already existed
        """
        with self._lock:
            if entity_id in self._entity_ids:
                return False  # Already exists

            self._entity_ids.add(entity_id)
            self._modified = True

            if self.auto_save:
                self._save()

            return True

    def add_multiple(self, entity_ids: List[str]) -> int:
        """
        Add multiple entity IDs in a batch operation.
        More efficient than calling add() repeatedly.

        Args:
            entity_ids: List of entity IDs to add

        Returns:
            Number of newly added entity IDs (excludes duplicates)
        """
        if not entity_ids:
            return 0

        with self._lock:
            initial_size = len(self._entity_ids)
            self._entity_ids.update(entity_ids)
            newly_added = len(self._entity_ids) - initial_size

            if newly_added > 0:
                self._modified = True
                if self.auto_save:
                    self._save()

            return newly_added

    def contains(self, entity_id: str) -> bool:
        """
        Check if an entity ID is already tracked (O(1) lookup).

        Args:
            entity_id: The entity ID to check

        Returns:
            True if the entity ID is tracked, False otherwise
        """
        with self._lock:
            return entity_id in self._entity_ids

    def get_all(self) -> Set[str]:
        """
        Get a copy of all tracked entity IDs.

        Returns:
            Set of all tracked entity IDs (copy, not reference)
        """
        with self._lock:
            return self._entity_ids.copy()

    def get_count(self) -> int:
        """
        Get the total count of tracked entity IDs.

        Returns:
            Number of tracked entity IDs
        """
        with self._lock:
            return len(self._entity_ids)

    def remove(self, entity_id: str) -> bool:
        """
        Remove an entity ID from the tracker.

        Args:
            entity_id: The entity ID to remove

        Returns:
            True if the entity was removed, False if it didn't exist
        """
        with self._lock:
            if entity_id not in self._entity_ids:
                return False

            self._entity_ids.remove(entity_id)
            self._modified = True

            if self.auto_save:
                self._save()

            return True

    def clear(self) -> None:
        """
        Clear all tracked entity IDs and remove the persistent file.
        Use with caution - this operation cannot be undone.
        """
        with self._lock:
            self._entity_ids.clear()
            self._modified = True

            # Remove the persistent file
            if self.file_path.exists():
                try:
                    self.file_path.unlink()
                    logger.info(f"   🗑️  Cleared tracker and removed file: {self.file_path}")
                except Exception as e:
                    logger.error(f"   ❌ Failed to remove tracker file: {e}")

            # Save empty state
            if self.auto_save:
                self._save()

    def flush(self) -> None:
        """
        Force save to disk if there are unsaved changes.
        Useful when auto_save is disabled or for explicit checkpointing.
        """
        with self._lock:
            if self._modified:
                self._save()

    def __len__(self) -> int:
        """Return the number of tracked entity IDs."""
        return self.get_count()

    def __contains__(self, entity_id: str) -> bool:
        """Support 'in' operator for checking entity IDs."""
        return self.contains(entity_id)

    def __repr__(self) -> str:
        """String representation of the tracker."""
        return f"PersistentEntityIDTracker(file={self.file_path}, count={len(self._entity_ids)})"

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure final save."""
        self.flush()
        return False


def create_tracker(checkpoint_dir: str, filename: str = "processed_entity_ids.json") -> PersistentEntityIDTracker:
    """
    Factory function to create a tracker instance with standard configuration.

    Args:
        checkpoint_dir: Directory for checkpoint files
        filename: Name of the tracker JSON file

    Returns:
        Configured PersistentEntityIDTracker instance
    """
    file_path = os.path.join(checkpoint_dir, filename)
    return PersistentEntityIDTracker(file_path, auto_save=True)
