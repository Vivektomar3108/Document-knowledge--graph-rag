"""
Diagnostic script to check progress tracker mismatch.
Compares XML files, CSVs, and progress tracker to find discrepancies.
"""
import os
import json
from pathlib import Path
from xml_utils import get_xml_files
from logger import setup_logger

logger = setup_logger(__name__)

def load_progress_file(progress_file: Path) -> set:
    """Load completed documents from progress JSON file."""
    if not progress_file.exists():
        return set()

    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('completed', []))
    except Exception as e:
        logger.error(f"Failed to load {progress_file}: {e}")
        return set()

def check_progress():
    """Check for discrepancies in progress tracking."""

    # Directories
    xml_dir = "xmls"
    results_dir = "results/2025-12-11_13-13-02"
    progress_dir = Path(results_dir) / ".progress"

    logger.info("="*70)
    logger.info("🔍 PROGRESS TRACKER DIAGNOSTIC")
    logger.info("="*70)

    # 1. Get XML files
    logger.info("\n1️⃣ Scanning XML files...")
    xml_files = get_xml_files(xml_dir)
    xml_doc_names = [os.path.splitext(os.path.basename(f))[0] for f in xml_files]
    logger.info(f"   Total XML files: {len(xml_files)}")
    logger.info(f"   Sample names (first 5):")
    for name in xml_doc_names[:5]:
        logger.info(f"      - {repr(name)}")

    # 2. Get CSVs
    logger.info("\n2️⃣ Scanning result CSVs...")
    csv_files = list(Path(results_dir).glob("*_results_raw_gpt-4.1.csv"))
    csv_doc_names = [f.stem.replace("_results_raw_gpt-4.1", "") for f in csv_files]
    logger.info(f"   Total CSV files: {len(csv_files)}")
    logger.info(f"   Sample names (first 5):")
    for name in csv_doc_names[:5]:
        logger.info(f"      - {repr(name)}")

    # 3. Get progress tracker data
    logger.info("\n3️⃣ Loading progress tracker...")
    extraction_completed = load_progress_file(progress_dir / "extraction_progress.json")
    vectordb_completed = load_progress_file(progress_dir / "vectordb_progress.json")

    logger.info(f"   Extraction completed: {len(extraction_completed)} documents")
    logger.info(f"   Vector DB completed: {len(vectordb_completed)} documents")

    if extraction_completed:
        logger.info(f"   Sample extraction names (first 5):")
        for name in list(extraction_completed)[:5]:
            logger.info(f"      - {repr(name)}")

    # 4. Find discrepancies
    logger.info("\n4️⃣ Analyzing discrepancies...")

    # Find CSVs without extraction progress
    csv_set = set(csv_doc_names)
    extraction_set = extraction_completed

    csvs_not_in_extraction = csv_set - extraction_set
    extraction_not_in_csvs = extraction_set - csv_set

    if csvs_not_in_extraction:
        logger.warning(f"   ⚠️  {len(csvs_not_in_extraction)} CSVs exist but NOT marked as extraction completed:")
        for name in sorted(csvs_not_in_extraction)[:10]:
            logger.warning(f"      - {repr(name)}")
        if len(csvs_not_in_extraction) > 10:
            logger.warning(f"      ... and {len(csvs_not_in_extraction) - 10} more")

    if extraction_not_in_csvs:
        logger.warning(f"   ⚠️  {len(extraction_not_in_csvs)} marked as extraction completed but NO CSV found:")
        for name in sorted(extraction_not_in_csvs)[:10]:
            logger.warning(f"      - {repr(name)}")
        if len(extraction_not_in_csvs) > 10:
            logger.warning(f"      ... and {len(extraction_not_in_csvs) - 10} more")

    # 5. Check pending calculation
    logger.info("\n5️⃣ Simulating get_pending_documents()...")
    xml_names_set = set(xml_doc_names)
    pending = xml_names_set - extraction_set

    logger.info(f"   Total XML files: {len(xml_names_set)}")
    logger.info(f"   Extraction completed: {len(extraction_set)}")
    logger.info(f"   Calculated pending: {len(pending)}")
    logger.info(f"   Expected pending: {len(xml_names_set) - len(extraction_set)}")

    # 6. Name normalization check
    logger.info("\n6️⃣ Checking name normalization...")

    # Check if any XML names don't match exactly
    xml_only = xml_names_set - csv_set - extraction_set
    if xml_only:
        logger.info(f"   Found {len(xml_only)} XML files not in CSVs or progress:")
        for name in sorted(xml_only)[:5]:
            logger.info(f"      - {repr(name)}")
            # Look for similar names
            for csv_name in csv_doc_names[:100]:
                if name.lower() == csv_name.lower() and name != csv_name:
                    logger.warning(f"        → Similar CSV name: {repr(csv_name)}")
                    break

    # 7. Summary
    logger.info("\n" + "="*70)
    logger.info("📊 SUMMARY")
    logger.info("="*70)
    logger.info(f"XML files:            {len(xml_files)}")
    logger.info(f"Result CSVs:          {len(csv_files)}")
    logger.info(f"Extraction completed: {len(extraction_completed)}")
    logger.info(f"Vector DB completed:  {len(vectordb_completed)}")
    logger.info(f"Pending (calculated): {len(pending)}")
    logger.info("="*70)

    # 8. Recommendation
    if len(extraction_completed) < len(csv_files):
        logger.warning("\n⚠️  ISSUE DETECTED:")
        logger.warning(f"   {len(csv_files)} CSVs exist but only {len(extraction_completed)} marked as completed")
        logger.warning(f"   This means {len(csv_files) - len(extraction_completed)} documents will be RE-PROCESSED")
        logger.warning("\n💡 RECOMMENDED ACTION:")
        logger.warning("   Sync progress tracker with actual CSVs to avoid reprocessing")

if __name__ == "__main__":
    check_progress()
