from fastembed import TextEmbedding, LateInteractionTextEmbedding, SparseTextEmbedding
from qdrant_client.async_qdrant_client import AsyncQdrantClient
from qdrant_client import models
from qdrant_client.models import PointStruct
import pandas as pd
import os
import time
import uuid
from dotenv import load_dotenv
import ast
import logging
import json
import re
from logger import get_logger
import gc  # For garbage collection
from datetime import datetime

logger = get_logger(__name__)

load_dotenv(override=True)

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Use new Qdrant if configured, otherwise fall back to old
NEW_QDRANT_URL = os.getenv("NEW_QDRANT_URL")
NEW_QDRANT_API_KEY = os.getenv("NEW_QDRANT_API_KEY")

client = AsyncQdrantClient(
    url=NEW_QDRANT_URL,
    api_key=NEW_QDRANT_API_KEY if NEW_QDRANT_API_KEY else None,
    timeout=300
)

# REMOVE GLOBAL MODEL LOADING - Replace with lazy loading functions
# dense_embedding_model = TextEmbedding("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
# bm25_embedding_model = SparseTextEmbedding("Qdrant/bm25")
# late_interaction_embedding_model = LateInteractionTextEmbedding("colbert-ir/colbertv2.0")

# Global variables to cache models (loaded only when needed)
_dense_model = None
_bm25_model = None
_late_interaction_model = None

