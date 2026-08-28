"""
Entity merging checkpoint utilities for resumable processing.

This module works in conjunction with PersistentEntityIDTracker to provide
comprehensive checkpoint functionality for the entity merging pipeline.
"""
import os
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime
from logger import setup_logger

logger = setup_logger(__name__)


class EntityMergingCheckpoint:
    """
    Manages checkpoints for entity merging to enable resumable processing.
    """

    def __init__(self, checkpoint_dir: str):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoint files
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.state_file = self.checkpoint_dir / "merging_state.json"
        self.processed_entities_file = self.checkpoint_dir / "processed_entities.csv"

        logger.info(f"📁 Entity merging checkpoint directory: {self.checkpoint_dir}")

    def save_checkpoint(self, merged_entities: List[dict], processed_entity_ids: Set[str],
                       last_processed_index: int, total_rows: int):
        """
        Save checkpoint of entity merging progress.

        Note: This saves a snapshot of processed_entity_ids for recovery purposes.
        The primary source of truth for entity ID tracking is now the
        PersistentEntityIDTracker (processed_entity_ids.json).

        Args:
            merged_entities: List of merged entity dictionaries
            processed_entity_ids: Set of entity IDs that have been processed
            last_processed_index: Index of last processed entity
            total_rows: Total number of entities to process
        """
        try:
            # Save state metadata
            state = {
                'last_processed_index': last_processed_index,
                'total_rows': total_rows,
                'processed_count': len(merged_entities),
                'processed_entity_ids': sorted(list(processed_entity_ids)),
                'timestamp': datetime.now().isoformat(),
                'progress_percent': (last_processed_index / total_rows * 100) if total_rows > 0 else 0
            }

            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

            # Save merged entities to CSV
            if merged_entities:
                df = pd.DataFrame(merged_entities)
                df.to_csv(self.processed_entities_file, index=False)

            logger.info(f"💾 Checkpoint saved: {len(merged_entities)} entities processed "
                       f"({last_processed_index}/{total_rows}, {state['progress_percent']:.1f}%)")

        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}", exc_info=True)

    def load_checkpoint(self) -> Optional[Dict]:
        """
        Load checkpoint state if it exists.

        Returns:
            Dictionary with checkpoint state or None if no checkpoint exists
        """
        if not self.state_file.exists():
            logger.info("No checkpoint found. Starting from beginning.")
            return None

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            logger.info(f"📂 Checkpoint loaded: {state['processed_count']} entities processed "
                       f"({state['progress_percent']:.1f}% complete)")
            logger.info(f"   Last processed index: {state['last_processed_index']}/{state['total_rows']}")

            return state

        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}", exc_info=True)
            return None

    def load_processed_entities(self) -> List[dict]:
        """
        Load previously processed entities from checkpoint.

        Returns:
            List of entity dictionaries
        """
        if not self.processed_entities_file.exists():
            return []

        try:
            df = pd.read_csv(self.processed_entities_file)
            entities = df.to_dict('records')
            logger.info(f"📥 Loaded {len(entities)} previously processed entities from checkpoint")
            return entities
        except Exception as e:
            logger.error(f"Failed to load processed entities: {e}", exc_info=True)
            return []

    def clear_checkpoint(self):
        """Clear checkpoint files."""
        try:
            if self.state_file.exists():
                self.state_file.unlink()
            if self.processed_entities_file.exists():
                self.processed_entities_file.unlink()
            logger.info("✅ Checkpoint cleared")
        except Exception as e:
            logger.error(f"Failed to clear checkpoint: {e}")

    def get_resume_info(self) -> Optional[Dict]:
        """
        Get information about resumable state.

        Returns:
            Dictionary with resume information or None
        """
        state = self.load_checkpoint()
        if not state:
            return None

        return {
            'can_resume': True,
            'last_processed_index': state['last_processed_index'],
            'total_rows': state['total_rows'],
            'progress_percent': state['progress_percent'],
            'processed_count': state['processed_count'],
            'timestamp': state['timestamp']
        }

    def verify_tracker_sync(self, tracker_count: int) -> Dict[str, any]:
        """
        Verify that the checkpoint and tracker are in sync.

        Args:
            tracker_count: Count from PersistentEntityIDTracker

        Returns:
            Dictionary with sync status information
        """
        state = self.load_checkpoint()
        if not state:
            return {
                'in_sync': True,
                'message': 'No checkpoint exists yet',
                'checkpoint_count': 0,
                'tracker_count': tracker_count
            }

        checkpoint_count = len(state.get('processed_entity_ids', []))
        in_sync = checkpoint_count == tracker_count

        return {
            'in_sync': in_sync,
            'checkpoint_count': checkpoint_count,
            'tracker_count': tracker_count,
            'difference': abs(checkpoint_count - tracker_count),
            'message': 'In sync' if in_sync else f'Mismatch: checkpoint has {checkpoint_count}, tracker has {tracker_count}'
        }
