"""
Iterative Entity Deduplication Module

This module implements an iterative approach to entity deduplication where:
1. Round 1 processes all entities against the original collection
2. After Round 1, a working collection is created with merged entity embeddings
3. Subsequent rounds process against the working collection until convergence
4. Convergence = no new merges in a round

Key features:
- Dual collection architecture (original preserved, working collection updated)
- Full checkpoint/resume support for pause/resume capability
- Round-by-round progress tracking
- Merge history and lineage tracking
"""

import os
import json
import time
import asyncio
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict

from logger import get_logger
from entity_utils import (
    process_entity_with_backoff,
    APIKeyManager,
    merge_descriptions,
    merge_aliases,
    merge_quotes,
    merge_keywords_from_entities,
    keywords_to_list,
    extract_metadata_from_row,
    aggregate_metadata,
    parse_keywords_from_json
)
from persistent_entity_tracker import PersistentEntityIDTracker
from cost_tracking_utils import TokenUsageStats

logger = get_logger(__name__)


# Column mapping: merged_* columns → standard columns
COLUMN_NORMALIZATION_MAP = {
    'root_entity_id': 'entity_id',
    'merged_description': 'entity_description',
    'merged_references': 'references',
    'merged_aliases': 'aliases',
    'merged_quotes': 'quotes',
    'merged_keywords': 'keywords',
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize column names from merged_* format to standard format.

    This ensures that output from one round can be used as input for the next round,
    since process_entity_with_backoff expects standard column names like
    'entity_description' not 'merged_description'.

    Args:
        df: DataFrame with potentially merged_* column names

    Returns:
        DataFrame with normalized column names
    """
    rename_map = {}
    for old_col, new_col in COLUMN_NORMALIZATION_MAP.items():
        if old_col in df.columns and new_col not in df.columns:
            rename_map[old_col] = new_col
            logger.debug(f"  Mapping column: {old_col} → {new_col}")

    if rename_map:
        logger.info(f"📋 Normalizing {len(rename_map)} column names for processing")
        df = df.rename(columns=rename_map)

    return df


@dataclass
class RoundStatistics:
    """Statistics for a single deduplication round."""
    round_number: int
    entities_start: int
    entities_end: int = 0
    merges_count: int = 0
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "pending"  # pending, in_progress, completed, failed
    output_file: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IterativeDedupState:
    """Complete state for iterative deduplication process."""
    session_id: str
    status: str = "initialized"  # initialized, in_progress, converged, failed

    # Collection names
    original_collection: str = ""
    working_collection: str = ""

    # Round tracking
    current_round: int = 1
    total_initial_entities: int = 0
    max_rounds: int = 10

    # Round history
    round_history: List[Dict] = field(default_factory=list)

    # Current round state (for resume within a round)
    current_round_state: Dict = field(default_factory=lambda: {
        "processed_entity_ids": [],
        "pending_entity_ids": [],
        "merged_this_round": {},
        "last_processed_index": -1,
        "entities_processed_count": 0
    })

    # Configuration
    config: Dict = field(default_factory=lambda: {
        "candidates_per_search": 40,
        "checkpoint_frequency": 100,
        "min_merge_threshold": 0
    })

    # Timestamps
    created_at: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'IterativeDedupState':
        return cls(**data)


class IterativeDedupCheckpoint:
    """
    Manages checkpoints for iterative deduplication process.
    Enables pause/resume at any point during processing.
    """

    def __init__(self, checkpoint_dir: str, session_id: Optional[str] = None):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Base directory for checkpoint files
            session_id: Optional session ID (auto-generated if not provided)
        """
        self.session_id = session_id or f"iterative_dedup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.checkpoint_dir = Path(checkpoint_dir) / self.session_id
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.state_file = self.checkpoint_dir / "iterative_dedup_state.json"
        self.round_entities_dir = self.checkpoint_dir / "round_outputs"
        self.merge_history_dir = self.checkpoint_dir / "merge_history"
        self.checkpoints_dir = self.checkpoint_dir / "checkpoints"

        # Create subdirectories
        self.round_entities_dir.mkdir(exist_ok=True)
        self.merge_history_dir.mkdir(exist_ok=True)
        self.checkpoints_dir.mkdir(exist_ok=True)

        logger.info(f"📁 Iterative dedup checkpoint initialized: {self.checkpoint_dir}")

    def save_state(self, state: IterativeDedupState) -> None:
        """Save the complete iterative dedup state."""
        state.last_updated = datetime.now().isoformat()
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug(f"💾 State saved: Round {state.current_round}, Status: {state.status}")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def load_state(self) -> Optional[IterativeDedupState]:
        """Load existing state if available."""
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            state = IterativeDedupState.from_dict(data)
            logger.info(f"📂 Loaded state: Round {state.current_round}, Status: {state.status}")
            return state
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None

    def save_round_checkpoint(self, round_num: int, entities: List[dict],
                              processed_ids: Set[str], last_index: int) -> None:
        """Save checkpoint within a round for resume capability."""
        checkpoint_file = self.checkpoints_dir / f"round{round_num}_checkpoint.json"
        entities_file = self.checkpoints_dir / f"round{round_num}_entities.csv"

        try:
            # Save checkpoint metadata
            checkpoint_data = {
                "round": round_num,
                "last_processed_index": last_index,
                "entities_count": len(entities),
                "processed_ids_count": len(processed_ids),
                "timestamp": datetime.now().isoformat()
            }
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2)

            # Save entities to CSV
            if entities:
                pd.DataFrame(entities).to_csv(entities_file, index=False)

            logger.debug(f"💾 Round {round_num} checkpoint saved: {len(entities)} entities")
        except Exception as e:
            logger.error(f"Failed to save round checkpoint: {e}")

    def load_round_checkpoint(self, round_num: int) -> Tuple[List[dict], int]:
        """Load checkpoint for a specific round."""
        checkpoint_file = self.checkpoints_dir / f"round{round_num}_checkpoint.json"
        entities_file = self.checkpoints_dir / f"round{round_num}_entities.csv"

        if not checkpoint_file.exists():
            return [], -1

        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)

            entities = []
            if entities_file.exists():
                entities = pd.read_csv(entities_file).to_dict('records')

            return entities, checkpoint_data.get('last_processed_index', -1)
        except Exception as e:
            logger.error(f"Failed to load round checkpoint: {e}")
            return [], -1

    def save_round_output(self, round_num: int, entities: List[dict]) -> str:
        """Save final output for a completed round."""
        output_file = self.round_entities_dir / f"unique_entities_round{round_num}.csv"
        try:
            df = pd.DataFrame(entities)

            # Apply keyword normalization to ensure clean data for subsequent rounds
            from keyword_normalization_utils import normalize_merged_keywords_column
            df = normalize_merged_keywords_column(df)

            df.to_csv(output_file, index=False)
            logger.info(f"💾 Round {round_num} output saved: {output_file}")
            return str(output_file)
        except Exception as e:
            logger.error(f"Failed to save round output: {e}")
            return ""

    def save_merge_history(self, round_num: int, merges: Dict[str, List[str]]) -> None:
        """Save merge history for a round."""
        history_file = self.merge_history_dir / f"merges_round{round_num}.json"
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "round": round_num,
                    "merges": merges,
                    "merge_count": len(merges),
                    "timestamp": datetime.now().isoformat()
                }, f, indent=2, ensure_ascii=False)
            logger.debug(f"💾 Merge history saved for round {round_num}: {len(merges)} merges")
        except Exception as e:
            logger.error(f"Failed to save merge history: {e}")

    def get_round_output_path(self, round_num: int) -> Path:
        """Get the output file path for a round."""
        return self.round_entities_dir / f"unique_entities_round{round_num}.csv"

    def clear_round_checkpoint(self, round_num: int) -> None:
        """Clear checkpoint files for a round after successful completion."""
        checkpoint_file = self.checkpoints_dir / f"round{round_num}_checkpoint.json"
        entities_file = self.checkpoints_dir / f"round{round_num}_entities.csv"

        for f in [checkpoint_file, entities_file]:
            if f.exists():
                f.unlink()


