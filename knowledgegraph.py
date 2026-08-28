from typing import List, Dict, Any, Optional, Tuple
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
import random
import asyncio
from dotenv import load_dotenv
from prompts.entity_extraction_prompt import new_entity_extraction_prompt, build_extraction_prompt
from schemas.entity_extraction_schema import NewBorgesGraphNodes
import time
from datetime import datetime
from llm_utils import get_llm
import pickle
from langchain_community.callbacks.manager import get_openai_callback

# Configure logging
from logger import setup_logger
logger = setup_logger(__name__)

# Import cost tracking utilities
from cost_tracking_utils import TokenUsageStats

# Load environment variables
load_dotenv(override=True)
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "Borges Knowledge Graph"
os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGCHAIN_API_KEY")
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
os.environ["BACKUP_OPENAI_API_KEY"] = os.getenv("BACKUP_OPENAI_API_KEY")

class ChunkProcessingError(Exception):
    """Custom exception for chunk processing errors"""
    pass

class RetryableError(ChunkProcessingError):
    """Errors that should be retried"""
    pass

class NonRetryableError(ChunkProcessingError):
    """Errors that should not be retried"""
    pass

class APIKeyManager:
    """Manages OpenAI API key switching for rate limit handling"""
    
    def __init__(self):
        self.primary_key = os.getenv("OPENAI_API_KEY")
        self.backup_key = os.getenv("BACKUP_OPENAI_API_KEY")
        self.current_key = "primary"
        self.switch_attempts = 0
        self.max_switches = 2  # Limit key switches to prevent infinite loops
        
    def get_current_key(self) -> str:
        """Get the currently active API key"""
        if self.current_key == "primary":
            return self.primary_key
        return self.backup_key
    
    def switch_to_backup(self) -> bool:
        """Switch to backup key if available and not already switched too many times"""
        if (self.backup_key and 
            self.current_key == "primary" and 
            self.switch_attempts < self.max_switches):
            
            os.environ["OPENAI_API_KEY"] = self.backup_key
            self.current_key = "backup"
            self.switch_attempts += 1
            logger.warning(f"  🔄 Switched to backup OpenAI API key (attempt {self.switch_attempts})")
            return True
        return False
    
    def switch_to_primary(self) -> bool:
        """Switch back to primary key if available"""
        if (self.primary_key and 
            self.current_key == "backup" and 
            self.switch_attempts < self.max_switches):
            
            os.environ["OPENAI_API_KEY"] = self.primary_key
            self.current_key = "primary"
            self.switch_attempts += 1
            logger.info(f"  🔄 Switched back to primary OpenAI API key (attempt {self.switch_attempts})")
            return True
        return False
    
    def reset_switches(self):
        """Reset the switch counter (call this after successful processing)"""
        self.switch_attempts = 0

def is_retryable_error(error: Exception) -> bool:
    """
    Determine if an error should be retried based on error type and message
    """
    # Check for specific error types that are retryable
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    
    # Check for HTTP-like status codes if available
    if hasattr(error, 'status_code'):
        if error.status_code == 429:  # Too Many Requests
            return True
        if error.status_code >= 500:  # Server errors
            return True
        if error.status_code in [408, 502, 503, 504]:  # Timeout and gateway errors
            return True
    
    # Check error message for retryable patterns
    error_message = str(error).lower()
    retryable_patterns = [
        'rate limit',
        'quota exceeded',
        'server error',
        'service unavailable',
        'timeout',
        'connection',
        'network',
        'temporary',
        'throttled',
        'overloaded',
        'too many requests',
        '429',
        'ratelimiterror'
    ]
    
    if any(pattern in error_message for pattern in retryable_patterns):
        return True
    
    # Non-retryable patterns
    non_retryable_patterns = [
        'authentication',
        'authorization',
        'invalid api key',
        'permission denied',
        'bad request',
        'malformed',
        'invalid input',
        'schema validation'
    ]
    
    if any(pattern in error_message for pattern in non_retryable_patterns):
        return False
    
    # Default to retryable for unknown errors
    return True

def is_rate_limit_error(error: Exception) -> bool:
    """
    Specifically check if this is a rate limit error that should trigger API key switch
    """
    error_message = str(error).lower()
    rate_limit_patterns = [
        'rate limit',
        'quota exceeded',
        'too many requests',
        '429',
        'ratelimiterror',
        'overloaded'
    ]
    
    return any(pattern in error_message for pattern in rate_limit_patterns)

