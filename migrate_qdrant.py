"""
Migrate data from old Qdrant cluster to new cluster.
Handles collection migration and verification.
"""
import asyncio
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.async_qdrant_client import AsyncQdrantClient
from qdrant_client import models
import json
from logger import setup_logger

logger = setup_logger(__name__)

load_dotenv(override=True)

# Configuration
OLD_QDRANT_URL = "https://af88b374-00e7-4a46-ac96-17bebe98ff08.eu-central-1-0.aws.cloud.qdrant.io:6333"
OLD_QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# NEW cluster configuration
NEW_QDRANT_URL = os.getenv("NEW_QDRANT_URL", "http://107.22.168.201:6333")
NEW_QDRANT_API_KEY = os.getenv("NEW_QDRANT_API_KEY", "")

OLD_COLLECTION = "full_xml_collection_11th_dec"
NEW_COLLECTION = "full_xml_collection_11th_dec"  # Can rename if needed


async def get_collection_info(client: AsyncQdrantClient, collection_name: str):
    """Get information about a collection."""
    try:
        info = await client.get_collection(collection_name)
        return info
    except Exception as e:
        logger.error(f"Failed to get collection info: {e}")
        return None


async def create_target_collection(client: AsyncQdrantClient, collection_name: str):
    """Create collection in new Qdrant with same schema."""
    try:
        logger.info(f"Creating collection '{collection_name}' in new Qdrant...")
        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "paraphrase-multilingual-mpnet-base-v2": models.VectorParams(
                    size=768,
                    on_disk=True,
                    distance=models.Distance.COSINE
                ),
                "colbertv2.0": models.VectorParams(
                    size=128,
                    on_disk=True,
                    distance=models.Distance.COSINE,
                    multivector_config=models.MultiVectorConfig(
                        comparator=models.MultiVectorComparator.MAX_SIM
                    )
                )
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
            strict_mode_config=models.StrictModeConfig(enabled=False)
        )
        logger.info(f"✅ Successfully created collection '{collection_name}'")
        return True
    except Exception as e:
        logger.error(f"Failed to create collection: {e}")
        return False


async def migrate_collection(
    old_client: AsyncQdrantClient,
    new_client: AsyncQdrantClient,
    old_collection: str,
    new_collection: str,
    batch_size: int = 20
):
    """
    Migrate all points from old collection to new collection.

    Args:
        old_client: Client for old Qdrant instance
        new_client: Client for new Qdrant instance
        old_collection: Source collection name
        new_collection: Target collection name
        batch_size: Number of points to migrate per batch
    """
    logger.info("="*60)
    logger.info("🚀 Starting Qdrant Migration")
    logger.info("="*60)

    # Get collection info
    logger.info(f"📊 Checking old collection: {old_collection}")
    old_info = await get_collection_info(old_client, old_collection)

    if not old_info:
        logger.error(f"❌ Old collection '{old_collection}' not found or inaccessible")
        return False

    total_points = old_info.points_count
    logger.info(f"   Total points to migrate: {total_points}")

    # Check if new collection exists
    logger.info(f"📊 Checking new collection: {new_collection}")
    new_info = await get_collection_info(new_client, new_collection)

    if not new_info:
        logger.info(f"   Collection doesn't exist. Creating...")
        success = await create_target_collection(new_client, new_collection)
        if not success:
            return False
    else:
        logger.info(f"   Collection exists with {new_info.points_count} points")
        logger.warning("   ⚠️  This will add to existing collection")

    # Scroll through all points and migrate
    logger.info(f"\n📦 Starting migration in batches of {batch_size}...")

    migrated_count = 0
    offset = None
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info(f"\n--- Batch {batch_num} ---")

            # Scroll points from old collection
            logger.info(f"Fetching points from old collection...")
            scroll_result = await old_client.scroll(
                collection_name=old_collection,
                limit=batch_size,
                offset=offset,
                with_vectors=True,
                with_payload=True
            )

            points, next_offset = scroll_result

            if not points:
                logger.info("✅ No more points to migrate")
                break

            logger.info(f"Retrieved {len(points)} points")

            # Convert Record objects to PointStruct for upload
            logger.info(f"Converting points to PointStruct format...")
            point_structs = []
            for point in points:
                point_struct = models.PointStruct(
                    id=point.id,
                    vector=point.vector,
                    payload=point.payload
                )
                point_structs.append(point_struct)

            logger.info(f"Converted {len(point_structs)} points")

            # Upload to new collection with retry logic
            upload_success = False
            max_retries = 3

            for retry in range(max_retries):
                try:
                    logger.info(f"Uploading to new collection... (attempt {retry + 1}/{max_retries})")
                    await new_client.upsert(
                        collection_name=new_collection,
                        points=point_structs,
                        wait=True
                    )
                    upload_success = True
                    break
                except Exception as upload_error:
                    logger.warning(f"Upload attempt {retry + 1} failed: {upload_error}")
                    if retry < max_retries - 1:
                        wait_time = (retry + 1) * 10  # 10, 20, 30 seconds
                        logger.info(f"Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All upload attempts failed for batch {batch_num}")
                        raise

            if not upload_success:
                logger.error(f"Failed to upload batch {batch_num} after {max_retries} attempts")
                continue

            migrated_count += len(points)
            logger.info(f"✅ Migrated {len(points)} points (Total: {migrated_count}/{total_points})")

            # Update offset for next iteration
            offset = next_offset

            # Break if no more points
            if next_offset is None:
                break

        logger.info("\n" + "="*60)
        logger.info(f"✅ Migration Complete!")
        logger.info(f"   Total points migrated: {migrated_count}")
        logger.info("="*60)

        # Verify migration
        logger.info("\n📊 Verifying migration...")
        new_info = await get_collection_info(new_client, new_collection)
        logger.info(f"   Old collection: {total_points} points")
        logger.info(f"   New collection: {new_info.points_count} points")

        if new_info.points_count >= total_points:
            logger.info("✅ Verification successful!")
            return True
        else:
            logger.warning(f"⚠️  Point count mismatch! Expected >= {total_points}, got {new_info.points_count}")
            return False

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}", exc_info=True)
        return False


