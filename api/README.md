# Borges Knowledge Graph API

FastAPI-based REST API for running the Borges Knowledge Graph extraction pipeline.

## Features

- **Pipeline Execution**: Upload multiple PDF or XML files for knowledge graph extraction
- **Status Monitoring**: Real-time pipeline status with detailed step visibility
- **File Downloads**: Download final outputs via S3 presigned URLs
- **Prompt Management**: View, update, and version the entity extraction prompt
- **Fully Async**: Non-blocking endpoints and database operations

## Quick Start

### 1. Install Dependencies

```bash
cd api
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

### 3. Create Database Tables

Execute the SQL statements from [fastapi_layer_for_pipeline.md](../fastapi_layer_for_pipeline.md) to create the required tables:

- `pipeline_runs`
- `input_files`
- `pipeline_status_updates`
- `extraction_prompts`

### 4. Run the API

```bash
# Development mode with auto-reload
python main.py

# Or use uvicorn directly
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

- Swagger UI docs: `http://localhost:8000/api/v1/docs`
- ReDoc: `http://localhost:8000/api/v1/redoc`

## API Endpoints

### Pipeline Management

- `POST /api/v1/pipeline/start` - Start a new pipeline run with file uploads
- `GET /api/v1/pipeline/{process_id}/status` - Get pipeline status
- `GET /api/v1/pipeline/{process_id}/files` - Get download URLs for outputs
- `GET /api/v1/pipeline/runs` - List all pipeline runs (with pagination)

### Prompt Management

- `GET /api/v1/prompts/extraction` - Get active extraction prompt
- `PUT /api/v1/prompts/extraction` - Update extraction prompt (creates new version)
- `GET /api/v1/prompts/extraction/history` - Get prompt version history
- `GET /api/v1/prompts/extraction/{version}` - Get specific prompt version
- `POST /api/v1/prompts/extraction/{version}/activate` - Activate a prompt version
- `GET /api/v1/prompts/extraction/default` - Get default built-in prompt

### Health & Configuration

- `GET /api/v1/health` - Health check
- `GET /api/v1/health/config` - Get API configuration
- `GET /api/v1/ping` - Simple ping (no auth required)

## Authentication

All endpoints (except `/ping`) require an API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/api/v1/health
```

## Example Usage

### Start a Pipeline Run

```bash
curl -X POST "http://localhost:8000/api/v1/pipeline/start" \
  -H "X-API-Key: your-api-key" \
  -F "files=@document1.pdf" \
  -F "files=@document2.pdf" \
  -F "files=@document3.pdf"
```

Response:
```json
{
  "process_id": "123e4567-e89b-12d3-a456-426614174000",
  "current_step": "pending",
  "message": "Pipeline started successfully. Processing 3 files.",
  "created_at": "2026-01-30T10:00:00Z",
  "files": [...]
}
```

### Check Pipeline Status

```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:8000/api/v1/pipeline/123e4567-e89b-12d3-a456-426614174000/status"
```

### Get Download URLs

```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:8000/api/v1/pipeline/123e4567-e89b-12d3-a456-426614174000/files"
```

### Update Extraction Prompt

```bash
curl -X PUT "http://localhost:8000/api/v1/prompts/extraction" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_content": "Your new prompt content here...",
    "change_notes": "Updated category definitions",
    "activate_immediately": true
  }'
```

## Architecture

```
api/
├── main.py                 # FastAPI app initialization
├── config.py               # Settings (Pydantic BaseSettings)
├── database.py             # SQLAlchemy/asyncpg setup
├── dependencies.py         # API key verification
├── models/                 # SQLAlchemy models
│   ├── pipeline.py
│   └── prompt.py
├── schemas/                # Pydantic request/response schemas
│   ├── pipeline.py
│   └── prompt.py
├── routers/                # API endpoints
│   ├── pipeline.py
│   ├── prompts.py
│   └── health.py
└── services/               # Business logic
    ├── pipeline_runner.py  # Background task runner
    ├── prompt_service.py   # Prompt CRUD operations
    └── s3_service.py       # S3 upload/presign operations
```

## Pipeline Steps

The pipeline progresses through these steps:

1. `pending` - Waiting to start
2. `text_extraction` - Extracting text from PDF/XML
3. `entity_extraction` - LLM entity extraction
4. `vector_indexing` - Uploading to Qdrant
5. `csv_merging` - Merging CSV files
6. `entity_deduplication` - Iterative deduplication
7. `normalization` - Creating normalized tables
8. `uploading_results` - Uploading to S3
9. `completed` - Successfully finished
10. `failed` - Pipeline failed

## Output Files

Only 2 files are stored in S3 per pipeline run:

1. `unique_entities.csv` - Deduplicated unique entities
2. `references.csv` - Entity reference locations

## Development

### Running Tests

```bash
# TODO: Add tests
pytest
```

### Code Style

```bash
# Format code
black api/

# Lint
ruff check api/
```

## Deployment

### Production Considerations

1. **Environment Variables**: Use secure secret management (AWS Secrets Manager, etc.)
2. **Database**: Use production PostgreSQL with connection pooling
3. **S3**: Configure proper bucket policies and lifecycle rules
4. **Monitoring**: Add monitoring and alerting (Prometheus, Datadog, etc.)
5. **Rate Limiting**: Add rate limiting middleware
6. **HTTPS**: Use HTTPS in production (nginx, ALB, etc.)

### Docker Deployment

```dockerfile
# TODO: Add Dockerfile
```

### Kubernetes Deployment

```yaml
# TODO: Add K8s manifests
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**: Check `DATABASE_URL` in `.env`
2. **S3 Upload Failures**: Verify AWS credentials and bucket permissions
3. **API Key Errors**: Ensure `X-API-Key` header is set correctly
4. **File Upload Limits**: Check `MAX_FILE_SIZE_MB` and `MAX_FILES_PER_REQUEST`

### Logs

Logs are written to the `logs/` directory with daily rotation:
- Format: `logs/borges_YYYY-MM-DD.log`

## License

Same as parent project.
