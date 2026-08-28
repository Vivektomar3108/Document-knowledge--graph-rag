"""
Re-upload documents that are actually missing from Qdrant.
Uses actual Qdrant query (like verify_uploads.py) instead of progress tracker.
"""
import asyncio
import os
from pathlib import Path
from qdrant_client.async_qdrant_client import AsyncQdrantClient
from dotenv import load_dotenv
from vectordb_utils import upload_results_csv_to_vectordb
from logger import setup_logger

logger = setup_logger(__name__)

load_dotenv(override=True)

# Use NEW Qdrant instance
NEW_QDRANT_URL = os.getenv("NEW_QDRANT_URL")
NEW_QDRANT_API_KEY = os.getenv("NEW_QDRANT_API_KEY")
COLLECTION_NAME = "full_xml_collection_11th_dec"


async def get_uploaded_documents_from_qdrant():
    """
    Query NEW Qdrant to get list of unique source documents actually uploaded.
    """
    logger.info("🔗 Connecting to NEW Qdrant instance...")
    logger.info(f"   URL: {NEW_QDRANT_URL}")

    client = AsyncQdrantClient(
        url=NEW_QDRANT_URL,
        api_key=NEW_QDRANT_API_KEY if NEW_QDRANT_API_KEY else None,
        timeout=60
    )

    try:
        # Get collection info
        collection_info = await client.get_collection(COLLECTION_NAME)
        total_points = collection_info.points_count
        logger.info(f"📊 Total points in Qdrant: {total_points}")

        # Scroll through all points to get unique source_document values
        logger.info("🔍 Fetching all points to identify source documents...")

        source_documents = set()
        offset = None
        batch_num = 0

        while True:
            batch_num += 1
            logger.info(f"   Fetching batch {batch_num}...")

            # Scroll with payload only (no vectors needed)
            scroll_result = await client.scroll(
                collection_name=COLLECTION_NAME,
                limit=1000,
                offset=offset,
                with_vectors=False,
                with_payload=True
            )

            points, next_offset = scroll_result

            if not points:
                break

            # Extract source_document from each point
            for point in points:
                if point.payload and 'source_document' in point.payload:
                    source_documents.add(point.payload['source_document'])

            logger.info(f"   Found {len(points)} points, unique docs so far: {len(source_documents)}")

            offset = next_offset
            if offset is None:
                break

        logger.info(f"\n✅ Total unique documents in NEW Qdrant: {len(source_documents)}")
        return source_documents

    except Exception as e:
        logger.error(f"❌ Failed to query Qdrant: {e}")
        return set()
    finally:
        await client.close()


def get_local_documents(results_dir: str, model_name: str = "gpt-4.1"):
    """Get all documents that have result CSVs locally."""
    results_path = Path(results_dir)
    local_docs = {}  # {doc_name: csv_path}

    pattern = f"*_results_raw_{model_name}.csv"
    for csv_file in results_path.glob(pattern):
        # Extract document name from filename
        doc_name = csv_file.stem.replace(f"_results_raw_{model_name}", "")
        local_docs[doc_name] = str(csv_file)

    return local_docs


