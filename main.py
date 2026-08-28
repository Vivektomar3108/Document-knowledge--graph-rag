import os
import sys
import asyncio
from pdf_utils import get_pdf_files, load_pdf_and_metadata
from xml_utils import get_xml_files, load_xml_and_metadata
from knowledgegraph import process_text_to_graph_data
from csv_utils import create_chunks_csv, create_results_csv, merge_csv_files
from entity_utils import generate_unique_entities_csv
from iterative_dedup import run_iterative_deduplication
from enrich_csv import enrich_merged_csv_with_fields
from vectordb_utils import upload_results_csv_to_vectordb
from mapping_entity_csv_utils import create_filtered_entity_mapping
import datetime
from normalization_utils import create_normalized_entity_tables
from relationship_utils import create_relationship_csv
from relationship_aggregation_utils import aggregate_relationships_for_unique_entities
from horizontal_keywords_utils import process_csv_for_horizontal_keywords

# --- Logging Configuration ---
from logger import setup_logger
logger = setup_logger(__name__)

# --- Cost Tracking ---
from cost_tracking_utils import PipelineCostTracker
import description_validation_utils

# --- Progress Tracking ---
from progress_tracker import ProgressTracker, DiskSpaceMonitor

# --- Environment Variable Checks ---
REQUIRED_ENV_VARS = ["OPENAI_API_KEY", "LANGCHAIN_API_KEY"]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}. Exiting.")
    sys.exit(1)


