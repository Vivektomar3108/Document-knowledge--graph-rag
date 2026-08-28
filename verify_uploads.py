"""
Verify actual uploads by checking Qdrant collection point count
and comparing with document CSVs.
"""
import asyncio
import os
import json
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.async_qdrant_client import AsyncQdrantClient
from dotenv import load_dotenv
from logger import setup_logger

logger = setup_logger(__name__)

load_dotenv(override=True)

# Use NEW Qdrant instance (after migration)
NEW_QDRANT_URL = os.getenv("NEW_QDRANT_URL")
NEW_QDRANT_API_KEY = os.getenv("NEW_QDRANT_API_KEY")

# Fall back to old Qdrant if NEW not configured
if NEW_QDRANT_URL:
    QDRANT_URL = NEW_QDRANT_URL
    QDRANT_API_KEY = NEW_QDRANT_API_KEY if NEW_QDRANT_API_KEY else None
    logger.info("🔗 Using NEW Qdrant instance")
else:
    QDRANT_URL = "https://af88b374-00e7-4a46-ac96-17bebe98ff08.eu-central-1-0.aws.cloud.qdrant.io:6333"
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    logger.warning("⚠️  Using OLD Qdrant instance (NEW_QDRANT_URL not set)")

COLLECTION_NAME = "full_xml_collection_11th_dec"


async def get_uploaded_documents_from_qdrant():
    """
    Query Qdrant to get list of unique source documents actually uploaded.
    """
    logger.info("Connecting to Qdrant...")
    client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60)

    try:
        # Get collection info
        collection_info = await client.get_collection(COLLECTION_NAME)
        total_points = collection_info.points_count
        logger.info(f"Total points in Qdrant: {total_points}")

        # Scroll through all points to get unique source_document values
        logger.info("Fetching all points to identify source documents...")

        source_documents = set()
        offset = None
        batch_num = 0

        while True:
            batch_num += 1
            logger.info(f"Fetching batch {batch_num}...")

            # Scroll with payload only (no vectors needed)
            scroll_result = await client.scroll(
                collection_name=COLLECTION_NAME,
                limit=1000,  # Larger batches for metadata only
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

            logger.info(f"  Found {len(points)} points, unique docs so far: {len(source_documents)}")

            offset = next_offset
            if offset is None:
                break

        logger.info(f"\n✅ Total unique documents in Qdrant: {len(source_documents)}")
        return source_documents

    except Exception as e:
        logger.error(f"Failed to query Qdrant: {e}")
        return set()
    finally:
        await client.close()


def get_local_documents(results_dir: str, model_name: str = "gpt-4.1"):
    """Get all documents that have result CSVs locally."""
    results_path = Path(results_dir)
    local_docs = set()

    pattern = f"*_results_raw_{model_name}.csv"
    for csv_file in results_path.glob(pattern):
        # Extract document name from filename
        doc_name = csv_file.stem.replace(f"_results_raw_{model_name}", "")
        local_docs.add(doc_name)

    return local_docs


async def main():
    """Main verification function."""
    import sys

    # Get results directory
    if len(sys.argv) > 1:
        results_dir = sys.argv[1]
    else:
        # Try different possible locations
        possible_paths = [
            "results",
            "/home/ubuntu/borges knowledge graph/results"
        ]

        results_dir = None
        for base_path in possible_paths:
            if os.path.exists(base_path):
                runs = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))], reverse=True)
                if runs:
                    results_dir = os.path.join(base_path, runs[0])
                    break

        if not results_dir:
            logger.error("No results directories found")
            logger.error("Please specify path: python verify_uploads.py 'results/2025-12-11_13-13-02'")
            return

    logger.info("="*60)
    logger.info("🔍 Verifying Actual Uploads")
    logger.info("="*60)
    logger.info(f"Results directory: {results_dir}")
    logger.info(f"Qdrant URL: {QDRANT_URL}")
    logger.info(f"Collection: {COLLECTION_NAME}")
    logger.info("")

    # Get local documents
    logger.info("📂 Scanning local CSVs...")
    local_docs = get_local_documents(results_dir)
    logger.info(f"   Found {len(local_docs)} documents with CSVs locally")

    # Get documents actually in Qdrant
    logger.info("\n📊 Querying Qdrant for uploaded documents...")
    qdrant_docs = await get_uploaded_documents_from_qdrant()

    # Compare
    logger.info("\n" + "="*60)
    logger.info("📊 Comparison Results")
    logger.info("="*60)
    logger.info(f"Local documents (CSVs):     {len(local_docs)}")
    logger.info(f"Qdrant documents (uploaded): {len(qdrant_docs)}")

    # Find missing documents
    missing_docs = local_docs - qdrant_docs

    if missing_docs:
        logger.warning(f"\n⚠️  {len(missing_docs)} documents NOT in Qdrant!")
        logger.info("\nMissing documents (first 20):")
        for i, doc in enumerate(sorted(list(missing_docs))[:20], 1):
            logger.info(f"   {i}. {doc}")

        if len(missing_docs) > 20:
            logger.info(f"   ... and {len(missing_docs) - 20} more")

        # Save to file
        missing_file = Path(results_dir) / "missing_from_qdrant.txt"
        with open(missing_file, 'w', encoding='utf-8') as f:
            for doc in sorted(missing_docs):
                f.write(f"{doc}\n")
        logger.info(f"\n💾 Full list saved to: {missing_file}")

    else:
        logger.info("\n✅ All local documents are in Qdrant!")

    # Find extra documents in Qdrant (shouldn't happen, but check)
    extra_docs = qdrant_docs - local_docs
    if extra_docs:
        logger.info(f"\n📝 Note: {len(extra_docs)} documents in Qdrant but no local CSV")
        logger.info("   (These may be from previous runs)")

    logger.info("\n" + "="*60)


if __name__ == "__main__":
    asyncio.run(main())