def calculate_backoff_delay(attempt: int, base_delay: float, max_delay: float, 
                          backoff_multiplier: float, jitter: bool = True) -> float:
    """
    Calculate delay with exponential backoff and optional jitter
    """
    # Correct exponential backoff formula
    delay = base_delay * (backoff_multiplier ** attempt)
    delay = min(delay, max_delay)
    
    if jitter:
        # Add ±25% jitter to prevent thundering herd
        jitter_range = delay * 0.25
        delay += random.uniform(-jitter_range, jitter_range)
    
    return max(0.1, delay)  # Minimum 0.1 second delay

def save_partial_results(chunks_data: List[Dict], all_responses: List[Any], 
                        source_doc_name: str, failed_chunk_index: int) -> None:
    """
    Save partial results when processing fails
    """
    partial_dir = "partial_graph_processing"
    os.makedirs(partial_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    partial_chunks_path = os.path.join(partial_dir, f"{source_doc_name}_chunks_data_partial_{timestamp}.pkl")
    partial_responses_path = os.path.join(partial_dir, f"{source_doc_name}_all_responses_partial_{timestamp}.pkl")
    
    # Save processing metadata
    metadata = {
        "source_doc_name": source_doc_name,
        "total_chunks": len(chunks_data),
        "processed_chunks": len(all_responses),
        "failed_at_chunk": failed_chunk_index,
        "timestamp": timestamp,
        "success_rate": len(all_responses) / len(chunks_data) * 100 if chunks_data else 0
    }
    
    metadata_path = os.path.join(partial_dir, f"{source_doc_name}_metadata_{timestamp}.pkl")
    
    try:
        with open(partial_chunks_path, "wb") as f:
            pickle.dump(chunks_data, f)
        with open(partial_responses_path, "wb") as f:
            pickle.dump(all_responses, f)
        with open(metadata_path, "wb") as f:
            pickle.dump(metadata, f)
            
        logger.info(f"  💾 Partial results saved to {partial_dir}/ for {source_doc_name}")
        logger.info(f"  📊 Processed {len(all_responses)}/{len(chunks_data)} chunks successfully")
        
    except Exception as save_e:
        logger.error(f"  ❌ Failed to save partial results: {save_e}")

async def process_single_chunk_with_backoff(chunk: str, chunk_id: str, source_doc_name: str,
                                    provider: str, model_name: str,
                                    api_key_manager: APIKeyManager,
                                    stats_tracker: Optional[TokenUsageStats] = None,
                                    custom_prompt: Optional[str] = None,
                                    max_retries: int = 5, base_delay: float = 1.0,
                                    max_delay: float = 60.0, backoff_multiplier: float = 2.0) -> Optional[Any]:
    """
    Process a single chunk with proper exponential backoff and API key switching

    Args:
        stats_tracker: Optional TokenUsageStats instance for cost tracking
        custom_prompt: Optional custom extraction prompt string from the API
    """
    for attempt in range(max_retries):
        try:
            # Re-initialize LLM with current API key
            structured_llm = get_llm(provider, model_name, temperature=0, structured_output_schema=NewBorgesGraphNodes)

            llm_start = datetime.now()
            chain = (build_extraction_prompt(custom_prompt) | structured_llm).with_config(
                {"run_name": f"EntityExtraction_{provider}_{model_name}_bioy"}
            )

            # Wrap LLM call with cost tracking for OpenAI models
            if provider.lower() == "openai" and stats_tracker is not None:
                with get_openai_callback() as cb:
                    response = await chain.ainvoke({"input": chunk, "source_doc_name": source_doc_name})
                    llm_duration = (datetime.now() - llm_start).total_seconds()

                    # Calculate cost using our pricing table (cb.total_cost may be 0 for newer models)
                    calculated_cost = stats_tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens)

                    # Track token usage and cost
                    stats_tracker.add_usage(
                        prompt_tokens=cb.prompt_tokens,
                        completion_tokens=cb.completion_tokens,
                        cost=calculated_cost,
                        context=f"{source_doc_name}_chunk_{chunk_id}"
                    )
                    logger.info(f"  💰 Tokens: {cb.total_tokens} (in: {cb.prompt_tokens}, out: {cb.completion_tokens}), Cost: ${calculated_cost:.6f}")
            else:
                # For non-OpenAI providers or when tracking is disabled
                response = await chain.ainvoke({"input": chunk, "source_doc_name": source_doc_name})
                llm_duration = (datetime.now() - llm_start).total_seconds()

            logger.info(f"  ⏱️  LLM processing took {llm_duration:.2f}s")
            
            if isinstance(response, NewBorgesGraphNodes):
                logger.info(f"  📊 Extracted {len(response.nodes)} entities from chunk")
                # Reset API key switches on successful processing
                api_key_manager.reset_switches()
                return response
            else:
                logger.warning(f"  ⚠️  Chunk {chunk_id} returned unexpected format. Type: {type(response)}")
                # This might be retryable depending on the cause
                raise RetryableError(f"Unexpected response format: {type(response)}")
                
        except Exception as e:
            error_str = str(e)
            logger.error(f"  ❌ Error processing chunk {chunk_id} (attempt {attempt + 1}/{max_retries}): {error_str}")
            
            # Check if this is a rate limit error and we should switch API keys
            if (provider == "openai" and 
                is_rate_limit_error(e) and 
                api_key_manager.switch_to_backup()):
                
                # Give the new key a moment to be recognized
                await asyncio.sleep(1)
                continue  # Retry immediately with new key
            
            # Determine if error is retryable
            if not is_retryable_error(e):
                logger.error(f"  🚫 Non-retryable error for chunk {chunk_id}: {error_str}")
                raise NonRetryableError(error_str)
            
            if attempt == max_retries - 1:  # Last attempt
                logger.error(f"  🔚 Max retries reached for chunk {chunk_id}")
                return None
            
            # Calculate delay with jitter
            delay = calculate_backoff_delay(attempt, base_delay, max_delay, backoff_multiplier)
            logger.info(f"  ⏳ Retrying after {delay:.1f}s...")
            await asyncio.sleep(delay)
    
    return None

