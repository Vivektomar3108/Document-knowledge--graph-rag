"""
Progress tracking utility for the Borges Knowledge Graph pipeline.
Ensures documents are not reprocessed after failures or restarts.
"""
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from logger import setup_logger

logger = setup_logger(__name__)


def normalize_document_name(name: str) -> str:
    """
    Normalize document name for comparison.
    Replaces spaces with underscores for consistent matching.

    Args:
        name: Document name

    Returns:
        Normalized name with underscores instead of spaces
    """
    return name.replace(' ', '_')


class ProgressTracker:
    """
    Tracks processing progress at document level to prevent reprocessing.
    Maintains state files for each stage of the pipeline.
    """

    def __init__(self, output_dir: str, run_id: Optional[str] = None, model_name: str = "gpt-4.1"):
        """
        Initialize progress tracker.

        Args:
            output_dir: Base output directory for the current run
            run_id: Optional run identifier (defaults to output directory name)
            model_name: Model name used for CSV files (for auto-sync)
        """
        self.output_dir = Path(output_dir)
        self.run_id = run_id or self.output_dir.name
        self.model_name = model_name

        # Create progress tracking directory
        self.progress_dir = self.output_dir / ".progress"
        self.progress_dir.mkdir(parents=True, exist_ok=True)

        # Progress files for each stage
        self.extraction_progress_file = self.progress_dir / "extraction_progress.json"
        self.vectordb_progress_file = self.progress_dir / "vectordb_progress.json"
        self.merging_progress_file = self.progress_dir / "merging_progress.json"

        # Load existing progress
        self.extraction_completed: Set[str] = self._load_progress(self.extraction_progress_file)
        self.vectordb_completed: Set[str] = self._load_progress(self.vectordb_progress_file)
        self.merging_completed: bool = self._load_merging_status()

        # Auto-sync with actual CSV files on initialization
        self._sync_with_csvs()

        logger.info(f"📊 Progress Tracker initialized for run: {self.run_id}")
        logger.info(f"   Extraction completed: {len(self.extraction_completed)} documents")
        logger.info(f"   Vector DB uploads: {len(self.vectordb_completed)} documents")
        logger.info(f"   Entity merging: {'✅ Completed' if self.merging_completed else '⏳ Pending'}")

    def _load_progress(self, progress_file: Path) -> Set[str]:
        """Load progress from JSON file and normalize all names."""
        if progress_file.exists():
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    completed = data.get('completed', [])
                    # Normalize all names to use underscores for consistent comparison
                    normalized = {normalize_document_name(name) for name in completed}
                    return normalized
            except Exception as e:
                logger.error(f"Failed to load progress from {progress_file}: {e}")
                return set()
        return set()

    def _save_progress(self, progress_file: Path, completed: Set[str]):
        """Save progress to JSON file."""
        try:
            data = {
                'completed': sorted(list(completed)),
                'last_updated': datetime.now().isoformat(),
                'total_count': len(completed)
            }
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Progress saved to {progress_file}")
        except Exception as e:
            logger.error(f"Failed to save progress to {progress_file}: {e}")

    def _load_merging_status(self) -> bool:
        """Load entity merging completion status."""
        if self.merging_progress_file.exists():
            try:
                with open(self.merging_progress_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('completed', False)
            except Exception as e:
                logger.error(f"Failed to load merging status: {e}")
                return False
        return False

    def _save_merging_status(self, completed: bool):
        """Save entity merging completion status."""
        try:
            data = {
                'completed': completed,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.merging_progress_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Merging status saved: {completed}")
        except Exception as e:
            logger.error(f"Failed to save merging status: {e}")

    def _sync_with_csvs(self):
        """
        Sync extraction_completed with actual result CSV files.
        This ensures progress tracker is accurate even if files were added manually.
        Normalizes all names to use underscores for consistent comparison.
        """
        try:
            # Find all result CSV files
            csv_pattern = f"*_results_raw_{self.model_name}.csv"
            csv_files = list(self.output_dir.glob(csv_pattern))

            if not csv_files:
                logger.debug("No result CSVs found, skipping auto-sync")
                return

            # Extract and normalize document names from CSV files
            csv_doc_names = set()
            for csv_file in csv_files:
                doc_name = csv_file.stem.replace(f"_results_raw_{self.model_name}", "")
                # Normalize to underscores for consistent comparison
                normalized_name = normalize_document_name(doc_name)
                csv_doc_names.add(normalized_name)

            # Find documents with CSVs but not in extraction_completed
            missing_from_progress = csv_doc_names - self.extraction_completed

            if missing_from_progress:
                logger.warning(f"⚠️  Found {len(missing_from_progress)} CSVs not in extraction_progress.json")
                logger.warning(f"   Auto-syncing progress tracker with actual CSVs...")

                # Add missing documents to extraction_completed
                self.extraction_completed.update(missing_from_progress)
                self._save_progress(self.extraction_progress_file, self.extraction_completed)

                logger.info(f"✅ Synced {len(missing_from_progress)} documents to extraction_progress.json")
            else:
                logger.debug("✅ extraction_progress.json is in sync with CSVs")

        except Exception as e:
            logger.error(f"Failed to sync with CSVs: {e}")

    def is_extraction_completed(self, document_name: str) -> bool:
        """Check if entity extraction is completed for a document."""
        # Normalize before checking
        normalized_name = normalize_document_name(document_name)
        return normalized_name in self.extraction_completed

    def mark_extraction_completed(self, document_name: str):
        """Mark entity extraction as completed for a document."""
        # Normalize before storing
        normalized_name = normalize_document_name(document_name)
        self.extraction_completed.add(normalized_name)
        self._save_progress(self.extraction_progress_file, self.extraction_completed)
        logger.info(f"✅ Marked extraction completed for: {normalized_name}")

    def is_vectordb_completed(self, document_name: str) -> bool:
        """Check if vector DB upload is completed for a document."""
        # Normalize before checking
        normalized_name = normalize_document_name(document_name)
        return normalized_name in self.vectordb_completed

    def mark_vectordb_completed(self, document_name: str):
        """Mark vector DB upload as completed for a document."""
        # Normalize before storing
        normalized_name = normalize_document_name(document_name)
        self.vectordb_completed.add(normalized_name)
        self._save_progress(self.vectordb_progress_file, self.vectordb_completed)
        logger.info(f"✅ Marked vector DB upload completed for: {normalized_name}")

    def is_merging_completed(self) -> bool:
        """Check if entity merging is completed."""
        return self.merging_completed

    def mark_merging_completed(self):
        """Mark entity merging as completed."""
        self.merging_completed = True
        self._save_merging_status(True)
        logger.info("✅ Marked entity merging as completed")

    def get_pending_documents(self, all_documents: List[str]) -> List[str]:
        """
        Get list of documents that haven't completed extraction yet.
        Normalizes all names to handle space vs underscore differences.

        Args:
            all_documents: List of all document paths or names

        Returns:
            List of document names that need processing
        """
        # Extract just the document names (without paths)
        doc_names = [os.path.splitext(os.path.basename(doc))[0] for doc in all_documents]

        # Normalize all document names to underscores for comparison
        normalized_doc_names = [normalize_document_name(name) for name in doc_names]

        # Filter out completed documents - compare normalized names
        pending = []
        for original_name, normalized_name in zip(doc_names, normalized_doc_names):
            if normalized_name not in self.extraction_completed:
                pending.append(original_name)  # Return original name, not normalized

        if pending:
            logger.info(f"📋 Found {len(pending)} pending documents out of {len(doc_names)} total")
            logger.info(f"   (Extraction completed set has {len(self.extraction_completed)} documents)")
        else:
            logger.info(f"✅ All {len(doc_names)} documents have been processed")

        return pending

    def get_summary(self) -> Dict[str, any]:
        """Get summary of current progress."""
        return {
            'run_id': self.run_id,
            'extraction_completed': len(self.extraction_completed),
            'vectordb_completed': len(self.vectordb_completed),
            'merging_completed': self.merging_completed,
            'extraction_pending': list(self.extraction_completed),
            'vectordb_pending': list(self.vectordb_completed)
        }

    def reset_progress(self):
        """Reset all progress (use with caution!)."""
        logger.warning("⚠️  Resetting all progress tracking...")
        self.extraction_completed.clear()
        self.vectordb_completed.clear()
        self.merging_completed = False

        self._save_progress(self.extraction_progress_file, self.extraction_completed)
        self._save_progress(self.vectordb_progress_file, self.vectordb_completed)
        self._save_merging_status(False)

        logger.info("✅ Progress reset completed")


class DiskSpaceMonitor:
    """Monitor disk space and provide warnings."""

    def __init__(self, threshold_percent: float = 95.0):
        """
        Initialize disk space monitor.

        Args:
            threshold_percent: Threshold percentage for warnings (default: 95%)
        """
        self.threshold_percent = threshold_percent
        self.logger = setup_logger(__name__)

    def check_disk_space(self, path: str = ".") -> Dict[str, any]:
        """
        Check disk space for the given path.

        Args:
            path: Path to check (defaults to current directory)

        Returns:
            Dictionary with disk space information
        """
        try:
            stat = shutil.disk_usage(path)

            total_gb = stat.total / (1024 ** 3)
            used_gb = stat.used / (1024 ** 3)
            free_gb = stat.free / (1024 ** 3)
            used_percent = (stat.used / stat.total) * 100

            info = {
                'total_gb': round(total_gb, 2),
                'used_gb': round(used_gb, 2),
                'free_gb': round(free_gb, 2),
                'used_percent': round(used_percent, 2),
                'is_critical': used_percent >= self.threshold_percent
            }

            return info
        except Exception as e:
            self.logger.error(f"Failed to check disk space: {e}")
            return None

    def log_disk_space(self, path: str = "."):
        """Log current disk space status."""
        info = self.check_disk_space(path)

        if info:
            status_emoji = "🔴" if info['is_critical'] else "🟡" if info['used_percent'] > 80 else "🟢"
            self.logger.info(f"{status_emoji} Disk Space: {info['used_gb']}/{info['total_gb']} GB "
                           f"({info['used_percent']}% used, {info['free_gb']} GB free)")

            if info['is_critical']:
                self.logger.error(f"⚠️  CRITICAL: Disk space is at {info['used_percent']}%! "
                                f"Only {info['free_gb']} GB remaining. Consider cleaning up or expanding disk.")
            elif info['used_percent'] > 80:
                self.logger.warning(f"⚠️  WARNING: Disk space is at {info['used_percent']}%. "
                                  f"Monitor closely during processing.")

    def ensure_minimum_space(self, min_gb: float = 1.0, path: str = ".") -> bool:
        """
        Ensure minimum disk space is available.

        Args:
            min_gb: Minimum required space in GB
            path: Path to check

        Returns:
            True if enough space, False otherwise
        """
        info = self.check_disk_space(path)

        if info and info['free_gb'] < min_gb:
            self.logger.error(f"❌ Insufficient disk space: {info['free_gb']} GB available, "
                            f"but {min_gb} GB required")
            return False

        return True