def get_dense_embedding_model():
    """Lazy load dense embedding model"""
    global _dense_model
    if _dense_model is None:
        logger.info("Loading dense embedding model...")
        _dense_model = TextEmbedding("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        logger.info("Dense embedding model loaded successfully")
    return _dense_model

def get_bm25_embedding_model():
    """Lazy load BM25 embedding model"""
    global _bm25_model
    if _bm25_model is None:
        logger.info("Loading BM25 embedding model...")
        _bm25_model = SparseTextEmbedding("Qdrant/bm25")
        logger.info("BM25 embedding model loaded successfully")
    return _bm25_model

def get_late_interaction_embedding_model():
    """Lazy load late interaction embedding model"""
    global _late_interaction_model
    if _late_interaction_model is None:
        logger.info("Loading late interaction embedding model...")
        _late_interaction_model = LateInteractionTextEmbedding("colbert-ir/colbertv2.0")
        logger.info("Late interaction embedding model loaded successfully")
    return _late_interaction_model

def clear_embedding_models():
    """Clear all embedding models from memory to free up RAM"""
    global _dense_model, _bm25_model, _late_interaction_model
    
    logger.info("Clearing embedding models from memory...")
    _dense_model = None
    _bm25_model = None
    _late_interaction_model = None
    
    # Force garbage collection
    gc.collect()
    logger.info("Embedding models cleared from memory")

def generate_collection_name(process_id: str = None) -> str:
    """Generate collection name with process_id and timestamp.
    
    Args:
        process_id: Optional process ID from pipeline. If None, uses 'default'
        
    Returns:
        Collection name in format: borges_collection_{process_id}_{timestamp}
    """
    pid = process_id if process_id else "default"
    return f"borges_collection_{pid}"

# Dynamic collection name - updates daily
target_collection_name = "borges_collection_default"

async def create_collection(collection_name: str = None):
    """
    Creates a collection in Qdrant with proper vector configurations for all embedding models.
    
    Args:
        collection_name: Name of the collection to create (defaults to target_collection_name)
        
    Returns:
        bool: True if collection was created successfully, False otherwise
    """
    try:
        logger.info(f"Creating collection '{collection_name}' in Qdrant...")
        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "paraphrase-multilingual-mpnet-base-v2": models.VectorParams(
                    size=768,  # Known dimension for this model
                    distance=models.Distance.COSINE
                ),
                "colbertv2.0": models.VectorParams(
                    size=128,  # Adjust if necessary based on model output
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
        logger.info(f"Successfully created collection '{collection_name}'")
        return True
    except Exception as e:
        logger.error(f"Failed to create collection '{collection_name}': {str(e)}", exc_info=True)
        return False

async def upload_results_csv_to_vectordb(
    csv_path: str,
    source_document: str,
    collection_name: str = None,
    process_id: str = None,
    batch_size: int = 10
):
    """
    Loads a results CSV in chunks, generates embeddings, and uploads to Qdrant
    in batches using asynchronous operations for uploading.

    Args:
        csv_path: Path to the input CSV file (expecting updated schema fields).
        source_document: Name of the source document for metadata.
        collection_name: Name of the Qdrant collection. Auto-generated if not provided.
        process_id: Process ID from pipeline for collection naming.
        batch_size: Number of rows to process and upload in each batch.
    """
    # Generate collection name if not provided
    if collection_name is None:
        collection_name = generate_collection_name(process_id)
        logger.info(f"Generated collection name: {collection_name}")
    
    total_rows_processed = 0
    start_time_overall = time.perf_counter()

    try:
        # Check if collection exists, create if it doesn't
        collections = await client.get_collections()
        collection_names = [col.name for col in collections.collections]
        if collection_name not in collection_names:
            logger.info(f"Collection '{collection_name}' not found. Attempting to create...")
            creation_success = await create_collection(collection_name)
            if not creation_success:
                logger.error(f"Failed to create collection '{collection_name}'. Aborting upload process.")
                return
        
        logger.info(f"Starting batched upload process for '{csv_path}' to collection '{NEW_QDRANT_URL}/{collection_name}'. Batch size: {batch_size}")
        
        # Verify file exists before starting
        if not os.path.exists(csv_path):
            logger.error(f"Error: CSV file not found at {csv_path}")
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Use chunksize to read the CSV in batches
        logger.info(f"Reading CSV file in batches: {csv_path}")
        try:
            chunk_iter = pd.read_csv(csv_path, chunksize=batch_size)
        except pd.errors.EmptyDataError:
            logger.error(f"Error: CSV file {csv_path} is empty.")
            raise
        except pd.errors.ParserError as e:
            logger.error(f"Error parsing CSV file {csv_path}: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error reading CSV file {csv_path}: {str(e)}", exc_info=True)
            raise

        for i, batch_df in enumerate(chunk_iter):
            batch_start_time = time.perf_counter()
            logger.info(f"--- Processing Batch {i+1} ({len(batch_df)} rows) ---")

            # 1. Prepare data for embedding within the batch
            prepare_start = time.perf_counter()
            doc_texts = []
            payloads = []
            point_ids = [] # Generate UUIDs now
            rows_parsed = 0
            rows_skipped = 0

            for index, row in batch_df.iterrows():
                try:
                    # Safely evaluate the string representation of the list
                    references_str = row['references']
                    if pd.isna(references_str):
                        references = []
                    else:
                        try:
                            # First try to parse as JSON since it might be JSON-encoded
                            references = json.loads(references_str)
                        except json.JSONDecodeError:
                            try:
                                # If JSON fails, try ast.literal_eval
                                references = ast.literal_eval(references_str)
                            except (SyntaxError, ValueError):
                                # If both fail, try to extract any text content
                                logger.warning(f"Could not parse references on row {index} in batch {i+1}. Attempting to extract text content.")
                                if isinstance(references_str, str):
                                    # Try to find any text content between quotes
                                    text_matches = re.findall(r'"text"\s*:\s*"([^"]*)"', references_str)
                                    if text_matches:
                                        references = [{"text": text} for text in text_matches]
                                    else:
                                        references = []
                                else:
                                    references = []

                    # Ensure references is a list
                    if not isinstance(references, list):
                        references = [references] if references else []

                    # Extract text from references, handling both dict and string formats
                    ref_texts = []
                    for ref in references:
                        if isinstance(ref, dict):
                            text = ref.get('text', '')
                        elif isinstance(ref, str):
                            text = ref
                        else:
                            text = str(ref)
                        if text:
                            ref_texts.append(text)
                    
                    ref_text = ' '.join(ref_texts)

                    # Use updated field names and handle potential NaN/None
                    entity_name = row.get('entity_name', '') or ""
                    entity_identification = row.get('entity_identification', '') or ""
                    description = row.get('entity_description', '') or "" # Use updated name
                    location = row.get('location', '') or "" # Use updated name

                    doc_text = f"{entity_name}: {entity_identification}. {description}. Reference Text: {ref_text}"
                    doc_texts.append(doc_text)

                    payload = {
                        # Use entity_occurrence_id if you generated that, otherwise use CSV index or generate new UUID here
                        # Using entity_occurrence_id from CSV if available
                        "entity_id": row.get('entity_id', str(uuid.uuid4())),
                        "entity_name": entity_name,
                        "aliases": row.get('aliases', '[]') or '[]',  # Store aliases as JSON string
                        "quotes": row.get('quotes', '[]') or '[]',  # Store quotes as JSON string
                        "entity_type": row.get('entity_type', '') or "",
                        "entity_category": row.get('entity_category', '') or "",
                        # Individual keyword fields (replacing vertical_keywords)
                        "century": row.get('century', '') or "",
                        "country": row.get('country', '') or "",
                        "literary_period": row.get('literary_period', '') or "",
                        "art_period": row.get('art_period', '') or "",
                        "historical_period": row.get('historical_period', '') or "",
                        "year": row.get('year', '') or "",
                        "author": row.get('author', '') or "",
                        "genre_keyword": row.get('genre', '') or "",  # Renamed to avoid conflict with document metadata 'genre'
                        "geo_type": row.get('geo_type', '') or "",
                        "institution_type": row.get('institution_type', '') or "",
                        # Entity fields
                        "entity_identification": entity_identification,
                        "entity_description": description,
                        "references": ref_text,
                        "location": location,
                        "source_document": source_document,
                        # Document metadata fields (not indexed, just stored in payload)
                        "collection_name": row.get('collection_name', '') or "",
                        "book_name": row.get('book_name', '') or "",
                        "index_name": row.get('index_name', '') or "",
                        "document_title": row.get('document_title', '') or "",
                        "publication_year": row.get('publication_year', '') or "",
                        "genre": row.get('genre', '') or "",  # Document genre metadata
                        "file_path": row.get('file_path', '') or ""
                    }
                    payloads.append(payload)
                    point_ids.append(str(uuid.uuid4())) # Unique ID for the Qdrant point itself
                    rows_parsed += 1

                except Exception as e:
                    logger.warning(f"Error processing row {index} in batch {i+1}. Error: {str(e)}")
                    logger.debug(f"Problematic row data: {row.to_dict()}")
                    rows_skipped += 1
                    continue

            prepare_end = time.perf_counter()
            logger.info(f"Batch {i+1}: Data preparation took {prepare_end - prepare_start:.4f}s. Parsed: {rows_parsed}, Skipped: {rows_skipped}")

            if not doc_texts:
                logger.warning(f"Batch {i+1}: No valid data found to process, skipping to next batch.")
                continue

            # 2. Generate Embeddings for the batch - USE LAZY LOADING
            embed_start = time.perf_counter()
            try:
                logger.info(f"Batch {i+1}: Generating embeddings for {len(doc_texts)} documents...")
                
                # Load models one by one and generate embeddings
                logger.info(f"Batch {i+1}: Generating dense embeddings...")
                dense_model = get_dense_embedding_model()
                dense_embeddings = list(dense_model.embed(doc_texts))
                
                logger.info(f"Batch {i+1}: Generating BM25 embeddings...")
                bm25_model = get_bm25_embedding_model()
                bm25_embeddings = list(bm25_model.embed(doc_texts))
                
                logger.info(f"Batch {i+1}: Generating late interaction embeddings...")
                late_interaction_model = get_late_interaction_embedding_model()
                late_interaction_embeddings = list(late_interaction_model.embed(doc_texts))

                if len(dense_embeddings) != len(doc_texts) or len(bm25_embeddings) != len(doc_texts) or len(late_interaction_embeddings) != len(doc_texts):
                    logger.warning(f"Batch {i+1}: Mismatch in embedding counts. Expected {len(doc_texts)}, got: Dense={len(dense_embeddings)}, BM25={len(bm25_embeddings)}, Late={len(late_interaction_embeddings)}")

            except ValueError as e:
                logger.error(f"Batch {i+1}: Value error generating embeddings: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Batch {i+1}: Failed to generate embeddings. Error: {str(e)}", exc_info=True)
                continue # Skip this batch if embedding fails
                
            embed_end = time.perf_counter()
            logger.info(f"Batch {i+1}: Embedding generation took {embed_end - embed_start:.4f}s")

            # 3. Create Qdrant PointStructs for the batch
            points_start = time.perf_counter()
            points_batch = []
            points_created = 0
            points_failed = 0
            
            for idx, (p_id, dense_emb, bm25_emb, late_emb, payload) in enumerate(zip(point_ids, dense_embeddings, bm25_embeddings, late_interaction_embeddings, payloads)):
                try:
                    # Adapt vector structuring based on actual model outputs and Qdrant requirements
                    vector_dict = {
                        # Ensure dense vectors are lists of floats
                        "paraphrase-multilingual-mpnet-base-v2": [float(x) for x in dense_emb],
                        # Ensure sparse vectors are in Qdrant format (assuming model returns object with indices/values)
                        "bm25": models.SparseVector(indices=bm25_emb.indices, values=[float(v) for v in bm25_emb.values]),
                         # Ensure Colbert vectors are lists of lists of floats
                        "colbertv2.0": [[float(x) for x in vec] for vec in late_emb]
                    }

                    point = models.PointStruct(
                        id=p_id,
                        vector=vector_dict,
                        payload=payload
                    )
                    points_batch.append(point)
                    points_created += 1
                    
                except AttributeError as e:
                    logger.warning(f"Error creating PointStruct for item {idx} in batch {i+1}. Likely missing indices/values in sparse vector: {str(e)}")
                    logger.debug(f"Problem data: Entity={payload.get('entity_name')}, BM25={type(bm25_emb)}")
                    points_failed += 1
                    continue # Skip this point
                except Exception as e:
                    logger.warning(f"Error creating PointStruct for item {idx} in batch {i+1}: {str(e)}")
                    points_failed += 1
                    continue # Skip this point

            points_end = time.perf_counter()
            logger.info(f"Batch {i+1}: PointStruct creation took {points_end - points_start:.4f}s. Created: {points_created}, Failed: {points_failed}")

            if not points_batch:
                logger.warning(f"Batch {i+1}: No valid points created after embedding, skipping upload.")
                continue

            # 4. Upload the batch to Qdrant asynchronously
            upload_start = time.perf_counter()
            try:
                logger.info(f"Batch {i+1}: Attempting to upsert {len(points_batch)} points...")
                # Using await for the async client upsert method
                await client.upsert(
                    collection_name=collection_name,
                    points=points_batch,
                    wait=True # Set wait=True for confirmation, False for fire-and-forget (faster but less certain)
                )
                upload_end = time.perf_counter()
                total_rows_processed += len(points_batch) # Only count successfully prepared points
                logger.info(f"Batch {i+1}: Successfully upserted {len(points_batch)} points in {upload_end - upload_start:.4f}s. (Total processed: {total_rows_processed})")

            except Exception as e:
                upload_end = time.perf_counter()
                logger.error(f"Batch {i+1}: Failed to upsert points after {upload_end - upload_start:.4f}s. Error: {str(e)}", exc_info=True)
                # Decide how to handle batch failure: retry? log failed IDs? continue?
                # For now, we just log and continue to the next batch.
                continue

            batch_end_time = time.perf_counter()
            logger.info(f"--- Batch {i+1} processing finished in {batch_end_time - batch_start_time:.4f}s ---")

            # OPTIONAL: Clear embeddings from memory after each batch to save RAM
            del dense_embeddings, bm25_embeddings, late_interaction_embeddings
            gc.collect()

    except FileNotFoundError:
        logger.error(f"Error: CSV file not found at {csv_path}")
        raise
    except pd.errors.EmptyDataError:
        logger.error(f"Error: CSV file {csv_path} is empty.")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred during the CSV reading/batching loop: {str(e)}", exc_info=True)
        raise
    finally:
        end_time_overall = time.perf_counter()
        logger.info(f"=== Finished processing all batches ===")
        logger.info(f"Total rows processed and attempted to upload: {total_rows_processed}")
        logger.info(f"Total execution time: {end_time_overall - start_time_overall:.2f} seconds")


async def upload_merged_entities_to_vectordb(
    csv_path: str,
    collection_name: str = None,
    process_id: str = None,
    batch_size: int = 10
):
    """
    Upload merged entities CSV to a Qdrant collection.
    This handles the unique_entities CSV format (after deduplication).

    Args:
        csv_path: Path to the merged/unique entities CSV file
        collection_name: Name of the Qdrant collection. Auto-generated if not provided.
        process_id: Process ID from pipeline for collection naming.
        batch_size: Number of rows to process and upload in each batch
    """
    # Generate collection name if not provided
    if collection_name is None:
        collection_name = generate_collection_name(process_id)
        logger.info(f"Generated collection name: {collection_name}")
    
    total_rows_processed = 0
    start_time_overall = time.perf_counter()

    try:
        # Check if collection exists, create if it doesn't
        collections = await client.get_collections()
        collection_names = [col.name for col in collections.collections]
        if collection_name not in collection_names:
            logger.info(f"Collection '{collection_name}' not found. Creating...")
            creation_success = await create_collection(collection_name)
            if not creation_success:
                logger.error(f"Failed to create collection '{collection_name}'. Aborting.")
                return

        logger.info(f"Uploading merged entities to '{collection_name}' from '{csv_path}'")

        # Verify file exists
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Read CSV in batches
        chunk_iter = pd.read_csv(csv_path, chunksize=batch_size)

        for i, batch_df in enumerate(chunk_iter):
            batch_start_time = time.perf_counter()
            logger.info(f"--- Processing Batch {i+1} ({len(batch_df)} rows) ---")

            doc_texts = []
            payloads = []
            point_ids = []
            rows_parsed = 0

            for index, row in batch_df.iterrows():
                try:
                    # Handle both raw and merged CSV formats
                    entity_id = row.get('root_entity_id') or row.get('entity_id', str(uuid.uuid4()))
                    entity_name = row.get('entity_name', '') or ""
                    entity_type = row.get('entity_type', '') or ""
                    entity_category = row.get('entity_category', '') or ""
                    entity_identification = row.get('entity_identification', '') or ""

                    # Handle merged description (from unique entities) or raw description
                    description = row.get('merged_description') or row.get('entity_description', '') or ""

                    # Handle merged references
                    references_str = row.get('merged_references') or row.get('references', '')
                    ref_text = ""
                    if references_str and pd.notna(references_str):
                        if isinstance(references_str, str):
                            # For merged_references, it's usually newline-separated text
                            ref_text = references_str.replace('\n', ' ')[:1000]  # Truncate if too long

                    # Create embedding text from merged/enriched data
                    doc_text = f"{entity_name}: {entity_identification}. {description}. Reference: {ref_text}"
                    doc_texts.append(doc_text)

                    # Parse merged keywords if available
                    keywords_data = row.get('merged_keywords') or row.get('keywords', '[]')
                    keyword_dict = {}
                    if keywords_data and pd.notna(keywords_data):
                        try:
                            if isinstance(keywords_data, str):
                                keywords_list = json.loads(keywords_data)
                                for item in keywords_list:
                                    if isinstance(item, str) and ':' in item:
                                        key, value = item.split(':', 1)
                                        keyword_dict[key.strip()] = value.strip()
                        except (json.JSONDecodeError, ValueError):
                            pass

                    payload = {
                        "entity_id": entity_id,
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                        "entity_category": entity_category,
                        "entity_identification": entity_identification,
                        "entity_description": description,
                        "references": ref_text,
                        # Keyword fields
                        "century": keyword_dict.get('century', ''),
                        "country": keyword_dict.get('country', ''),
                        "literary_period": keyword_dict.get('literary_period', ''),
                        "art_period": keyword_dict.get('art_period', ''),
                        "historical_period": keyword_dict.get('historical_period', ''),
                        "year": keyword_dict.get('year', ''),
                        "author": keyword_dict.get('author', ''),
                        "genre_keyword": keyword_dict.get('genre', ''),
                        "geo_type": keyword_dict.get('geo_type', ''),
                        "institution_type": keyword_dict.get('institution_type', ''),
                        # Metadata
                        "aliases": row.get('merged_aliases') or row.get('aliases', '[]'),
                        "quotes": row.get('merged_quotes') or row.get('quotes', '[]'),
                        "document_titles": row.get('document_titles', ''),
                        "occurrence_count": int(row.get('occurrence_count', 1)) if pd.notna(row.get('occurrence_count')) else 1,
                        "source_document": "merged_entities"
                    }
                    payloads.append(payload)
                    point_ids.append(str(uuid.uuid4()))
                    rows_parsed += 1

                except Exception as e:
                    logger.warning(f"Error processing row {index} in batch {i+1}: {e}")
                    continue

            if not doc_texts:
                logger.warning(f"Batch {i+1}: No valid data, skipping")
                continue

            # Generate embeddings
            try:
                logger.info(f"Batch {i+1}: Generating embeddings for {len(doc_texts)} documents...")

                dense_model = get_dense_embedding_model()
                dense_embeddings = list(dense_model.embed(doc_texts))

                bm25_model = get_bm25_embedding_model()
                bm25_embeddings = list(bm25_model.embed(doc_texts))

                late_interaction_model = get_late_interaction_embedding_model()
                late_interaction_embeddings = list(late_interaction_model.embed(doc_texts))

            except Exception as e:
                logger.error(f"Batch {i+1}: Failed to generate embeddings: {e}")
                continue

            # Create Qdrant points
            points_batch = []
            for idx, (p_id, dense_emb, bm25_emb, late_emb, payload) in enumerate(
                zip(point_ids, dense_embeddings, bm25_embeddings, late_interaction_embeddings, payloads)
            ):
                try:
                    vector_dict = {
                        "paraphrase-multilingual-mpnet-base-v2": [float(x) for x in dense_emb],
                        "bm25": models.SparseVector(indices=bm25_emb.indices, values=[float(v) for v in bm25_emb.values]),
                        "colbertv2.0": [[float(x) for x in vec] for vec in late_emb]
                    }
                    point = models.PointStruct(id=p_id, vector=vector_dict, payload=payload)
                    points_batch.append(point)
                except Exception as e:
                    logger.warning(f"Error creating point {idx}: {e}")
                    continue

            if not points_batch:
                continue

            # Upload to Qdrant
            try:
                await client.upsert(
                    collection_name=collection_name,
                    points=points_batch,
                    wait=True
                )
                total_rows_processed += len(points_batch)
                logger.info(f"Batch {i+1}: Uploaded {len(points_batch)} points (Total: {total_rows_processed})")
            except Exception as e:
                logger.error(f"Batch {i+1}: Upload failed: {e}")
                continue

            # Clear memory
            del dense_embeddings, bm25_embeddings, late_interaction_embeddings
            gc.collect()

    except Exception as e:
        logger.error(f"Error uploading merged entities: {e}", exc_info=True)
        raise
    finally:
        end_time = time.perf_counter()
        logger.info(f"Upload complete: {total_rows_processed} entities in {end_time - start_time_overall:.2f}s")


from collections import OrderedDict
async def query_hybrid_search(query_text, entity_type, entity_name, primary_entity_id, excluded_entity_ids, collection_name: str = None, process_id: str = None):
    """
    Generate embeddings and query Qdrant for similar entities.

    Args:
        query_text: Text to search for
        entity_type: Type of entity to filter by
        entity_name: Name of the entity being searched
        primary_entity_id: ID of the primary entity (excluded from results)
        excluded_entity_ids: Set of entity IDs to exclude from results
        collection_name: Optional collection name. Auto-generated if not provided.
        process_id: Process ID from pipeline for collection naming.
    """
    # Generate collection name if not provided
    if collection_name is None:
        collection_name = generate_collection_name(process_id)
    search_collection = collection_name
    try:
        # Generate query embeddings using lazy loading
        logger.info(f"Generating query embeddings for entity '{entity_name}' of type '{entity_type}'")
        try:
            dense_model = get_dense_embedding_model()
            dense_vectors = next(dense_model.query_embed(query_text))
            
            bm25_model = get_bm25_embedding_model()
            sparse_vectors = next(bm25_model.query_embed(query_text))
            
            late_interaction_model = get_late_interaction_embedding_model()
            late_vectors = next(late_interaction_model.query_embed(query_text))
            
            logger.info("Query embeddings generated successfully")
        except StopIteration as e:
            logger.error(f"Failed to generate embeddings - empty iterator returned: {e}")
            return []
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise

        # Create filters
        try:
            must_not = []
            if excluded_entity_ids or primary_entity_id:
                exclude_ids = list(excluded_entity_ids) if excluded_entity_ids else []
                if primary_entity_id:
                    exclude_ids.append(primary_entity_id)
                #logger.info(f"Excluding entity IDs in Qdrant: {exclude_ids}")
                must_not.append(models.FieldCondition(key="entity_id", match=models.MatchAny(any=exclude_ids)))

            # Filter for Query 1: entity_name == "Argentina" and entity_type == "PLACES"
            filter1 = models.Filter(
                must=[
                    models.FieldCondition(key="entity_name", match=models.MatchValue(value=entity_name)),
                    models.FieldCondition(key="entity_type", match=models.MatchValue(value=entity_type))
                ],
                must_not=must_not
            )
            filter2 = models.Filter(
                must=[
                    models.FieldCondition(key="entity_type", match=models.MatchValue(value=entity_type))
                ],
                must_not=must_not)
            
            # Prepare prefetch for dense and sparse vectors
            prefetch = [
                models.Prefetch(
                    query=dense_vectors.tolist(),
                    using="paraphrase-multilingual-mpnet-base-v2",
                    limit=50
                ),
                models.Prefetch(
                    query=models.SparseVector(**sparse_vectors.as_object()),
                    using="bm25",
                    limit=50
                )
            ]
        except Exception as e:
            logger.error(f"Error creating filters or prefetch: {e}")
            raise

        # Query Qdrant
        logger.info(f"Querying Qdrant collection {search_collection} ...")

        try:
            results1 = await client.query_points(
                collection_name=search_collection,
                prefetch=prefetch,
                query=[vec.tolist() for vec in late_vectors],  # Convert late interaction vectors to list
                using="colbertv2.0",
                query_filter=filter1,
                with_payload=True,
                limit=40
            )
            logger.info(f"Query 1 (entity_name={entity_name}) completed with {len(results1.model_dump().get('points', []))} results")
        except Exception as e:
            logger.error(f"Error in first query (entity_name filter): {repr(e)}", exc_info=True)
            results1 = None

        try:
            results2 = await client.query_points(
                collection_name=search_collection,
                prefetch=prefetch,
                query=[vec.tolist() for vec in late_vectors],  # Convert late interaction vectors to list
                using="colbertv2.0",
                query_filter=filter2,
                with_payload=True,
                limit=40
            )
            logger.info(f"Query 2 (entity_type={entity_type}) completed with {len(results2.model_dump().get('points', []))} results")
        except Exception as e:
            logger.error(f"Error in second query (entity_type filter): {repr(e)}", exc_info=True)
            results2 = None

        # Process and combine results
        combined_points = OrderedDict()
        
        try:
            # Add results from Query 1 first (prioritized) if available
            if results1:
                points1 = results1.model_dump().get('points', [])
                for point in points1:
                    try:
                        entity_id = point.get("payload", {}).get("entity_id")
                        if entity_id:
                            combined_points[entity_id] = point
                    except Exception as e:
                        logger.warning(f"Error processing point from query 1: {e}")
                        continue
            
            # Add results from Query 2 if entity_id is not already present
            if results2:
                points2 = results2.model_dump().get('points', [])
                for point in points2:
                    try:
                        entity_id = point.get("payload", {}).get("entity_id")
                        if entity_id and entity_id not in combined_points:
                            combined_points[entity_id] = point
                    except Exception as e:
                        logger.warning(f"Error processing point from query 2: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error combining query results: {e}")
            # Return any results we have so far or an empty list
            return list(combined_points.values()) if combined_points else []

        # Convert to list for final output
        final_results = list(combined_points.values())
        logger.info(f"Query completed successfully with {len(final_results)} total combined results")
        return final_results

    except Exception as e:
        logger.error(f"Unhandled error during hybrid search query: {e}", exc_info=True)
        # Return empty results rather than crashing the whole process
        return []