async def process_text_to_graph_data(text: str, source_doc_name: str, provider: str, model_name: str,
                             max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 60.0,
                             backoff_multiplier: float = 2.0,
                             continue_on_failure: bool = True,
                             max_consecutive_failures: int = 3,
                             save_partial_every: int = 10,
                             stats_tracker: Optional[TokenUsageStats] = None,
                             document_metadata: Optional[dict] = None,
                             custom_prompt: Optional[str] = None,
                             max_concurrent_chunks: int = 5) -> Tuple[List[Dict[str, Any]], List[Any]]:
    """
    Enhanced text processing with parallel chunk processing, proper error handling, 
    exponential backoff, and API key switching.

    Args:
        text: The full input text.
        source_doc_name: The name of the source document.
        provider: The LLM provider ("openai" or "google").
        model_name: The model name to use with the provider.
        max_retries: Maximum number of retry attempts for LLM call.
        base_delay: Initial delay in seconds for backoff.
        max_delay: Maximum delay cap for backoff.
        backoff_multiplier: Exponential growth factor for backoff.
        continue_on_failure: Whether to continue processing after chunk failures.
        max_consecutive_failures: Stop if this many consecutive chunks fail.
        save_partial_every: Save partial results every N chunks.
        stats_tracker: Optional TokenUsageStats instance for cost tracking.
        document_metadata: Optional dictionary containing document metadata (collection, book, etc.).
        custom_prompt: Optional custom extraction prompt string from the API.
        max_concurrent_chunks: Maximum number of chunks to process in parallel (default: 5).

    Returns:
        A tuple containing chunks_data and all_responses.
    """
    logger.info("\n" + "="*60)
    logger.info(f"🚀 Starting text processing for document: {source_doc_name}")
    logger.info(f"🔧 Provider: {provider}, Model: {model_name}")
    logger.info(f"⚡ Parallel processing: Up to {max_concurrent_chunks} chunks concurrently")
    
    # Initialize API key manager
    api_key_manager = APIKeyManager()
    logger.info(f"🔑 API Key Manager initialized. Primary key: {'✅' if api_key_manager.primary_key else '❌'}, Backup key: {'✅' if api_key_manager.backup_key else '❌'}")
    
    start_time = datetime.now()

    # Split text into chunks
    split_start = datetime.now()
    splitter = RecursiveCharacterTextSplitter(
        #chunk_size=8000,
        chunk_size=2000,
        chunk_overlap=300
    )
    chunks = splitter.split_text(text)
    split_duration = (datetime.now() - split_start).total_seconds()
    logger.info(f"📝 Split text into {len(chunks)} chunks in {split_duration:.2f}s")

    # Prepare all chunk data upfront
    chunks_data = []
    for i, chunk in enumerate(chunks):
        chunk_id = f"{source_doc_name}_chunk_{i+1}"
        chunk_data = {
            "chunk_id": chunk_id,
            "file_name": source_doc_name,
            "chunk_text": chunk,
            # Add document metadata fields with defaults
            "collection_name": document_metadata.get('collection_name', '') if document_metadata else '',
            "book_name": document_metadata.get('book_name', '') if document_metadata else '',
            "index_name": document_metadata.get('index_name', '') if document_metadata else '',
            "document_title": document_metadata.get('document_title', '') if document_metadata else '',
            "publication_year": document_metadata.get('publication_year', '') if document_metadata else '',
            "genre": document_metadata.get('genre', '') if document_metadata else '',
            "file_path": document_metadata.get('file_path', '') if document_metadata else ''
        }
        chunks_data.append(chunk_data)

    # Process chunks in parallel with concurrency limit
    all_responses = []
    failed_chunks = []
    semaphore = asyncio.Semaphore(max_concurrent_chunks)
    
    async def process_chunk_with_semaphore(i: int, chunk: str) -> tuple:
        """Process a single chunk with semaphore to limit concurrency."""
        async with semaphore:
            chunk_id = f"{source_doc_name}_chunk_{i+1}"
            logger.info(f"\n🔄 Processing chunk {i+1}/{len(chunks)} ({(i+1)/len(chunks)*100:.1f}%)")
            
            # Prepare chunk with metadata
            enhanced_chunk = f"This chunk is from Source Document Name: {source_doc_name}\n" + \
                            f"The id of Chunk: {chunk_id}\n\n" + chunk
            
            chunk_start = datetime.now()
            try:
                # Process chunk with backoff and API key switching
                response = await process_single_chunk_with_backoff(
                    enhanced_chunk, chunk_id, source_doc_name,
                    provider, model_name, api_key_manager,
                    stats_tracker,
                    custom_prompt,
                    max_retries, base_delay, max_delay, backoff_multiplier
                )
                
                chunk_duration = (datetime.now() - chunk_start).total_seconds()
                
                if response is not None:
                    logger.info(f"  ✅ Chunk {i+1} processed successfully in {chunk_duration:.2f}s")
                    return (i, response, None)
                else:
                    # Chunk failed after all retries
                    logger.error(f"  ❌ Chunk {i+1} failed after {max_retries} retries")
                    return (i, None, {
                        "chunk_index": i,
                        "chunk_id": chunk_id,
                        "error": "Max retries exceeded"
                    })
                    
            except NonRetryableError as e:
                logger.error(f"  ❌ Non-retryable error for chunk {i+1}: {str(e)}")
                return (i, None, {
                    "chunk_index": i,
                    "chunk_id": chunk_id,
                    "error": f"Non-retryable: {str(e)}"
                })
                
            except Exception as e:
                logger.error(f"  ❌ Unexpected error for chunk {i+1}: {str(e)}")
                return (i, None, {
                    "chunk_index": i,
                    "chunk_id": chunk_id,
                    "error": f"Unexpected: {str(e)}"
                })
    
    # Create tasks for all chunks
    tasks = [process_chunk_with_semaphore(i, chunk) for i, chunk in enumerate(chunks)]
    
    # Execute all tasks in parallel (with semaphore limiting concurrency)
    logger.info(f"\n🚀 Starting parallel processing of {len(chunks)} chunks (max {max_concurrent_chunks} concurrent)...")
    results = await asyncio.gather(*tasks, return_exceptions=False)
    
    # Process results in original order
    all_responses = [None] * len(chunks)  # Pre-allocate list to maintain order
    for i, response, error in results:
        if response is not None:
            all_responses[i] = response
        elif error is not None:
            failed_chunks.append(error)
    
    # Remove None values from responses (failed chunks)
    all_responses = [r for r in all_responses if r is not None]
    processed_chunk_count = len(all_responses)
    consecutive_failures = len(failed_chunks)

    # Save partial results if there were any failures
    if failed_chunks:
        save_partial_results(chunks_data, all_responses, source_doc_name, len(chunks))
        logger.warning(f"⚠️  {len(failed_chunks)} chunks failed to process")

    # Save final partial results if there were any failures
    if failed_chunks:
        save_partial_results(chunks_data, all_responses, source_doc_name, len(chunks))

    total_duration = (datetime.now() - start_time).total_seconds()
    success_rate = processed_chunk_count / len(chunks) * 100 if chunks else 0
    
    logger.info("\n" + "="*60)
    logger.info("📊 PROCESSING SUMMARY")
    logger.info("="*60)
    logger.info(f"⏱️  Total processing time: {total_duration:.2f}s")
    logger.info(f"✅ Successfully processed: {processed_chunk_count}/{len(chunks)} chunks")
    logger.info(f"📈 Success rate: {success_rate:.1f}%")
    logger.info(f"❌ Failed chunks: {len(failed_chunks)}")
    logger.info(f"🔄 API key switches: {api_key_manager.switch_attempts}")
    logger.info(f"🔑 Final API key: {api_key_manager.current_key}")
    
    if len(chunks) > 0:
        logger.info(f"⚡ Average time per chunk: {total_duration/len(chunks):.2f}s")
    
    if failed_chunks:
        logger.info(f"🚫 Failed chunk IDs: {[f['chunk_id'] for f in failed_chunks]}")
    
    logger.info("="*60)
    
    return chunks_data, all_responses