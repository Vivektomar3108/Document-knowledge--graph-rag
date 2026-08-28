### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables in .env file:
# OPENAI_API_KEY=your_openai_api_key
# GOOGLE_API_KEY=your_google_api_key  
# LANGCHAIN_API_KEY=your_langchain_api_key
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_PROJECT=Borges Knowledge Graph
# QDRANT_API_KEY=your_qdrant_api_key
```

### Running the Pipeline
```bash
# Main pipeline execution (processes all PDFs in pdfs/ directory)
python main.py

# Process existing CSV files (starts from Qdrant upload step)
python process_csv.py

# Run normalization utilities
python run_normalization.py
```

### Testing
No formal test suite is configured. Test functionality by running the pipeline with sample PDF files.

## Architecture

### Core Pipeline Flow
The system implements a 8-step knowledge graph extraction pipeline:

1. **PDF Loading** (`pdf_utils.py`) - Extract text from PDF documents
2. **Text Chunking** (`knowledgegraph.py`) - Split text using RecursiveCharacterTextSplitter (8000 chars, 300 overlap)
3. **Entity Extraction** (`knowledgegraph.py`) - LLM-based structured extraction using Pydantic schemas
4. **CSV Generation** (`csv_utils.py`) - Generate chunks and results CSV files
5. **Vector Database Upload** (`vectordb_utils.py`) - Upload to Qdrant with embeddings
6. **Results Merging** (`csv_utils.py`) - Combine multiple document results
7. **Entity Deduplication** (`entity_utils.py`) - LLM-based entity merging and normalization
8. **Relationship Mapping** (`mapping_entity_csv_utils.py`) - Generate entity relationship mappings

### Key Components

**LLM Integration**: Supports both OpenAI (GPT-4.1, GPT-4.1-mini) and Google (Gemini) models through LangChain with structured output using Pydantic schemas (`schemas.py`). The system uses temperature=0.4 for consistent results.

**Entity Schema**: Defines structured entity extraction with `BorgesEntity`, `Reference`, `Relationship`, and `IndirectReference` models. Entities are normalized with specific naming conventions (e.g., "Last Name, First Name (Birth Year - Death Year)" for people).

**Chunking Strategy**: Uses character-based splitting with semantic chunking option available. Default: 8000 characters with 300 character overlap for context preservation.

**Vector Database**: Integrates with Qdrant for semantic search capabilities. Batch processing with configurable batch sizes (default: 50).

**Entity Deduplication**: Two-stage process using vector similarity search followed by LLM-based reasoning to merge duplicate entities across documents.

### File Organization

- `main.py` - Pipeline orchestration and execution
- `knowledgegraph.py` - Core text processing and LLM entity extraction
- `schemas.py` - Pydantic models for structured extraction
- `prompts.py` - LLM prompts and few-shot examples
- `*_utils.py` - Specialized utilities for PDF, CSV, vector DB, entities, normalization, and mapping
- `pdfs/` - Input directory for PDF files
- `results/` - Output directory with date-based subdirectories

### Configuration

Model selection is done at runtime via user input. The system supports:
- OpenAI: gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini
- Google: gemini-2.5-pro-preview, gemini-2.5-flash-preview variants

Output files follow naming convention: `{document_name}_{file_type}_{model_name}.csv`

### Logging

Centralized logging system using `logger.py`:
- Day-wise log files stored in `logs/` directory with format `borges_YYYY-MM-DD.log`
- Detailed logging with module name, function name, and line numbers for file logs
- Console output with simplified format
- All modules use the centralized logger via `from logger import setup_logger` or `get_logger`

Usage in new files:
```python
from logger import setup_logger
logger = setup_logger(__name__)
```