async def reupload_missing_documents(
    missing_docs: list,
    results_dir: str,
    batch_delay: int = 5
):
    """
    Re-upload documents that are actually missing from Qdrant.

    Args:
        missing_docs: List of (document_name, csv_path) tuples
        results_dir: Results directory path
        batch_delay: Delay between uploads in seconds
    """
    if not missing_docs:
        logger.info("✅ No documents need re-upload")
        return

    logger.info("="*60)
    logger.info(f"🔄 Re-uploading {len(missing_docs)} Documents to NEW Qdrant")
    logger.info("="*60)

    # Load progress tracker to mark uploads
    from progress_tracker import ProgressTracker
    progress_tracker = ProgressTracker(results_dir)

    successful = 0
    failed = 0
    failed_list = []

    for i, (doc_name, csv_path) in enumerate(missing_docs, 1):
        logger.info(f"\n[{i}/{len(missing_docs)}] Uploading: {doc_name}")
        logger.info(f"   CSV: {csv_path}")

        try:
            # Upload to vector DB (will use NEW_QDRANT_URL from vectordb_utils)
            await upload_results_csv_to_vectordb(csv_path, doc_name)

            # Mark as completed in progress tracker
            progress_tracker.mark_vectordb_completed(doc_name)

            logger.info(f"   ✅ Successfully uploaded {doc_name}")
            successful += 1

            # Delay between uploads to avoid overwhelming the server
            if i < len(missing_docs):
                logger.info(f"   ⏳ Waiting {batch_delay}s before next upload...")
                await asyncio.sleep(batch_delay)

        except Exception as e:
            logger.error(f"   ❌ Failed to upload {doc_name}: {e}")
            failed += 1
            failed_list.append(doc_name)

    logger.info("\n" + "="*60)
    logger.info("📊 Re-upload Summary")
    logger.info("="*60)
    logger.info(f"   ✅ Successful: {successful}")
    logger.info(f"   ❌ Failed: {failed}")
    logger.info(f"   📊 Total: {len(missing_docs)}")

    if failed_list:
        logger.info(f"\n⚠️  Failed documents:")
        for doc in failed_list:
            logger.info(f"      - {doc}")

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

    logger.info("="*60)
    logger.info("🔍 Finding Documents Missing from NEW Qdrant")
    logger.info("="*60)
    logger.info(f"📂 Results directory: {results_dir}")
    logger.info(f"🔗 NEW Qdrant URL: {NEW_QDRANT_URL}")
    logger.info("")

    # Get model name
    model_name = input("Enter model name (default: gpt-4.1): ").strip() or "gpt-4.1"

    # Get local documents with CSVs
    logger.info("\n📂 Scanning local CSVs...")
    local_docs = get_local_documents(results_dir, model_name)
    logger.info(f"   Found {len(local_docs)} documents with CSVs locally")

    # Get documents actually in NEW Qdrant
    logger.info("\n📊 Querying NEW Qdrant for uploaded documents...")
    qdrant_docs = await get_uploaded_documents_from_qdrant()

    # Find missing documents
    missing_doc_names = set(local_docs.keys()) - qdrant_docs
    missing_docs = [(doc_name, local_docs[doc_name]) for doc_name in missing_doc_names]

    logger.info("\n" + "="*60)
    logger.info("📊 Comparison Results")
    logger.info("="*60)
    logger.info(f"Local documents (CSVs):      {len(local_docs)}")
    logger.info(f"Qdrant documents (uploaded): {len(qdrant_docs)}")
    logger.info(f"Missing from Qdrant:         {len(missing_docs)}")

    if missing_docs:
        logger.info(f"\n⚠️  Found {len(missing_docs)} documents NOT in NEW Qdrant!")
        logger.info("\nMissing documents (first 20):")
        for i, (doc_name, _) in enumerate(sorted(missing_docs)[:20], 1):
            logger.info(f"   {i}. {doc_name}")

        if len(missing_docs) > 20:
            logger.info(f"   ... and {len(missing_docs) - 20} more")

        # Save to file
        missing_file = "missing_from_new_qdrant.txt"
        with open(missing_file, 'w', encoding='utf-8') as f:
            for doc_name, _ in sorted(missing_docs):
                f.write(f"{doc_name}\n")
        logger.info(f"\n💾 Full list saved to: {missing_file}")

        # Confirm re-upload
        print(f"\n⚠️  Found {len(missing_docs)} documents that need re-upload to NEW Qdrant")
        confirm = input("Proceed with re-upload? (yes/no): ").strip().lower()

        if confirm != "yes":
            logger.info("Re-upload cancelled by user")
            return

        # Perform re-upload
        await reupload_missing_documents(missing_docs, results_dir, batch_delay=5)

    else:
        logger.info("\n✅ All local documents are in NEW Qdrant!")

    logger.info("\n" + "="*60)


if __name__ == "__main__":
    asyncio.run(main())
