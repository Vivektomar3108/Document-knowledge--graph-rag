"""
Sync progress tracker with actual CSV files to avoid reprocessing.
Updates extraction_progress.json to match result CSVs that exist.
"""
import os
import json
from pathlib import Path
from logger import setup_logger

logger = setup_logger(__name__)

def sync_progress(results_dir: str, model_name: str = "gpt-4.1"):
    """
    Sync extraction progress with actual CSV files.

    Args:
        results_dir: Results directory path
        model_name: Model name used for CSVs
    """
    logger.info("="*70)
    logger.info("🔄 SYNCING PROGRESS TRACKER WITH ACTUAL CSVs")
    logger.info("="*70)
    logger.info(f"Results directory: {results_dir}")
    logger.info(f"Model name: {model_name}")
    logger.info("")

    results_path = Path(results_dir)
    progress_dir = results_path / ".progress"
    extraction_file = progress_dir / "extraction_progress.json"
    vectordb_file = progress_dir / "vectordb_progress.json"

    # 1. Get all result CSVs
    logger.info("1️⃣ Scanning result CSVs...")
    csv_pattern = f"*_results_raw_{model_name}.csv"
    csv_files = list(results_path.glob(csv_pattern))
    csv_doc_names = {f.stem.replace(f"_results_raw_{model_name}", "") for f in csv_files}
    logger.info(f"   Found {len(csv_doc_names)} result CSV files")

    # 2. Load current extraction progress
    logger.info("\n2️⃣ Loading current extraction progress...")
    if extraction_file.exists():
        with open(extraction_file, 'r', encoding='utf-8') as f:
            extraction_data = json.load(f)
            extraction_completed = set(extraction_data.get('completed', []))
    else:
        extraction_completed = set()
    logger.info(f"   Currently marked as completed: {len(extraction_completed)}")

    # 3. Load current vectordb progress
    logger.info("\n3️⃣ Loading current vector DB progress...")
    if vectordb_file.exists():
        with open(vectordb_file, 'r', encoding='utf-8') as f:
            vectordb_data = json.load(f)
            vectordb_completed = set(vectordb_data.get('completed', []))
    else:
        vectordb_completed = set()
    logger.info(f"   Currently marked as completed: {len(vectordb_completed)}")

    # 4. Find missing documents
    logger.info("\n4️⃣ Analyzing gaps...")

    # Documents with CSVs but not in extraction_completed
    missing_from_extraction = csv_doc_names - extraction_completed

    # Documents in extraction_completed but no CSV (orphaned entries)
    orphaned_in_extraction = extraction_completed - csv_doc_names

    if missing_from_extraction:
        logger.warning(f"   ⚠️  {len(missing_from_extraction)} CSVs exist but NOT in extraction_completed:")
        for name in sorted(missing_from_extraction)[:10]:
            logger.warning(f"      - {name}")
        if len(missing_from_extraction) > 10:
            logger.warning(f"      ... and {len(missing_from_extraction) - 10} more")
    else:
        logger.info(f"   ✅ All CSVs are in extraction_completed")

    if orphaned_in_extraction:
        logger.warning(f"   ⚠️  {len(orphaned_in_extraction)} in extraction_completed but NO CSV:")
        for name in sorted(orphaned_in_extraction)[:10]:
            logger.warning(f"      - {name}")
        if len(orphaned_in_extraction) > 10:
            logger.warning(f"      ... and {len(orphaned_in_extraction) - 10} more")

    # 5. Sync extraction_completed with CSVs
    if missing_from_extraction or orphaned_in_extraction:
        logger.info("\n5️⃣ Syncing extraction_completed with CSVs...")

        # Set extraction_completed to match CSV files
        new_extraction_completed = csv_doc_names.copy()

        logger.info(f"   Old extraction_completed: {len(extraction_completed)}")
        logger.info(f"   New extraction_completed: {len(new_extraction_completed)}")

        # Ask for confirmation
        print(f"\n⚠️  This will update extraction_progress.json:")
        print(f"   - Add {len(missing_from_extraction)} documents")
        if orphaned_in_extraction:
            print(f"   - Remove {len(orphaned_in_extraction)} orphaned entries")

        confirm = input("\nProceed with sync? (yes/no): ").strip().lower()

        if confirm != "yes":
            logger.info("❌ Sync cancelled by user")
            return

        # Save updated progress
        from datetime import datetime
        new_data = {
            'completed': sorted(list(new_extraction_completed)),
            'total_count': len(new_extraction_completed),
            'last_updated': datetime.now().isoformat()
        }

        # Backup old file
        if extraction_file.exists():
            backup_file = extraction_file.with_suffix('.json.backup')
            import shutil
            shutil.copy2(extraction_file, backup_file)
            logger.info(f"   📁 Backed up to: {backup_file}")

        # Write new file
        with open(extraction_file, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)

        logger.info(f"   ✅ Updated extraction_progress.json")
        logger.info(f"   New extraction_completed count: {len(new_extraction_completed)}")
    else:
        logger.info("\n✅ extraction_completed is already in sync with CSVs!")

    # 6. Also sync vectordb_completed
    logger.info("\n6️⃣ Checking vector DB progress...")

    missing_from_vectordb = csv_doc_names - vectordb_completed

    if missing_from_vectordb:
        logger.warning(f"   ⚠️  {len(missing_from_vectordb)} CSVs NOT in vectordb_completed:")
        logger.warning(f"   These documents need re-upload to Qdrant")
        for name in sorted(missing_from_vectordb)[:10]:
            logger.warning(f"      - {name}")
        if len(missing_from_vectordb) > 10:
            logger.warning(f"      ... and {len(missing_from_vectordb) - 10} more")
    else:
        logger.info(f"   ✅ All CSVs are marked as uploaded to vector DB")

    # 7. Summary
    logger.info("\n" + "="*70)
    logger.info("📊 FINAL STATE")
    logger.info("="*70)
    logger.info(f"Result CSVs:          {len(csv_doc_names)}")
    logger.info(f"Extraction completed: {len(csv_doc_names)}")  # Now synced
    logger.info(f"Vector DB completed:  {len(vectordb_completed)}")
    logger.info("="*70)

    if missing_from_vectordb:
        logger.info(f"\n⚠️  Note: {len(missing_from_vectordb)} documents still need Qdrant upload")
        logger.info(f"   Run: python reupload_missing_from_qdrant.py")

    logger.info("\n✅ Progress tracker sync completed!")

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        results_dir = sys.argv[1]
    else:
        results_dir = "results/2025-12-11_13-13-02"

    model_name = input("Enter model name (default: gpt-4.1): ").strip() or "gpt-4.1"

    sync_progress(results_dir, model_name)