async def main():
    """Main migration function."""
    logger.info("🔧 Qdrant Migration Tool")
    logger.info("="*60)

    # Display configuration
    logger.info("Configuration:")
    logger.info(f"  Old Qdrant: {OLD_QDRANT_URL}")
    logger.info(f"  New Qdrant: {NEW_QDRANT_URL}")
    logger.info(f"  Old Collection: {OLD_COLLECTION}")
    logger.info(f"  New Collection: {NEW_COLLECTION}")
    logger.info("")

    # Confirm migration
    print("⚠️  WARNING: This will migrate ALL data from old to new Qdrant cluster.")
    print(f"   Source: {OLD_QDRANT_URL}/{OLD_COLLECTION}")
    print(f"   Target: {NEW_QDRANT_URL}/{NEW_COLLECTION}")
    print("")

    confirm = input("Continue? (yes/no): ").strip().lower()
    if confirm != "yes":
        logger.info("Migration cancelled by user")
        return

    # Initialize clients
    logger.info("\n🔌 Connecting to Qdrant instances...")

    old_client = AsyncQdrantClient(
        url=OLD_QDRANT_URL,
        api_key=OLD_QDRANT_API_KEY,
        timeout=300
    )

    new_client = AsyncQdrantClient(
        url=NEW_QDRANT_URL,
        api_key=NEW_QDRANT_API_KEY if NEW_QDRANT_API_KEY else None,
        timeout=300
    )

    logger.info("✅ Connected to both instances")

    # Perform migration
    success = await migrate_collection(
        old_client=old_client,
        new_client=new_client,
        old_collection=OLD_COLLECTION,
        new_collection=NEW_COLLECTION,
        batch_size=20
    )

    if success:
        logger.info("\n🎉 Migration completed successfully!")
        logger.info("\n📝 Next steps:")
        logger.info("1. Update .env with new Qdrant credentials")
        logger.info("2. Update vectordb_utils.py with new Qdrant URL")
        logger.info("3. Resume pipeline with: ./run_pipeline.sh")
    else:
        logger.error("\n❌ Migration failed. Please check logs and try again.")


if __name__ == "__main__":
    asyncio.run(main())
