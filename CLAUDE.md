# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables in .env file:
# OPENAI_API_KEY=your_openai_api_key
# BACKUP_OPENAI_API_KEY=your_backup_openai_api_key  # For rate limit failover
# GOOGLE_API_KEY=your_google_api_key
# LANGCHAIN_API_KEY=your_langchain_api_key
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_PROJECT=Borges Knowledge Graph
# QDRANT_API_KEY=your_qdrant_api_key
# QDRANT_URL=your_qdrant_url
# NEW_QDRANT_URL=your_new_qdrant_url  # For migration
# NEW_QDRANT_API_KEY=your_new_qdrant_api_key  # For migration
```

### Running the Pipeline
```bash
# Main pipeline execution (processes all PDFs and XMLs)
python main.py

# Process existing CSV files (starts from Qdrant upload step)
python process_csv.py

# Run iterative deduplication standalone
python iterative_dedup.py

# Test pipeline with specific components
python test_main.py
python unique_entities_pipeline_test.py
python test_iterative_dedup.py
python test_progress_sync.py
python test_name_normalization.py

# Diagnostic utilities
python diagnose_duplicates.py
python debug_pending_calculation.py
```

### Testing
No formal test suite is configured. Test functionality by running the pipeline with sample PDF files placed in the `pdfs/` directory.

## Architecture

### Core Pipeline Flow
The system implements a simplified knowledge graph extraction pipeline focused on Jorge Luis Borges' corpus:

1. **Document Loading** (`pdf_utils.py`, `xml_utils.py`) - Extract text from PDF (using LlamaParse) and XML documents
2. **Text Chunking & Entity Extraction** (`knowledgegraph.py`) - Split text using RecursiveCharacterTextSplitter (8000 chars, 300 overlap) and extract entities with LLM
3. **CSV Generation** (`csv_utils.py`) - Generate chunks and raw results CSV files
4. **Vector Database Upload** (`vectordb_utils.py`) - Upload to Qdrant with hybrid embeddings (dense, BM25, ColBERT)
5. **CSV Merging** (`csv_utils.py`) - Merge individual result CSVs into single merged file
6. **Iterative Entity Deduplication** (`iterative_dedup.py`) - Multi-round deduplication with convergence detection
7. **CSV Enrichment** (`enrich_csv.py`) - Enrich merged CSV with additional metadata fields
8. **Entity Mapping & Normalization** (`mapping_entity_csv_utils.py`) - Generate relationship mappings and normalized entity tables

**Note**: Horizontal keywords generation and relationship aggregation are currently commented out per client request.

### Key Components

**LLM Integration**: Supports both OpenAI (GPT-4.1, GPT-4.1-mini, GPT-4.1-nano, GPT-4o variants) and Google (Gemini) models through LangChain with structured output using Pydantic schemas. The system uses temperature=1.0 for structured output generation. Includes advanced retry logic with exponential backoff, API key failover for rate limit handling, and comprehensive cost tracking.

**Entity Schema**: Defines structured entity extraction with specialized Borges-focused models:
- `BorgesEntity` - Core entity with normalized naming, categorization, and vertical keywords
- `Reference` - Direct quotes/paraphrases from source chunks
- `Relationship` - Typed relationships between entities (prioritizing Borges connections)
- `IndirectReference` - Contextually derived entity relationships

**Entity Classification**: Hierarchical categorization system with 9 major categories (Literature/Arts, Borges's Work, History/Politics, Places, Biography, Symbols/Metaphors, Philosophical Themes, Science/Math, Fiction) and specific sub-categories for precise classification.

**Chunking Strategy**: Character-based splitting with semantic chunking option. Default: 8000 characters with 300 character overlap for context preservation.

**XML Processing Support**: Full support for XML documents alongside PDFs:
- Parses XML files with proper encoding (latin-1)
- Extracts metadata from XML attributes (nombre, año_pub, genero)
- Caches parsed content to `parsed_xml_content/` directory
- Cost tracking for XML processing

**Iterative Deduplication System**: Multi-round entity deduplication with convergence detection:
- Processes entities across multiple rounds (default: 10 max rounds)
- Stops automatically when no new merges occur (convergence detection)
- Uses dual collection architecture (original preserved, working updated)
- Full checkpoint/resume support at round level
- Tracks merge lineage to understand entity merge history
- Column normalization between rounds for compatibility

**Progress Tracking System** (`progress_tracker.py`): Document-level processing tracker with three stages:
- `extraction_completed`: Documents fully extracted and uploaded to Qdrant
- `vectordb_completed`: Documents uploaded to vector database
- `merging_completed`: Entity merging phase finished
- Auto-syncs with CSVs to validate progress
- Enables resume capability distinguishing extraction vs merging phases
- Includes disk space monitoring (95% threshold warning, <1GB stops execution)

**Persistent Entity ID Tracking** (`persistent_entity_tracker.py`): Real-time entity ID persistence:
- Saves every entity ID to disk immediately upon processing
- Uses atomic writes (temp file + rename) to prevent corruption
- Thread-safe with locks for concurrent access
- Zero data loss between checkpoints
- JSON storage format with sorted entity IDs and timestamps

**Entity Merging Checkpoints** (`entity_checkpoint.py`): Comprehensive checkpoint management:
- Saves merging state, processed entity IDs, progress percentage
- Batch output saves every N entities
- Resume from exact point of interruption
- Automatically clears stale checkpoints when merged CSV is rebuilt

**Cost Tracking System** (`cost_tracking_utils.py`): Token usage and cost monitoring:
- Tracks token usage per pipeline stage (extraction, merging, validation)
- Current pricing for gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o variants
- Records prompt tokens, completion tokens, cost, and context per call
- Generates CSV cost reports per stage in `cost_reports/` subdirectory

**Vector Database**: Integrates with Qdrant for semantic search with hybrid embeddings:
- **Dense embeddings**: Paraphrase-MultiLingual-MPNet-Base-V2 (768 dimensions)
- **BM25 embeddings**: Sparse vectors with IDF modifier
- **ColBERT embeddings**: Late interaction with 128-dimensional multivectors
- Lazy loading of embedding models for memory optimization
- Query enhancement with two-tier filtering (exact name + type match)
- Batch processing with configurable sizes (default: 50)
- Garbage collection after batch uploads

**Error Handling & Resilience**:
- Advanced retry logic with exponential backoff and jitter
- Distinction between retryable (rate limits, timeouts) and non-retryable errors (auth, invalid requests)
- API key failover: Primary and backup OpenAI keys with automatic switching
- 5 consecutive failure limit: Pipeline stops if 5 documents fail in a row
- Graceful degradation: Continues processing on individual entity failures

### File Organization

**Core Pipeline Files:**
- `main.py` - Pipeline orchestration with progress tracking, checkpointing, and resume capability
- `knowledgegraph.py` - Core text processing and LLM entity extraction
- `process_csv.py` - Process existing CSV files starting from Qdrant upload
- `iterative_dedup.py` - Multi-round iterative entity deduplication with convergence detection

**Schema and Prompts:**
- `schemas/entity_extraction_schema.py` - Pydantic models for structured extraction
- `schemas/entity_merging_schema.py` - Models for entity deduplication
- `schemas/horizontal_keyword_schema.py` - Models for keyword enrichment
- `schemas/description_validation_schema.py` - Models for entity description validation
- `prompts/entity_extraction_prompt.py` - Comprehensive extraction prompts with detailed guidelines
- `prompts/entity_merging_prompt.py` - Entity deduplication prompts
- `prompts/horizontal_keywords_prompt.py` - Keyword enrichment prompts
- `prompts/description_validation_prompts.py` - Description validation prompts

**Utility Modules:**
- `pdf_utils.py` - PDF text extraction with LlamaParse and metadata handling
- `xml_utils.py` - XML text extraction, parsing, and caching
- `csv_utils.py` - CSV file generation, merging, and metadata operations
- `vectordb_utils.py` - Qdrant operations with hybrid embeddings (dense, BM25, ColBERT)
- `entity_utils.py` - Entity deduplication with retry logic, API key failover, and cost tracking
- `entity_checkpoint.py` - Entity merging checkpoint management for resume capability
- `persistent_entity_tracker.py` - Real-time persistent entity ID tracking with atomic writes
- `progress_tracker.py` - Document-level progress tracking with disk space monitoring
- `cost_tracking_utils.py` - Token usage and cost tracking across pipeline stages
- `mapping_entity_csv_utils.py` - Entity relationship mapping
- `normalization_utils.py` - Entity normalization utilities
- `description_validation_utils.py` - Entity description validation
- `relationship_utils.py` - Relationship processing
- `relationship_aggregation_utils.py` - Relationship aggregation for unique entities
- `horizontal_keywords_utils.py` - Horizontal keyword processing
- `enrich_csv.py` - CSV enrichment with additional fields
- `llm_utils.py` - LLM provider abstractions

**Testing and Diagnostic Utilities:**
- `test_main.py` - Pipeline testing
- `test_iterative_dedup.py` - Iterative deduplication testing
- `test_progress_sync.py` - Progress tracking testing
- `test_name_normalization.py` - Name normalization testing
- `unique_entities_pipeline_test.py` - Entity extraction testing
- `diagnose_duplicates.py` - Diagnostic tool for duplicate entity analysis
- `debug_pending_calculation.py` - Debugging tool for pending entity calculations
- `run_normalization.py` - Standalone normalization execution
- `logger.py` - Centralized logging configuration

**Input/Output Directories:**
- `pdfs/` - Input directory for PDF files
- `xmls/` or root - Input directory for XML files
- `results/` - Output directory with timestamped subdirectories
- `logs/` - Daily log files with format `borges_YYYY-MM-DD.log`
- `parsed_pdf_content/` - Cached PDF text content
- `parsed_xml_content/` - Cached XML text content
- `temporary_unique_files/` - Checkpoint storage for entity merging and iterative dedup
  - `iterative_dedup_*/` - Per-session deduplication checkpoints
  - `round_outputs/` - Output from each deduplication round
  - `merge_history/` - Merge lineage tracking files
  - `checkpoints/` - Round-specific checkpoint files
  - `processed_entity_ids.json` - Persistent entity ID tracker
- `cost_reports/` - Token usage and cost analysis reports
- `sample_xmls/` - Sample XML files for testing
- `partial_graph_processing/` - Partial processing artifacts

**Documentation Files:**
- `CLAUDE.md` - Project guidance for Claude Code (this file)
- `CHECKPOINT_MISMATCH_FIX.md` - Checkpoint clearing on merged CSV rebuild
- `PERSISTENT_TRACKER_IMPLEMENTATION.md` - Persistent tracking system details
- `NAME_NORMALIZATION_FIX.md` - Entity name normalization fixes
- `CRITICAL_FIX.md` - Critical bug fixes documentation
- `QUICK_START.md` - Quick start guide
- `RECOVERY_GUIDE.md` - Recovery procedures for pipeline failures
- `QDRANT_MIGRATION_GUIDE.md` - Qdrant collection migration steps
- `Description_Validation_Approach.md` - Description validation approach documentation

### Configuration

**Model Selection**: Done at runtime via user input prompts. The system supports:
- OpenAI: gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini
- Google: gemini-2.5-pro-preview, gemini-2.5-flash-preview variants

**Processing Parameters** (configured in `main.py`):
- `used_llamaparse` (default: True) - Use LlamaParse for PDF extraction
- `enable_cost_tracking` (default: True) - Track token usage and costs
- `use_iterative_dedup` (default: True) - Use multi-round deduplication
- `iterative_dedup_max_rounds` (default: 10) - Maximum deduplication rounds
- `chunk_size` (default: 8000) - Character count per text chunk
- `chunk_overlap` (default: 300) - Character overlap between chunks
- `batch_size` (default: 50) - Batch size for Qdrant uploads

**Output File Naming**: `{document_name}_{file_type}_{model_name}.csv`

**Environment Variables**: All API keys and configuration stored in `.env` file (not committed to repo):
- `OPENAI_API_KEY` - Primary OpenAI API key
- `BACKUP_OPENAI_API_KEY` - Backup key for rate limit failover
- `GOOGLE_API_KEY` - Google/Gemini API key
- `LANGCHAIN_API_KEY` - LangChain tracing key
- `LANGCHAIN_TRACING_V2` - Enable LangChain tracing
- `LANGCHAIN_PROJECT` - LangChain project name
- `QDRANT_API_KEY` - Qdrant cloud API key
- `QDRANT_URL` - Qdrant instance URL
- `NEW_QDRANT_URL` - New Qdrant instance URL (for migration)
- `NEW_QDRANT_API_KEY` - New Qdrant API key (for migration)

### Logging

Centralized logging system using `logger.py`:
- Day-wise log files stored in `logs/` directory with format `borges_YYYY-MM-DD.log`
- Detailed logging with module name, function name, and line numbers for file logs
- Console output with simplified format
- All modules use the centralized logger via `from logger import setup_logger`

Usage in new files:
```python
from logger import setup_logger
logger = setup_logger(__name__)
```

### Processing Flow Details

**Document Processing Pipeline**: The system processes PDF and XML documents through a sophisticated NLP pipeline that:
1. **Document Loading**: Extracts text from PDFs (using LlamaParse) and XML files with metadata
2. **Text Chunking**: Splits documents into 8000-character chunks with 300-character overlap
3. **Entity Extraction**: LLM-based extraction with maximum recall, hierarchical Borges-specific classification
4. **CSV Generation**: Creates individual chunk and result CSVs per document
5. **Vector Upload**: Uploads to Qdrant with hybrid embeddings (dense, BM25, ColBERT)
6. **CSV Merging**: Combines all document results into single merged CSV
7. **Iterative Deduplication**: Multi-round entity merging with convergence detection:
   - Round 1: Initial deduplication across all entities
   - Rounds 2-N: Continue until convergence (no new merges)
   - Updates working Qdrant collection after each round
   - Tracks merge lineage for entity provenance
8. **CSV Enrichment**: Adds metadata fields to merged results
9. **Normalization**: Creates normalized entity and reference tables

**Resume/Restart Capability**: The pipeline supports interruption and resumption at multiple levels:
- **Document-level**: Skips already processed documents based on progress tracker
- **Extraction vs Merging**: Can pause between extraction and merging phases
- **Deduplication Rounds**: Can resume within a specific deduplication round
- **Entity-level**: Checkpoints save processed entity IDs for fine-grained resume

**Progress Tracking**: Three-stage tracking system:
1. `extraction_completed`: Document extracted and CSV generated
2. `vectordb_completed`: Vectors uploaded to Qdrant
3. `merging_completed`: Entity merging finished for session

**Checkpoint Management**:
- Persistent entity ID tracker: Real-time saves to prevent data loss
- Entity merging checkpoints: Resume from exact point of interruption
- Iterative dedup checkpoints: Per-round state and merge history
- Automatic checkpoint clearing when source data (merged CSV) is rebuilt

**Error Handling Strategy**:
- Exponential backoff with jitter for rate limits
- API key failover for continued processing
- 5 consecutive failure limit to prevent infinite loops
- Distinction between retryable and non-retryable errors
- Graceful degradation on individual entity failures

**Output Structure**: Each run creates a timestamped directory in `results/` containing:
- `{doc}_chunks_{model}.csv` - Individual document chunks
- `{doc}_results_{model}.csv` - Individual document entity extraction results
- `all_{model}_merged_results.csv` - Merged results across all documents
- `all_{model}_enriched_results.csv` - Enriched merged results with metadata
- `all_{model}_entities_normalized.csv` - Normalized entity table
- `all_{model}_references_locations.csv` - Reference location mappings
- `cost_reports/` subdirectory with token usage and cost analysis
- `temporary_unique_files/` with checkpoints and deduplication artifacts

**Iterative Deduplication Output**: Located in `temporary_unique_files/iterative_dedup_{timestamp}/`:
- `round_outputs/round_{N}_merged.csv` - Output from each round
- `merge_history/round_{N}_merges.json` - Merge decisions per round
- `checkpoints/round_{N}_checkpoint.json` - Round-specific state
- `convergence_report.txt` - Statistics and convergence analysis

### Key Architectural Improvements

**1. Dual Document Support**: Unified pipeline for both PDF and XML documents with format-specific parsers and metadata extraction.

**2. Multi-Round Deduplication**: Replaced single-pass entity merging with iterative deduplication that continues until convergence, significantly improving entity consolidation quality.

**3. Comprehensive Checkpointing**: Multiple checkpoint layers (document-level, entity-level, round-level) enable resume from any interruption point without data loss.

**4. Real-Time Persistence**: Persistent entity ID tracker saves every processed entity immediately, eliminating data loss windows between bulk checkpoints.

**5. Resource Management**:
- Lazy loading of embedding models reduces memory footprint
- Disk space monitoring prevents pipeline failures from storage issues
- Garbage collection after batch uploads optimizes memory usage

**6. Resilience & Recovery**:
- API key failover for rate limit handling
- Advanced retry logic distinguishes transient vs permanent failures
- 5 consecutive failure limit prevents infinite loops
- Graceful degradation on individual entity failures

**7. Cost Transparency**: Comprehensive token usage and cost tracking across all pipeline stages with detailed CSV reports.

**8. Progress Observability**: Three-stage progress tracking with detailed logging, emoji-based status visualization, and sync validation against actual CSVs.

**9. Dual Qdrant Collections**: Maintains original collection while updating working collection during deduplication, enabling rollback and comparison.

**10. Hybrid Vector Search**: Three embedding types (dense, BM25, ColBERT) provide comprehensive semantic and keyword-based entity matching.

### Recent Bug Fixes & Improvements

**Critical Fixes**:
- **Checkpoint Mismatch**: Automatically clears stale entity merging checkpoints when merged CSV is rebuilt
- **Empty Entity Handling**: Gracefully handles cases with no processed entities
- **Name Normalization**: Fixed entity name normalization to handle edge cases
- **Column Compatibility**: Ensures column normalization between deduplication rounds

**Performance Optimizations**:
- Lazy model loading reduces startup time and memory usage
- Batch processing with garbage collection prevents memory leaks
- Efficient checkpoint design minimizes I/O overhead

**User Experience**:
- Clear progress indication with emoji-based status updates
- Detailed error messages with recovery suggestions
- Cost reporting for budget management
- Resume capability reduces wasted computation on interruptions

### Common Workflows

**Fresh Pipeline Run**:
1. Place PDF/XML files in `pdfs/` directory or root
2. Run `python main.py`
3. Select model when prompted
4. Pipeline processes all documents, uploads to Qdrant, and performs iterative deduplication
5. Results saved in `results/{timestamp}/` directory

**Resuming After Interruption**:
1. Run `python main.py` again
2. Pipeline detects incomplete run and offers resume options:
   - Resume extraction: Continues processing unfinished documents
   - Resume merging: Skips extraction, continues with entity deduplication
3. Uses checkpoints to continue from exact interruption point

**Processing Existing CSVs**:
1. Place CSV files in appropriate results directory
2. Run `python process_csv.py`
3. Starts from Qdrant upload step, skipping extraction

**Running Iterative Deduplication Standalone**:
1. Ensure merged CSV exists in results directory
2. Run `python iterative_dedup.py`
3. Specify max rounds and collection names
4. Monitor convergence in round outputs

**Cost Analysis**:
1. After pipeline run, check `cost_reports/` subdirectory in results
2. Review token usage and costs per stage
3. Use for budget planning and model selection

**Diagnostics**:
- Run `python diagnose_duplicates.py` to analyze duplicate entities
- Run `python debug_pending_calculation.py` to investigate pending calculations
- Check logs in `logs/borges_YYYY-MM-DD.log` for detailed execution traces

### Troubleshooting

**Pipeline Fails to Start**:
- Check `.env` file has all required API keys
- Verify disk space (minimum 1GB free required)
- Check logs for specific error messages

**Rate Limit Errors**:
- Set `BACKUP_OPENAI_API_KEY` in `.env` for automatic failover
- Pipeline will automatically switch to backup key
- Monitor cost reports to track usage across keys

**Checkpoint Issues**:
- If checkpoint appears stale, pipeline automatically clears when merged CSV is rebuilt
- Manually delete `temporary_unique_files/` directory to clear all checkpoints
- Check `progress_tracker.py` logs for sync validation messages

**Deduplication Not Converging**:
- Check `convergence_report.txt` in iterative_dedup output directory
- Increase `iterative_dedup_max_rounds` if needed
- Review merge history JSONs to understand merge decisions

**Memory Issues**:
- Reduce `batch_size` in main.py
- Clear embedding models between batches (automatically done)
- Process fewer documents per run

### Best Practices

1. **Backup Strategy**: Keep original collection in Qdrant; work with copies during deduplication
2. **Cost Management**: Enable cost tracking, monitor reports, use appropriate model tiers
3. **Incremental Processing**: Process documents in batches if dealing with large corpus
4. **Checkpoint Hygiene**: Let pipeline manage checkpoints automatically; manual clearing only when needed
5. **Model Selection**: Use gpt-4.1-mini for initial runs, gpt-4.1 for production quality
6. **Resume Points**: Prefer resuming at phase boundaries (after extraction, before merging) for cleaner state
7. **Monitoring**: Check logs regularly for warnings about disk space, rate limits, or errors
8. **Testing**: Use sample documents in `sample_xmls/` to test pipeline before full runs