class IterativeDeduplication:
    """
    Orchestrates the iterative entity deduplication process.

    Process:
    1. Round 1: Process against original collection
    2. Create working collection from Round 1 results
    3. Round N: Process against working collection, update collection after round
    4. Repeat until no merges (convergence)
    """

    def __init__(
        self,
        input_csv_path: str,
        output_dir: str,
        original_collection: str,
        provider: str,
        model_name: str,
        working_collection_prefix: str = "dedup_working",
        max_rounds: int = 10,
        checkpoint_frequency: int = 100,
        stats_tracker: Optional[TokenUsageStats] = None,
        session_id: Optional[str] = None,
        process_id: Optional[str] = None
    ):
        """
        Initialize the iterative deduplication process.

        Args:
            input_csv_path: Path to merged results CSV (input for Round 1)
            output_dir: Directory for outputs and checkpoints
            original_collection: Name of the original Qdrant collection
            provider: LLM provider ("openai" or "google")
            model_name: Model name for the provider
            working_collection_prefix: Prefix for working collection name
            max_rounds: Maximum number of rounds before stopping
            checkpoint_frequency: Save checkpoint every N entities
            stats_tracker: Optional cost tracking
            session_id: Optional session ID for resuming
            process_id: Process ID for collection naming
        """
        self.input_csv_path = input_csv_path
        self.output_dir = Path(output_dir)
        self.original_collection = original_collection
        self.provider = provider
        self.model_name = model_name
        self.max_rounds = max_rounds
        self.checkpoint_frequency = checkpoint_frequency
        self.stats_tracker = stats_tracker
        self.process_id = process_id

        # Generate working collection name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.working_collection = f"{working_collection_prefix}_{timestamp}"

        # Initialize checkpoint manager
        self.checkpoint = IterativeDedupCheckpoint(
            str(self.output_dir / "iterative_dedup"),
            session_id
        )

        # Initialize or load state
        existing_state = self.checkpoint.load_state()
        if existing_state:
            self.state = existing_state
            self.working_collection = existing_state.working_collection
            logger.info(f"📂 Resuming session: {self.state.session_id}")
        else:
            self.state = IterativeDedupState(
                session_id=self.checkpoint.session_id,
                original_collection=original_collection,
                working_collection=self.working_collection,
                created_at=datetime.now().isoformat(),
                config={
                    "candidates_per_search": 40,
                    "checkpoint_frequency": checkpoint_frequency,
                    "min_merge_threshold": 0,
                    "max_rounds": max_rounds
                }
            )
            self.checkpoint.save_state(self.state)

        # API key manager
        self.api_key_manager = APIKeyManager()

        logger.info(f"🚀 Iterative Deduplication initialized")
        logger.info(f"   Session ID: {self.state.session_id}")
        logger.info(f"   Original collection: {self.original_collection}")
        logger.info(f"   Working collection: {self.working_collection}")
        logger.info(f"   Max rounds: {self.max_rounds}")

    async def run(self) -> str:
        """
        Run the complete iterative deduplication process.

        Returns:
            Path to the final unique entities CSV
        """
        logger.info("\n" + "="*70)
        logger.info("🔄 STARTING ITERATIVE ENTITY DEDUPLICATION")
        logger.info("="*70)

        start_time = datetime.now()
        self.state.status = "in_progress"
        self.checkpoint.save_state(self.state)

        try:
            # Determine starting point
            if self.state.current_round == 1 and not self.state.round_history:
                # Fresh start - load initial entities
                logger.info(f"📂 Loading input CSV: {self.input_csv_path}")
                initial_df = pd.read_csv(self.input_csv_path)
                self.state.total_initial_entities = len(initial_df)
                logger.info(f"   Total entities to process: {self.state.total_initial_entities}")

            # Main iteration loop
            while self.state.current_round <= self.max_rounds:
                round_start = datetime.now()

                logger.info(f"\n{'='*60}")
                logger.info(f"🔄 ROUND {self.state.current_round} STARTING")
                logger.info(f"{'='*60}")

                # Determine input for this round
                if self.state.current_round == 1:
                    round_input_path = self.input_csv_path
                    search_collection = self.original_collection
                else:
                    # Use previous round's output
                    prev_round_output = self.checkpoint.get_round_output_path(self.state.current_round - 1)
                    if not prev_round_output.exists():
                        logger.error(f"Previous round output not found: {prev_round_output}")
                        raise FileNotFoundError(f"Missing round {self.state.current_round - 1} output")
                    round_input_path = str(prev_round_output)
                    search_collection = self.working_collection

                # Process this round
                round_result = await self._process_round(
                    self.state.current_round,
                    round_input_path,
                    search_collection
                )

                round_duration = (datetime.now() - round_start).total_seconds()

                # Create round statistics
                round_stats = RoundStatistics(
                    round_number=self.state.current_round,
                    entities_start=round_result['entities_start'],
                    entities_end=round_result['entities_end'],
                    merges_count=round_result['merges_count'],
                    started_at=round_start.isoformat(),
                    completed_at=datetime.now().isoformat(),
                    duration_seconds=round_duration,
                    status="completed",
                    output_file=round_result['output_file']
                )

                self.state.round_history.append(round_stats.to_dict())

                logger.info(f"\n{'='*60}")
                logger.info(f"✅ ROUND {self.state.current_round} COMPLETED")
                logger.info(f"   Entities: {round_stats.entities_start} → {round_stats.entities_end}")
                logger.info(f"   Merges: {round_stats.merges_count}")
                logger.info(f"   Duration: {round_duration:.2f}s")
                logger.info(f"{'='*60}")

                # Check for convergence
                if round_result['merges_count'] == 0:
                    logger.info(f"\n🎉 CONVERGENCE REACHED after {self.state.current_round} rounds!")
                    self.state.status = "converged"
                    break

                # Prepare for next round
                if self.state.current_round < self.max_rounds:
                    # Update working collection for next round
                    await self._update_working_collection(
                        round_result['output_file'],
                        self.state.current_round
                    )

                # Clear current round checkpoint and move to next
                self.checkpoint.clear_round_checkpoint(self.state.current_round)
                self.state.current_round += 1
                self.state.current_round_state = {
                    "processed_entity_ids": [],
                    "pending_entity_ids": [],
                    "merged_this_round": {},
                    "last_processed_index": -1,
                    "entities_processed_count": 0
                }
                self.checkpoint.save_state(self.state)

            # Check if we hit max rounds without convergence
            if self.state.current_round > self.max_rounds:
                logger.warning(f"⚠️ Max rounds ({self.max_rounds}) reached without convergence")
                self.state.status = "max_rounds_reached"

            # Generate final output
            final_output = self._generate_final_output()

            total_duration = (datetime.now() - start_time).total_seconds()
            self._log_final_summary(total_duration)

            self.checkpoint.save_state(self.state)

            return final_output

        except Exception as e:
            logger.error(f"❌ Iterative deduplication failed: {e}", exc_info=True)
            self.state.status = "failed"
            self.checkpoint.save_state(self.state)
            raise

    async def _process_round(
        self,
        round_num: int,
        input_csv_path: str,
        search_collection: str
    ) -> Dict:
        """
        Process a single round of deduplication.

        Args:
            round_num: Current round number
            input_csv_path: Path to input CSV for this round
            search_collection: Qdrant collection to search against

        Returns:
            Dictionary with round results
        """
        logger.info(f"📂 Loading entities from: {input_csv_path}")
        df = pd.read_csv(input_csv_path)

        # Normalize column names (merged_* → standard names)
        # This is critical for Round 2+ where input comes from previous round output
        df = normalize_columns(df)

        entities_start = len(df)

        logger.info(f"   Entities to process: {entities_start}")
        logger.info(f"   Search collection: {search_collection}")

        # Check for existing checkpoint for this round
        checkpoint_entities, last_index = self.checkpoint.load_round_checkpoint(round_num)

        if checkpoint_entities and last_index >= 0:
            logger.info(f"📂 Resuming round {round_num} from index {last_index + 1}")
            merged_entities = checkpoint_entities
            start_idx = last_index + 1
        else:
            merged_entities = []
            start_idx = 0

        # Initialize entity tracker for this round
        tracker_file = self.checkpoint.checkpoints_dir / f"round{round_num}_entity_ids.json"
        entity_tracker = PersistentEntityIDTracker(str(tracker_file), auto_save=True)

        # Track merges for this round
        merges_this_round = {}

        # Process entities sequentially
        merged_entities = []
        
        logger.info(f"\\n🔄 Starting sequential deduplication of entities...")
        
        for idx, row in df.iterrows():
            # Skip if before start index (resuming)
            if idx < start_idx:
                continue
            
            entity_id = row.get('entity_id') or row.get('root_entity_id')
            entity_name = row.get('entity_name', 'Unknown')

            # Skip if already processed
            if entity_tracker.contains(entity_id):
                logger.debug(f"  ⏭️ Skipping already processed: {entity_name}")
                continue

            logger.info(f"\\n🔄 [{idx+1}/{entities_start}] Processing: {entity_name}")

            try:
                # Process entity
                result = await self._process_single_entity(
                    row.to_dict(), idx, entity_tracker, df, search_collection
                )

                # Track merges if any
                if result and result.get('merged_entity_ids'):
                    merges_this_round[result['root_entity_id']] = result['merged_entity_ids']
                    merged_entities.append(result)

                # Always track as processed after successful attempt (even if no merge)
                entity_tracker.add(entity_id)

            except Exception as e:
                logger.error(f"  ❌ Error processing entity {idx}: {e}")
                continue
        
        # Save checkpoint with all results
        self.checkpoint.save_round_checkpoint(
            round_num, merged_entities, entity_tracker.get_all(), len(df) - 1
        )
        self.state.current_round_state['last_processed_index'] = len(df) - 1
        self.state.current_round_state['entities_processed_count'] = len(merged_entities)
        self.checkpoint.save_state(self.state)
        
        logger.info(f"\\n✅ Sequential processing completed: {len(merged_entities)} entities merged")

        # Save round output
        output_file = self.checkpoint.save_round_output(round_num, merged_entities)

        # Save merge history
        self.checkpoint.save_merge_history(round_num, merges_this_round)

        return {
            'entities_start': entities_start,
            'entities_end': len(merged_entities),
            'merges_count': len(merges_this_round),
            'output_file': output_file,
            'merges': merges_this_round
        }

    async def _process_single_entity(
        self,
        row: dict,
        idx: int,
        entity_tracker: PersistentEntityIDTracker,
        df: pd.DataFrame,
        search_collection: str
    ) -> Optional[dict]:
        """
        Process a single entity for deduplication.

        This wraps the existing process_entity_with_backoff and
        passes the collection_name for vector search.
        """
        result = await process_entity_with_backoff(
            row, idx, self.provider, self.model_name,
            self.api_key_manager, entity_tracker,
            self.stats_tracker,
            max_retries=5, base_delay=1.0,
            max_delay=60.0, backoff_multiplier=2.0,
            df=df,
            collection_name=search_collection
        )
        return result

    async def _update_working_collection(self, round_output_path: str, round_num: int) -> None:
        """
        Update the working collection with merged entities from the completed round.

        For Round 1 → Round 2: Create new empty collection and upload Round 1 results
        For Round N → Round N+1: Recreate collection with new round results
        """
        from vectordb_utils import (
            create_collection, upload_merged_entities_to_vectordb, client
        )

        logger.info(f"\n📦 Updating working collection for next round...")
        logger.info(f"   Source: {round_output_path}")
        logger.info(f"   Target: {self.working_collection}")

        if round_num == 1:
            # Create new working collection
            logger.info(f"   Creating new working collection: {self.working_collection}")

            # Check if collection already exists
            collections = await client.get_collections()
            collection_names = [col.name for col in collections.collections]

            if self.working_collection not in collection_names:
                success = await create_collection(self.working_collection)
                if not success:
                    raise RuntimeError(f"Failed to create working collection: {self.working_collection}")

            # Upload Round 1 results (merged entities format)
            await upload_merged_entities_to_vectordb(
                round_output_path,
                collection_name=self.working_collection,
                process_id=self.process_id,
                batch_size=10
            )
        else:
            # For subsequent rounds, recreate the collection with new data
            # This ensures fresh embeddings computed from enriched merged descriptions
            logger.info(f"   Recreating working collection with round {round_num} results")

            # Delete existing collection
            try:
                await client.delete_collection(self.working_collection)
                logger.info(f"   Deleted old working collection")
            except Exception as e:
                logger.warning(f"   Could not delete working collection: {e}")

            # Create fresh and upload
            success = await create_collection(self.working_collection)
            if not success:
                raise RuntimeError(f"Failed to recreate working collection")

            await upload_merged_entities_to_vectordb(
                round_output_path,
                collection_name=self.working_collection,
                process_id=self.process_id,
                batch_size=10
            )

        logger.info(f"   ✅ Working collection updated successfully")

    def _generate_final_output(self) -> str:
        """Generate the final unique entities CSV."""
        # Get the last completed round
        if not self.state.round_history:
            raise RuntimeError("No rounds completed")

        last_round = self.state.round_history[-1]
        last_round_num = last_round['round_number']

        # Load, normalize, and save to final location
        source = self.checkpoint.get_round_output_path(last_round_num)
        final_output = self.output_dir / "unique_entities_final.csv"

        if source.exists():
            # Read the source CSV
            df = pd.read_csv(source)

            # Apply keyword normalization as a safety net
            from keyword_normalization_utils import normalize_merged_keywords_column
            df = normalize_merged_keywords_column(df)

            # Save to final output location
            df.to_csv(final_output, index=False)

            logger.info(f"📄 Final output (normalized): {final_output}")
            return str(final_output)
        else:
            raise FileNotFoundError(f"Last round output not found: {source}")

    def _log_final_summary(self, total_duration: float) -> None:
        """Log final summary of the iterative deduplication process."""
        logger.info("\n" + "="*70)
        logger.info("📊 ITERATIVE DEDUPLICATION SUMMARY")
        logger.info("="*70)

        logger.info(f"Session ID: {self.state.session_id}")
        logger.info(f"Status: {self.state.status}")
        logger.info(f"Total duration: {total_duration:.2f}s ({total_duration/60:.1f} minutes)")
        logger.info(f"Rounds completed: {len(self.state.round_history)}")

        if self.state.round_history:
            initial = self.state.total_initial_entities
            final = self.state.round_history[-1]['entities_end']
            reduction = ((initial - final) / initial * 100) if initial > 0 else 0

            logger.info(f"\nEntity reduction: {initial} → {final} ({reduction:.1f}% reduction)")

            logger.info(f"\nRound-by-round breakdown:")
            logger.info("-" * 60)
            logger.info(f"{'Round':<8} {'Start':<10} {'End':<10} {'Merges':<10} {'Duration':<12}")
            logger.info("-" * 60)

            for round_info in self.state.round_history:
                logger.info(
                    f"{round_info['round_number']:<8} "
                    f"{round_info['entities_start']:<10} "
                    f"{round_info['entities_end']:<10} "
                    f"{round_info['merges_count']:<10} "
                    f"{round_info['duration_seconds']:.1f}s"
                )

            logger.info("-" * 60)
            total_merges = sum(r['merges_count'] for r in self.state.round_history)
            logger.info(f"{'TOTAL':<8} {initial:<10} {final:<10} {total_merges:<10}")

        logger.info("="*70)


async def run_iterative_deduplication(
    input_csv_path: str,
    output_dir: str,
    original_collection: str,
    provider: str,
    model_name: str,
    max_rounds: int = 10,
    stats_tracker: Optional[TokenUsageStats] = None,
    session_id: Optional[str] = None,
    process_id: Optional[str] = None
) -> str:
    """
    Convenience function to run iterative deduplication.

    Args:
        input_csv_path: Path to merged results CSV
        output_dir: Directory for outputs
        original_collection: Name of original Qdrant collection
        provider: LLM provider
        model_name: Model name
        max_rounds: Maximum rounds
        stats_tracker: Optional cost tracker
        session_id: Optional session ID for resuming
        process_id: Process ID for collection naming

    Returns:
        Path to final unique entities CSV
    """
    dedup = IterativeDeduplication(
        input_csv_path=input_csv_path,
        output_dir=output_dir,
        original_collection=original_collection,
        provider=provider,
        model_name=model_name,
        max_rounds=max_rounds,
        stats_tracker=stats_tracker,
        session_id=session_id,
        process_id=process_id
    )

    return await dedup.run()
