"""
Identify and re-upload documents that failed vector DB upload.
Compares progress tracker with actual result CSVs to find gaps.
"""
import asyncio
import os
import json
from pathlib import Path
from vectordb_utils import upload_results_csv_to_vectordb
from logger import setup_logger

logger = setup_logger(__name__)


def load_progress_file(progress_file: str) -> set:
    """Load completed documents from progress JSON file."""
    if not os.path.exists(progress_file):
        return set()

    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('completed', []))
    except Exception as e:
        logger.error(f"Failed to load progress file: {e}")
        return set()


def get_all_result_csvs(results_dir: str, model_name: str) -> dict:
    """
    Get all result CSV files and extract document names.

    Returns:
        dict: {document_name: csv_file_path}
    """
    results_path = Path(results_dir)
    result_csvs = {}

    pattern = f"*_results_raw_{model_name}.csv"
    for csv_file in results_path.glob(pattern):
        # Extract document name from filename
        # Format: DocumentName_results_raw_gpt-4.1.csv
        doc_name = csv_file.stem.replace(f"_results_raw_{model_name}", "")
        result_csvs[doc_name] = str(csv_file)

    return result_csvs


def identify_failed_uploads(results_dir: str, model_name: str = "gpt-4.1") -> list:
    """
    Identify documents that have result CSVs but failed vector DB upload.

    Returns:
        list: [(document_name, csv_path), ...]
    """
    logger.info("="*60)
    logger.info("🔍 Identifying Failed Vector DB Uploads")
    logger.info("="*60)

    # Load progress tracker data
    progress_dir = Path(results_dir) / ".progress"
    extraction_file = progress_dir / "extraction_progress.json"
    vectordb_file = progress_dir / "vectordb_progress.json"

    extraction_completed = load_progress_file(str(extraction_file))
    vectordb_completed = load_progress_file(str(vectordb_file))

    logger.info(f"📊 Extraction completed: {len(extraction_completed)} documents")
    logger.info(f"📊 Vector DB uploaded: {len(vectordb_completed)} documents")

    # Get all result CSVs
    all_csvs = get_all_result_csvs(results_dir, model_name)
    logger.info(f"📊 Total result CSVs: {len(all_csvs)} files")

    # Find documents with CSVs but not uploaded to vector DB
    failed_uploads = []

    for doc_name, csv_path in all_csvs.items():
        if doc_name not in vectordb_completed:
            failed_uploads.append((doc_name, csv_path))

    logger.info(f"\n📋 Found {len(failed_uploads)} documents needing re-upload:")

    if failed_uploads:
        for i, (doc_name, csv_path) in enumerate(failed_uploads[:10], 1):
            logger.info(f"   {i}. {doc_name}")

        if len(failed_uploads) > 10:
            logger.info(f"   ... and {len(failed_uploads) - 10} more")

    logger.info("="*60)

    return failed_uploads


async def reupload_documents(
    failed_uploads: list,
    results_dir: str,
    batch_delay: int = 5
):
    """
    Re-upload failed documents to vector DB.

    Args:
        failed_uploads: List of (document_name, csv_path) tuples
        results_dir: Results directory path
        batch_delay: Delay between uploads in seconds
    """
    if not failed_uploads:
        logger.info("✅ No documents need re-upload")
        return

    logger.info("="*60)
    logger.info(f"🔄 Re-uploading {len(failed_uploads)} Documents")
    logger.info("="*60)

    # Load progress tracker to mark uploads
    from progress_tracker import ProgressTracker
    progress_tracker = ProgressTracker(results_dir)

    successful = 0
    failed = 0

    for i, (doc_name, csv_path) in enumerate(failed_uploads, 1):
        logger.info(f"\n[{i}/{len(failed_uploads)}] Uploading: {doc_name}")
        logger.info(f"   CSV: {csv_path}")

        try:
            # Upload to vector DB
            await upload_results_csv_to_vectordb(csv_path, doc_name)

            # Mark as completed
            progress_tracker.mark_vectordb_completed(doc_name)

            logger.info(f"   ✅ Successfully uploaded {doc_name}")
            successful += 1

            # Delay between uploads to avoid overwhelming the server
            if i < len(failed_uploads):
                logger.info(f"   ⏳ Waiting {batch_delay}s before next upload...")
                await asyncio.sleep(batch_delay)

        except Exception as e:
            logger.error(f"   ❌ Failed to upload {doc_name}: {e}")
            failed += 1

    logger.info("\n" + "="*60)
    logger.info("📊 Re-upload Summary")
    logger.info("="*60)
    logger.info(f"   ✅ Successful: {successful}")
    logger.info(f"   ❌ Failed: {failed}")
    logger.info(f"   📊 Total: {len(failed_uploads)}")
    logger.info("="*60)


async def main():
    """Main function."""
    import sys

    # Get results directory
    if len(sys.argv) > 1:
        results_dir = sys.argv[1]
    else:
        # Find most recent results directory
        results_base = "results"
        if os.path.exists(results_base):
            runs = sorted([d for d in os.listdir(results_base) if os.path.isdir(os.path.join(results_base, d))], reverse=True)
            if runs:
                results_dir = os.path.join(results_base, runs[0])
            else:
                logger.error("No results directories found")
                return
        else:
            logger.error("Results directory not found")
            return

    logger.info(f"📂 Using results directory: {results_dir}")

    # Get model name
    model_name = input("Enter model name (default: gpt-4.1): ").strip() or "gpt-4.1"

    # Identify failed uploads
    failed_uploads = identify_failed_uploads(results_dir, model_name)

    if not failed_uploads:
        logger.info("\n✅ All documents have been uploaded to vector DB!")
        return

    # Confirm re-upload
    print(f"\n⚠️  Found {len(failed_uploads)} documents that need re-upload")
    confirm = input("Proceed with re-upload? (yes/no): ").strip().lower()

    if confirm != "yes":
        logger.info("Re-upload cancelled by user")
        return

    # Perform re-upload
    await reupload_documents(failed_uploads, results_dir, batch_delay=5)


if __name__ == "__main__":
    asyncio.run(main())