async def process_document_directory(
    input_dir="pdfs",
    output_dir="results",
    file_type="pdf",
    extraction_provider="openai",
    extraction_model="gpt-4.1",
    merging_provider="openai",
    merging_model="gpt-4.1-mini",
    used_llamaparse=True,
    enable_cost_tracking=True,
    use_iterative_dedup=True,
    iterative_dedup_max_rounds=10,
    status_callback=None,
    custom_prompt=None,
    process_id=None,
    max_concurrent_chunks=5
):
    """
    Process all document files (PDF or XML) in a directory through the knowledge graph pipeline.
    Stops execution if 5 consecutive documents fail.

    Args:
        input_dir: Directory containing input files
        output_dir: Directory for output files
        file_type: Type of files to process ("pdf" or "xml")
        extraction_provider: LLM provider for entity extraction
        extraction_model: Model name for entity extraction
        merging_provider: LLM provider for entity merging
        merging_model: Model name for entity merging
        used_llamaparse: Whether to use LlamaParse for PDFs (ignored for XML)
        enable_cost_tracking: Enable token usage and cost tracking (default: True)
        use_iterative_dedup: Use iterative deduplication instead of single-pass (default: True)
        iterative_dedup_max_rounds: Max rounds for iterative deduplication (default: 10)
        status_callback: Optional async callable(step, message, details) called at each pipeline
                         step transition.  Used by the FastAPI layer to push live status to the DB.
        custom_prompt: Optional custom extraction prompt string.  When provided, overrides the
                       built-in default prompt during entity extraction.
        process_id: Process ID for the pipeline run (used for collection naming)
        max_concurrent_chunks: Maximum number of chunks to process in parallel (default: 5)
    """

    # --- helper: safely invoke the status callback (no-op when running CLI) ---
    async def _notify(step: str, message: str, details: dict = None):
        if status_callback:
            try:
                await status_callback(step, message, details)
            except Exception as cb_err:
                logger.warning(f"Status callback error (non-fatal): {cb_err}")
    file_type = file_type.lower()
    if file_type not in ["pdf", "xml"]:
        logger.error(f"Invalid file_type: {file_type}. Must be 'pdf' or 'xml'.")
        return None

    logger.info(f"=== Starting {file_type.upper()} directory processing ===")
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"File type: {file_type.upper()}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Extraction Provider: {extraction_provider}")
    logger.info(f"Extraction Model: {extraction_model}")
    logger.info(f"Merging Provider: {merging_provider}")
    logger.info(f"Merging Model: {merging_model}")
    logger.info(f"Cost Tracking: {'Enabled' if enable_cost_tracking else 'Disabled'}")
    logger.info(f"Iterative Deduplication: {'Enabled' if use_iterative_dedup else 'Disabled'}")
    if use_iterative_dedup:
        logger.info(f"Max Dedup Rounds: {iterative_dedup_max_rounds}")

    # Initialize disk space monitor
    disk_monitor = DiskSpaceMonitor(threshold_percent=95.0)
    disk_monitor.log_disk_space(output_dir)

    # Check minimum disk space (at least 1GB free)
    if not disk_monitor.ensure_minimum_space(min_gb=1.0, path=output_dir):
        logger.error("❌ Insufficient disk space. Aborting pipeline.")
        return None

    # Initialize pipeline cost tracker
    pipeline_tracker = None
    extraction_stats = None
    merging_stats = None
    validation_stats = None
    horizontal_keywords_stats = None

    if enable_cost_tracking and extraction_provider.lower() == "openai":
        pipeline_tracker = PipelineCostTracker()
        extraction_stats = pipeline_tracker.get_or_create_tracker("Entity Extraction", extraction_model)
        merging_stats = pipeline_tracker.get_or_create_tracker("Entity Merging", merging_model)
        validation_stats = pipeline_tracker.get_or_create_tracker("Description Validation", "gpt-4.1-nano")
        horizontal_keywords_stats = pipeline_tracker.get_or_create_tracker("Horizontal Keywords", merging_model)

        # Set validation stats tracker globally
        description_validation_utils.set_stats_tracker(validation_stats)

        logger.info("✅ Cost tracking initialized for all pipeline stages")

    # Create output directory if it doesn't exist
    try:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Ensured output directory exists: {output_dir}")
    except PermissionError:
        logger.error(f"Permission denied when creating output directory: {output_dir}")
        return None
    except OSError as e:
        logger.error(f"OS error when creating output directory: {str(e)}")
        return None
    
    # Get all files in the directory based on file type
    if file_type == "pdf":
        document_files = get_pdf_files(input_dir)
        if not document_files:
            logger.error(f"No PDF files found in directory: {input_dir}")
            return None
    else:  # xml
        document_files = get_xml_files(input_dir)
        if not document_files:
            logger.error(f"No XML files found in directory: {input_dir}")
            return None

    # Initialize progress tracker (with auto-sync to CSVs)
    progress_tracker = ProgressTracker(output_dir, model_name=extraction_model)

    # Filter out already processed documents based on extraction_completed set
    all_doc_names = [os.path.splitext(os.path.basename(doc))[0] for doc in document_files]

    # Get pending documents from progress tracker
    pending_doc_names_set = set(progress_tracker.get_pending_documents(document_files))

    # Filter document_files to only include pending documents
    # IMPORTANT: Only process documents NOT in extraction_completed
    filtered_files = []
    skipped_count = 0

    for doc in document_files:
        doc_name = os.path.splitext(os.path.basename(doc))[0]
        if doc_name in pending_doc_names_set:
            filtered_files.append(doc)
        else:
            skipped_count += 1

    document_files = filtered_files

    logger.info(f"📋 Skipping {skipped_count} already completed documents")
    logger.info(f"📋 Processing {len(document_files)} pending documents out of {len(all_doc_names)} total")

    if not document_files:
        logger.info(f"✅ All documents have already been processed. Skipping extraction phase.")
        logger.info(f"📋 Proceeding to entity merging phase...")
        # Skip to merging phase
        document_files = []

    # Lists to track generated CSV files
    chunks_csv_files = []
    results_csv_files = []

    # Track consecutive document failures
    consecutive_failures = 0
    max_consecutive_failures = 5

    total_docs = len(document_files)
    await _notify("text_extraction", f"Starting text extraction for {total_docs} document(s)")

    # Process each document file
    for doc_idx, doc_path in enumerate(document_files, start=1):
        await _notify("text_extraction",
                      f"Processing document {doc_idx}/{total_docs}: {os.path.basename(doc_path)}",
                      {"doc_index": doc_idx, "total_docs": total_docs})

        # Load document based on type (run in thread pool to avoid blocking)
        if file_type == "pdf":
            document_name, document_text, document_metadata = await asyncio.to_thread(
                load_pdf_and_metadata, doc_path, used_llamaparse
            )
        else:  # xml
            document_name, document_text, document_metadata = await asyncio.to_thread(
                load_xml_and_metadata, doc_path
            )

        if document_name is None or document_text is None:
            consecutive_failures += 1
            logger.warning(f"{file_type.upper()} failed to load: {doc_path}. Consecutive failures: {consecutive_failures}")
            if consecutive_failures >= max_consecutive_failures:
                logger.error(f"Stopping pipeline: {consecutive_failures} consecutive {file_type.upper()} failures.")
                break
            continue

        # Reset failure counter on success
        consecutive_failures = 0
        logger.info(f"\n=== Processing {file_type.upper()}: {document_name} ===")

        # Log metadata if available
        if document_metadata:
            logger.info(f"Metadata: Book='{document_metadata.get('book_name', '')}', "
                       f"Title='{document_metadata.get('document_title', '')}', "
                       f"Year='{document_metadata.get('publication_year', '')}', "
                       f"Genre='{document_metadata.get('genre', '')}'")

        # Step 2: Process text to generate chunks and extract entities
        try:
            await _notify("entity_extraction",
                          f"Extracting entities from {document_name}",
                          {"document": document_name})
            logger.info(f"Processing text to graph data for {document_name}...")
            chunk_data_list, llm_responses = await process_text_to_graph_data(
                document_text, document_name, extraction_provider, extraction_model,
                stats_tracker=extraction_stats,
                document_metadata=document_metadata,
                custom_prompt=custom_prompt,
                max_concurrent_chunks=max_concurrent_chunks
            )
            if not chunk_data_list or not llm_responses:
                consecutive_failures += 1
                logger.warning(f"Document processing failed for {document_name}. Consecutive failures: {consecutive_failures}")
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(f"Stopping pipeline: {consecutive_failures} consecutive document failures.")
                    break
                continue
            # Reset failure counter on success
            consecutive_failures = 0
            logger.info(f"Successfully processed text - generated {len(chunk_data_list)} chunks and {len(llm_responses)} responses")
        except Exception as e:
            logger.error(f"Failed to process text to graph data for {document_name}: {str(e)}", exc_info=True)
            consecutive_failures += 1
            logger.warning(f"Document processing failed for {document_name}. Consecutive failures: {consecutive_failures}")
            if consecutive_failures >= max_consecutive_failures:
                logger.error(f"Stopping pipeline: {consecutive_failures} consecutive document failures.")
                break
            continue
        
        # Step 3: Write Chunks CSV (run in thread pool to avoid blocking)
        chunks_csv_path = os.path.join(output_dir, f"{document_name}_chunks_{extraction_model}.csv")
        try:
            logger.info(f"Creating chunks CSV file at: {chunks_csv_path}")
            await asyncio.to_thread(create_chunks_csv, chunk_data_list, document_name, chunks_csv_path)
            chunks_csv_files.append(chunks_csv_path)
            logger.info(f"Successfully created chunks CSV: {chunks_csv_path}")
        except IOError as e:
            logger.error(f"I/O error writing chunks CSV for {document_name}: {str(e)}")
            continue
        except Exception as e:
            logger.error(f"Failed to write chunks CSV for {document_name}: {str(e)}", exc_info=True)
            continue
        
        # Step 4: Write Results CSV (run in thread pool to avoid blocking)
        results_csv_path = os.path.join(output_dir, f"{document_name}_results_raw_{extraction_model}.csv")
        try:
            logger.info(f"Creating results CSV file at: {results_csv_path}")
            await asyncio.to_thread(create_results_csv, llm_responses, chunk_data_list, document_name, results_csv_path)
            results_csv_files.append(results_csv_path)
            logger.info(f"Successfully created results CSV: {results_csv_path}")
        except IOError as e:
            logger.error(f"I/O error writing results CSV for {document_name}: {str(e)}")
            continue
        except Exception as e:
            logger.error(f"Failed to write results CSV for {document_name}: {str(e)}", exc_info=True)
            continue
        
        # Step 5: Upload to Qdrant VectorDB
        await _notify("vector_indexing",
                      f"Uploading {document_name} to vector database",
                      {"document": document_name})
        vectordb_success = False
        try:
            # Check if already uploaded to avoid duplicate uploads
            if not progress_tracker.is_vectordb_completed(document_name):
                logger.info(f"Uploading results CSV for {document_name} to Qdrant vector database...")
                await upload_results_csv_to_vectordb(
                    results_csv_path, 
                    document_name,
                    process_id=str(process_id) if process_id else None
                )
                logger.info(f"Successfully uploaded results to vector database for {document_name}")
                progress_tracker.mark_vectordb_completed(document_name)
                vectordb_success = True
            else:
                logger.info(f"✅ Vector DB upload already completed for {document_name}, skipping upload")
                vectordb_success = True
        except FileNotFoundError:
            logger.error(f"Results CSV not found during vector database upload: {results_csv_path}")
            continue
        except Exception as e:
            logger.error(f"Failed to upload {document_name} to Qdrant vector database: {str(e)}", exc_info=True)
            continue

        # Mark document as fully processed only if everything succeeded
        if vectordb_success:
            progress_tracker.mark_extraction_completed(document_name)
            logger.info(f"=== Successfully completed processing for {file_type.upper()}: {document_name} ===")
            
            # Update progress via status callback with per-file details
            if results_csv_path and os.path.exists(results_csv_path):
                try:
                    import pandas as pd
                    results_df = pd.read_csv(results_csv_path)
                    entities_in_doc = len(results_df)
                    
                    await _notify(
                        "entity_extraction",
                        f"Completed {doc_idx}/{total_docs} documents",
                        {
                            "processed_documents": doc_idx,
                            "total_documents": total_docs,
                            "filename": os.path.basename(doc_path),
                            "entities_count": entities_in_doc,
                            "status": "completed"
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to send file completion details: {e}")

            # Periodically check disk space
            if len(results_csv_files) % 10 == 0:
                disk_monitor.log_disk_space(output_dir)

    # Check if we successfully processed any documents
    # If no new documents were processed, try to find existing result CSV files
    if not results_csv_files:
        logger.info("No new documents were processed in this run. Looking for existing result CSV files...")
        # Find all existing result CSV files in the output directory
        import glob
        existing_results = glob.glob(os.path.join(output_dir, f"*_results_raw_{extraction_model}.csv"))
        if existing_results:
            results_csv_files = existing_results
            logger.info(f"Found {len(results_csv_files)} existing result CSV files to merge")
        else:
            logger.error(f"No {file_type.upper()} files found (new or existing). Cannot proceed with merging.")
            return None
        
    # Merge all result CSVs into a single file
    await _notify("csv_merging", "Merging all document result CSVs into a single file")
    logger.info("\n=== Starting CSV merge phase ===")
    merged_results_csv = os.path.join(output_dir, f"all_{extraction_model}_merged_results.csv")

    # DISCOVERY: Find ALL matching CSV files in the directory to handle resume/restart scenarios
    # This ensures we merge files from previous runs, not just the ones processed in this specific execution.
    import glob
    csv_pattern = os.path.join(output_dir, f"*_results_raw_{extraction_model}.csv")
    all_csv_files = glob.glob(csv_pattern)

    if not all_csv_files:
        logger.error(f"No result CSV files found matching pattern: {csv_pattern}")
        logger.error(f"Cannot proceed with merging.")
        return {
            "chunks_csv_files": chunks_csv_files,
            "results_csv_files": results_csv_files, # Return what we have tracked so far
            "merged_results": None,
            "unique_entities": None,
            "entity_mapping": None
        }

    logger.info(f"Found {len(all_csv_files)} total result CSV files to merge (combining current and previous runs)")

    # Clear any stale entity merging checkpoints since we're rebuilding the merged CSV
    # The checkpoint may be from a previous run with different data
    checkpoint_dir = "temporary_unique_files"
    if os.path.exists(checkpoint_dir):
        from entity_checkpoint import EntityMergingCheckpoint
        temp_checkpoint_manager = EntityMergingCheckpoint(checkpoint_dir)
        checkpoint_state = temp_checkpoint_manager.load_checkpoint()
        if checkpoint_state:
            logger.info("🧹 Found existing entity merging checkpoint - clearing it since merged CSV is being rebuilt")
            temp_checkpoint_manager.clear_checkpoint()
            # Also clear the entity tracker
            from persistent_entity_tracker import PersistentEntityIDTracker
            tracker_path = os.path.join(checkpoint_dir, "processed_entity_ids.json")
            if os.path.exists(tracker_path):
                temp_tracker = PersistentEntityIDTracker(tracker_path, auto_save=False)
                temp_tracker.clear()
                logger.info("🧹 Cleared entity ID tracker as well")

    try:
        logger.info(f"Merging {len(all_csv_files)} results CSV files...")
        merged_csv_path = await merge_csv_files(all_csv_files, merged_results_csv)
        
        if not merged_csv_path:
            logger.error("CSV merge failed. Cannot proceed with entity extraction.")
            return {
                "chunks_csv_files": chunks_csv_files,
                "results_csv_files": results_csv_files,
                "merged_results": None,
                "unique_entities": None,
                "entity_mapping": None
            }
        
        # Generate unique entities CSV from merged results
        unique_entities_csv_path = os.path.join(output_dir, f"all_{extraction_model}_unique_entities.csv")

        # Check if entity merging is already completed
        await _notify("entity_deduplication", "Starting entity deduplication")
        if progress_tracker.is_merging_completed() and os.path.exists(unique_entities_csv_path):
            logger.info(f"✅ Entity merging already completed. Using existing file: {unique_entities_csv_path}")
        else:
            try:
                if use_iterative_dedup:
                    # Use iterative deduplication for better results with large corpora
                    logger.info(f"🔄 Starting ITERATIVE deduplication (max {iterative_dedup_max_rounds} rounds)")
                    logger.info(f"   Output: {unique_entities_csv_path}")

                    # Generate dynamic collection name with process_id
                    from vectordb_utils import generate_collection_name
                    original_collection = generate_collection_name(str(process_id) if process_id else None)

                    unique_entities_csv_path = await run_iterative_deduplication(
                        input_csv_path=merged_csv_path,
                        output_dir=output_dir,
                        original_collection=original_collection,
                        provider=merging_provider,
                        model_name=merging_model,
                        max_rounds=iterative_dedup_max_rounds,
                        stats_tracker=merging_stats,
                        process_id=str(process_id) if process_id else None
                    )
                    logger.info(f"✅ Iterative deduplication completed: {unique_entities_csv_path}")
                else:
                    # Use single-pass deduplication (original behavior)
                    logger.info(f"Generating unique entities CSV at: {unique_entities_csv_path}")
                    await generate_unique_entities_csv(
                        merged_csv_path, unique_entities_csv_path, merging_provider, merging_model,
                        stats_tracker=merging_stats
                    )
                    logger.info(f"Successfully generated unique entities CSV: {unique_entities_csv_path}")

                # Mark merging as completed
                progress_tracker.mark_merging_completed()
            except Exception as e:
                logger.error(f"Failed to generate unique entities CSV: {str(e)}", exc_info=True)
                return {
                    "chunks_csv_files": chunks_csv_files,
                    "results_csv_files": results_csv_files,
                    "merged_results": merged_csv_path,
                    "unique_entities": None,
                    "entity_mapping": None
                }

        try:
            
            # Enrich merged CSV with specified fields
            enriched_csv_path = os.path.join(output_dir, f"all_{extraction_model}_enriched_results.csv")
            enrich_merged_csv_with_fields(
                unique_entities_csv_path=unique_entities_csv_path,
                original_csv_path=merged_csv_path,
                output_csv_path=enriched_csv_path
            )
            logger.info(f"Successfully enriched merged CSV: {enriched_csv_path}")

            # COMMENTED OUT: Relationship aggregation removed in simplified entity extraction
            # agg_relationships_path = os.path.join(output_dir, f"all_{extraction_model}_unique_entities_with_relationships.csv")
            # aggregate_relationships_for_unique_entities(
            #     unique_entities_csv_path=unique_entities_csv_path,
            #     raw_csv_path=merged_csv_path,
            #     output_csv_path=agg_relationships_path
            # )
            # --- NEW STEP: GENERATE HORIZONTAL KEYWORDS ---
            # COMMENTED OUT: Client does not want horizontal keywords currently
            # h_keywords_csv_path = os.path.join(output_dir, f"all_{extraction_model}_unique_entities_with_h_keywords.csv")
            # await process_csv_for_horizontal_keywords(
            #     input_csv_path=unique_entities_csv_path,
            #     output_csv_path=h_keywords_csv_path,
            #     provider=merging_provider, # Using merging model as it's often cheaper/faster for such tasks
            #     model=merging_model,
            #     stats_tracker=horizontal_keywords_stats
            # )
            # logger.info(f"Successfully generated horizontal keywords: {h_keywords_csv_path}")

            # Generate entity mapping CSV
            mapping_csv_path = os.path.join(output_dir, f"all_{extraction_model}_entity_mapping.csv")
            try:
                logger.info(f"Generating entity mapping CSV at: {mapping_csv_path}")
                create_filtered_entity_mapping(merged_csv_path, unique_entities_csv_path, mapping_csv_path)
                logger.info(f"Successfully generated entity mapping CSV: {mapping_csv_path}")

                # Normalization Step
                await _notify("normalization", "Creating normalized entity and reference tables")
                normalized_entities_path = os.path.join(output_dir, f"all_{extraction_model}_entities_normalized.csv")
                normalized_references_path = os.path.join(output_dir, f"all_{extraction_model}_references_locations.csv")
                create_normalized_entity_tables(
                    unique_entities_csv_path=unique_entities_csv_path,
                    raw_results_csv_path=merged_csv_path,
                    output_entities_csv_path=normalized_entities_path,
                    output_references_csv_path=normalized_references_path
                )

                # COMMENTED OUT: Relationship CSV creation removed in simplified entity extraction
                # relationship_csv_path = os.path.join(output_dir, f"all_{extraction_model}_relationships.csv")
                # create_relationship_csv(normalized_entities_path, relationship_csv_path)

                # Print cost summary if tracking was enabled
                if pipeline_tracker is not None:
                    logger.info("\n=== COST TRACKING SUMMARY ===")
                    pipeline_tracker.print_full_summary()

                    # Export cost reports
                    cost_reports_dir = os.path.join(output_dir, "cost_reports")
                    pipeline_tracker.export_all_to_csv(cost_reports_dir)
                    logger.info(f"Cost reports exported to: {cost_reports_dir}/")

                logger.info("=== Pipeline completed successfully ===")
                return {
                    "chunks_csv_files": chunks_csv_files,
                    "results_csv_files": results_csv_files,
                    "merged_results": merged_csv_path,
                    "enriched_results": enriched_csv_path,
                    "unique_entities": unique_entities_csv_path,
                    "entity_mapping": mapping_csv_path,
                    "normalized_entities": normalized_entities_path,
                    "normalized_references": normalized_references_path
                }
            except Exception as e:
                logger.error(f"Failed to generate entity mapping CSV: {str(e)}", exc_info=True)
                return {
                    "chunks_csv_files": chunks_csv_files,
                    "results_csv_files": results_csv_files,
                    "merged_results": merged_csv_path,
                    "unique_entities": unique_entities_csv_path,
                    "entity_mapping": None
                }
        except Exception as e:
            logger.error(f"Failed to generate unique entities CSV: {str(e)}", exc_info=True)
            return {
                "chunks_csv_files": chunks_csv_files,
                "results_csv_files": results_csv_files,
                "merged_results": merged_csv_path,
                "unique_entities": None,
                "entity_mapping": None
            }
    except Exception as e:
        logger.error(f"Failed during final processing steps: {str(e)}", exc_info=True)
        return {
            "chunks_csv_files": chunks_csv_files,
            "results_csv_files": results_csv_files,
            "merged_results": None,
            "unique_entities": None,
            "entity_mapping": None
        }

async def process_existing_csv(csv_path, output_dir, provider, model_name,
                               use_iterative_dedup=True, iterative_dedup_max_rounds=10,
                               process_id=None):
    """
    Process an existing results CSV file starting from Qdrant upload step.

    Args:
        csv_path: Path to the existing results CSV file
        output_dir: Directory to store output CSV files (should be the full path, including date subdir)
        provider: LLM provider ("openai" or "google")
        model_name: Name of the model used (for naming output files)
        use_iterative_dedup: Use iterative deduplication instead of single-pass (default: True)
        iterative_dedup_max_rounds: Max rounds for iterative deduplication (default: 10)
        process_id: Process ID for the pipeline run (used for collection naming)
    """
    logger.info(f"=== Starting processing of existing CSV file ===")
    logger.info(f"CSV file: {csv_path}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Provider: {provider}")
    logger.info(f"Model name: {model_name}")
    
    # Create output directory if it doesn't exist
    try:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Ensured output directory exists: {output_dir}")
    except PermissionError:
        logger.error(f"Permission denied when creating output directory: {output_dir}")
        return None
    except OSError as e:
        logger.error(f"OS error when creating output directory: {str(e)}")
        return None

    document_name = os.path.basename(csv_path).split('_results_raw_')[0]
    
    try:
        # Step 5: Upload to Qdrant VectorDB
        try:
            logger.info(f"Uploading results CSV for {document_name} to Qdrant vector database...")
            await upload_results_csv_to_vectordb(
                csv_path, 
                document_name,
                process_id=str(process_id) if process_id else None
            )
            logger.info(f"Successfully uploaded results to vector database for {document_name}")
        except FileNotFoundError:
            logger.error(f"Results CSV not found during vector database upload: {csv_path}")
            return None
        except Exception as e:
            logger.error(f"Failed to upload {document_name} to Qdrant vector database: {str(e)}", exc_info=True)
            return None

        # Generate unique entities CSV from results
        unique_entities_csv_path = os.path.join(output_dir, f"all_{model_name}_unique_entities.csv")
        try:
            if use_iterative_dedup:
                # Use iterative deduplication for better results
                logger.info(f"🔄 Starting ITERATIVE deduplication (max {iterative_dedup_max_rounds} rounds)")
                from vectordb_utils import generate_collection_name
                original_collection = generate_collection_name(str(process_id) if process_id else None)
                unique_entities_csv_path = await run_iterative_deduplication(
                    input_csv_path=csv_path,
                    output_dir=output_dir,
                    original_collection=original_collection,
                    provider=provider,
                    model_name=model_name,
                    max_rounds=iterative_dedup_max_rounds,
                    process_id=str(process_id) if process_id else None
                )
                logger.info(f"✅ Iterative deduplication completed: {unique_entities_csv_path}")
            else:
                logger.info(f"Generating unique entities CSV at: {unique_entities_csv_path}")
                await generate_unique_entities_csv(csv_path, unique_entities_csv_path, provider, model_name)
                logger.info(f"Successfully generated unique entities CSV: {unique_entities_csv_path}")
            
            # Generate entity mapping CSV
            mapping_csv_path = os.path.join(output_dir, f"all_{model_name}_entity_mapping.csv")
            try:
                logger.info(f"Generating entity mapping CSV at: {mapping_csv_path}")
                create_filtered_entity_mapping(csv_path, unique_entities_csv_path, mapping_csv_path)
                logger.info(f"Successfully generated entity mapping CSV: {mapping_csv_path}")
                
                logger.info("=== Pipeline completed successfully ===")
                return {
                    "results_csv": csv_path,
                    "unique_entities": unique_entities_csv_path,
                    "entity_mapping": mapping_csv_path
                }
            except Exception as e:
                logger.error(f"Failed to generate entity mapping CSV: {str(e)}", exc_info=True)
                return {
                    "results_csv": csv_path,
                    "unique_entities": unique_entities_csv_path,
                    "entity_mapping": None
                }
        except Exception as e:
            logger.error(f"Failed to generate unique entities CSV: {str(e)}", exc_info=True)
            return {
                "results_csv": csv_path,
                "unique_entities": None,
                "entity_mapping": None
            }
    except Exception as e:
        logger.error(f"Failed during final processing steps: {str(e)}", exc_info=True)
        return {
            "results_csv": csv_path,
            "unique_entities": None,
            "entity_mapping": None
        }


if __name__ == "__main__":
    try:
        # Prompt user for file type
        file_type = input("Enter file type to process (pdf/xml): ").strip().lower()
        if file_type not in ["pdf", "xml"]:
            logger.error("Invalid file type. Please enter 'pdf' or 'xml'.")
            sys.exit(1)

        # Prompt user for input directory
        if file_type == "pdf":
            default_input_dir = "pdfs"
        else:
            default_input_dir = "xmls"

        input_dir = input(f"Enter input directory (default: {default_input_dir}): ").strip()
        if not input_dir:
            input_dir = default_input_dir

        # Prompt user for provider and model name
        extraction_provider = input("Enter LLM provider for entity extraction (openai/google): ").strip().lower()
        if extraction_provider not in ["openai", "google"]:
            logger.error("Invalid provider. Please enter 'openai' or 'google'.")
            sys.exit(1)
        extraction_model = input("Enter model name for entity extraction (e.g., 'gpt-4.1'): ").strip()
        if not extraction_model:
            logger.error("Extraction model name cannot be empty.")
            sys.exit(1)

        merging_provider = input("Enter LLM provider for entity merging (openai/google): ").strip().lower()
        if merging_provider not in ["openai", "google"]:
            logger.error("Invalid provider. Please enter 'openai' or 'google'.")
            sys.exit(1)
        merging_model = input("Enter model name for entity merging (e.g., 'gpt-4.1-mini'): ").strip()
        if not merging_model:
            logger.error("Merging model name cannot be empty.")
            sys.exit(1)

        # Define settings
        base_output_directory = "results"

        # Check for existing incomplete run to resume
        existing_runs = []
        if os.path.exists(base_output_directory):
            for run_dir in sorted(os.listdir(base_output_directory), reverse=True):
                run_path = os.path.join(base_output_directory, run_dir)
                progress_file = os.path.join(run_path, ".progress", "extraction_progress.json")
                merging_file = os.path.join(run_path, ".progress", "merging_progress.json")

                # Check if this run has progress but is not completed
                if os.path.isdir(run_path) and (os.path.exists(progress_file) or os.path.exists(merging_file)):
                    # Check if merging is completed
                    merging_completed = False
                    if os.path.exists(merging_file):
                        try:
                            import json
                            with open(merging_file, 'r') as f:
                                merging_data = json.load(f)
                                merging_completed = merging_data.get('completed', False)
                        except:
                            pass

                    # If merging is not completed, this is an incomplete run
                    if not merging_completed:
                        existing_runs.append(run_path)

        # Use existing incomplete run or create new one
        if existing_runs:
            output_directory = existing_runs[0]
            logger.info(f"\n🔄 RESUMING EXISTING RUN")
            logger.info(f"Found incomplete run at: {output_directory}")
        else:
            # Create a subdirectory with today's date (YYYY-MM-DD)
            today_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_directory = os.path.join(base_output_directory, today_str)
            logger.info(f"\n=== STARTING NEW {file_type.upper()} PROCESSING PIPELINE ===")

        logger.info(f"File Type: {file_type.upper()}")
        logger.info(f"Input Directory: {input_dir}")
        logger.info(f"Output Directory: {output_directory}")
        logger.info(f"Extraction Provider: {extraction_provider}")
        logger.info(f"Extraction Model: {extraction_model}")
        logger.info(f"Merging Provider: {merging_provider}")
        logger.info(f"Merging Model: {merging_model}")

        results = asyncio.run(process_document_directory(
            input_dir=input_dir,
            output_dir=output_directory,
            file_type=file_type,
            extraction_provider=extraction_provider,
            extraction_model=extraction_model,
            merging_provider=merging_provider,
            merging_model=merging_model,
            used_llamaparse=(file_type == "pdf"),  # Only use llamaparse for PDFs
            enable_cost_tracking=True
        ))
        
        if results:
            logger.info("\n=== PROCESSING SUMMARY ===")
            logger.info(f"Processed {file_type.upper()} files: {len(results['results_csv_files'])}")
            logger.info(f"Generated files:")
            logger.info(f"- Chunks CSV files: {len(results['chunks_csv_files'])}")
            for csv_file in results['chunks_csv_files']:
                logger.info(f"  * {os.path.basename(csv_file)}")
            logger.info(f"- Results CSV files: {len(results['results_csv_files'])}")
            for csv_file in results['results_csv_files']:
                logger.info(f"  * {os.path.basename(csv_file)}")
            
            if results['merged_results']:
                logger.info(f"- Merged results: {os.path.basename(results['merged_results'])}")
            else:
                logger.warning("- Merged results: Failed to generate")
                
            if results['unique_entities']:
                logger.info(f"- Unique entities: {os.path.basename(results['unique_entities'])}")
            else:
                logger.warning("- Unique entities: Failed to generate")

            if results['entity_mapping']:
                logger.info(f"- Entity mapping: {os.path.basename(results['entity_mapping'])}")
            else:
                logger.warning("- Entity mapping: Failed to generate")

            if results.get('normalized_entities'):
                logger.info(f"- Normalized entities: {os.path.basename(results['normalized_entities'])}")
            if results.get('normalized_references'):
                logger.info(f"- Normalized references: {os.path.basename(results['normalized_references'])}")
        else:
            logger.error("Pipeline failed to complete successfully - no results returned.")
        
        logger.info("\n=== PIPELINE EXECUTION COMPLETE ===")
    except KeyboardInterrupt:
        logger.warning("Pipeline execution interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Pipeline failed with unexpected error: {str(e)}", exc_info=True)
        sys.exit(1)

