import ast
import os
import time
import pandas as pd
from typing import List, Optional
from langchain_core.prompts import ChatPromptTemplate
from vectordb_utils import query_hybrid_search
from dotenv import load_dotenv
import json
import re
from llm_utils import get_llm
from prompts.entity_merging_prompt import get_entity_merging_prompt
from schemas.entity_merging_schema import MergedResponse
import random
import pickle
from datetime import datetime
from description_validation_utils import validate_merged_description
from langchain_community.callbacks.manager import get_openai_callback

load_dotenv(override=True)
from logger import get_logger
logger = get_logger(__name__)

# Import cost tracking utilities
from cost_tracking_utils import TokenUsageStats
from entity_checkpoint import EntityMergingCheckpoint
from persistent_entity_tracker import PersistentEntityIDTracker
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
os.environ["BACKUP_OPENAI_API_KEY"] = os.getenv("BACKUP_OPENAI_API_KEY")

# LLM prompt and schema
system_role = get_entity_merging_prompt()
prompt = ChatPromptTemplate.from_messages([
    ("system", system_role),
    ("human", '{input}')
])


class EntityProcessingError(Exception):
    """Custom exception for entity processing errors"""
    pass

class RetryableError(EntityProcessingError):
    """Errors that should be retried"""
    pass

class NonRetryableError(EntityProcessingError):
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

def calculate_backoff_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0, 
                          backoff_multiplier: float = 2.0, jitter: bool = True) -> float:
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

def save_partial_progress(merged_entities: List[dict], checkpoint_dir: str, 
                         current_idx: int, total_rows: int) -> None:
    """
    Save partial progress when processing fails
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    partial_filename = f"partial_entities_{current_idx:04d}_of_{total_rows:04d}_{timestamp}.pkl"
    partial_path = os.path.join(checkpoint_dir, partial_filename)
    
    # Save processing metadata
    metadata = {
        "processed_entities": len(merged_entities),
        "last_processed_index": current_idx,
        "total_rows": total_rows,
        "timestamp": timestamp,
        "progress_percentage": (current_idx / total_rows) * 100 if total_rows > 0 else 0
    }
    
    metadata_path = os.path.join(checkpoint_dir, f"metadata_{timestamp}.pkl")
    
    try:
        with open(partial_path, "wb") as f:
            pickle.dump(merged_entities, f)
        with open(metadata_path, "wb") as f:
            pickle.dump(metadata, f)
            
        logger.info(f"  💾 Partial progress saved: {len(merged_entities)} entities processed")
        logger.info(f"  📊 Progress: {current_idx}/{total_rows} ({(current_idx/total_rows)*100:.1f}%)")
        
    except Exception as save_e:
        logger.error(f"  ❌ Failed to save partial progress: {save_e}")

def merge_keyword_columns(keyword_dicts: List[dict]) -> dict:
    """
    Merge separate keyword columns from multiple entities.
    For each keyword field, take the first non-empty value (priority to root entity).
    
    Args:
        keyword_dicts: List of keyword dictionaries from entities being merged
        
    Returns:
        Dictionary with merged keyword values
    """
    merged = {}
    keyword_fields = [
        'century', 'country', 'literary_period', 'art_period',
        'historical_period', 'year', 'author', 'genre',
        'geo_type', 'institution_type'
    ]
    
    for field in keyword_fields:
        # Take first non-empty value (root entity has priority as it's first in list)
        for kw_dict in keyword_dicts:
            value = kw_dict.get(field)
            if value:
                merged[field] = value
                break
        else:
            # No value found in any dict
            merged[field] = None
    
    return merged

def keywords_to_list(keyword_dict: dict) -> List[str]:
    """
    Convert keyword dictionary to key:value list format for CSV output.
    Handles semicolon-separated and comma-separated values by splitting them into separate entries.

    Args:
        keyword_dict: Dictionary with keyword fields like {'century': '19th', 'country': 'uk'}
                     or with multiple values like {'century': '19th; 20th'} or {'century': '19th, 20th'}

    Returns:
        List of strings in 'key:value' format, e.g. ['century:19th', 'country:uk']
        For multi-value fields: ['century:19th', 'century:20th']
    """
    result = []
    for key, value in keyword_dict.items():
        if value:
            formatted_key = key.strip().lower()
            value_str = str(value).strip().lower()

            # Check if value contains semicolon or comma-separated multiple values
            if ';' in value_str or ',' in value_str:
                # Split on both semicolons and commas to handle all separator types
                individual_values = []
                # First split on semicolons
                for part in value_str.split(';'):
                    # Then split each part on commas
                    for subpart in part.split(','):
                        cleaned = subpart.strip()
                        if cleaned:
                            individual_values.append(cleaned.replace(' ', '_'))

                # Create separate entries for each value
                for individual_value in individual_values:
                    result.append(f"{formatted_key}:{individual_value}")
            else:
                # Single value: normalize spaces to underscores
                formatted_value = value_str.replace(' ', '_')
                result.append(f"{formatted_key}:{formatted_value}")
    return sorted(result)

def merge_descriptions(descriptions):
    """Join and deduplicate descriptions."""
    seen = set()
    merged = []
    for desc in descriptions:
        if desc and desc.strip() not in seen:
            seen.add(desc.strip())
            merged.append(desc.strip())
    return " ".join(merged)

def merge_aliases(aliases_lists):
    """
    Merge multiple lists of aliases, deduplicating and preserving order.

    Args:
        aliases_lists: List of alias lists (each can be a list, JSON string, or comma-separated string)

    Returns:
        JSON string of unique aliases
    """
    seen = set()
    merged = []

    for aliases in aliases_lists:
        # Parse aliases if it's a string
        if isinstance(aliases, str):
            try:
                # Try JSON parsing first
                parsed = json.loads(aliases)
                if isinstance(parsed, list):
                    aliases = parsed
                else:
                    aliases = [str(parsed)]
            except (json.JSONDecodeError, ValueError):
                # Try splitting by comma or semicolon
                aliases = [a.strip() for a in re.split(r'[,;]', aliases) if a.strip()]

        # Ensure aliases is a list
        if not isinstance(aliases, list):
            aliases = [str(aliases)] if aliases else []

        # Add unique aliases while preserving order
        for alias in aliases:
            alias_str = str(alias).strip()
            if alias_str and alias_str not in seen:
                seen.add(alias_str)
                merged.append(alias_str)

    return json.dumps(merged, ensure_ascii=False)

def merge_quotes(quotes_lists):
    """
    Merge multiple lists of quotes, deduplicating and preserving order.

    Args:
        quotes_lists: List of quote lists (each can be a list, JSON string, or comma-separated string)

    Returns:
        JSON string of unique quotes
    """
    seen = set()
    merged = []

    for quotes in quotes_lists:
        # Parse quotes if it's a string
        if isinstance(quotes, str):
            try:
                # Try JSON parsing first
                parsed = json.loads(quotes)
                if isinstance(parsed, list):
                    quotes = parsed
                else:
                    quotes = [str(parsed)]
            except (json.JSONDecodeError, ValueError):
                # Try splitting by newline or semicolon
                quotes = [q.strip() for q in re.split(r'[\n;]', quotes) if q.strip()]

        # Ensure quotes is a list
        if not isinstance(quotes, list):
            quotes = [str(quotes)] if quotes else []

        # Add unique quotes while preserving order
        for quote in quotes:
            quote_str = str(quote).strip()
            if quote_str and quote_str not in seen:
                seen.add(quote_str)
                merged.append(quote_str)

    return json.dumps(merged, ensure_ascii=False)

def parse_keywords_from_json(keywords_json: str) -> dict:
    """
    Parse keywords from JSON array format to dictionary.

    Args:
        keywords_json: JSON string like '["century:19th", "country:uk", "author:borges"]'

    Returns:
        Dictionary like {'century': '19th', 'country': 'uk', 'author': 'borges'}
    """
    keyword_dict = {}

    if not keywords_json or pd.isna(keywords_json):
        return keyword_dict

    try:
        # Parse JSON array
        keywords_list = json.loads(keywords_json)

        # Convert each key:value pair to dict entry
        for item in keywords_list:
            if isinstance(item, str) and ':' in item:
                key, value = item.split(':', 1)  # Split only on first colon
                keyword_dict[key.strip()] = value.strip()
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        logger.warning(f"Failed to parse keywords JSON: {keywords_json}. Error: {e}")

    return keyword_dict

def merge_keywords_from_entities(entity_keywords_list: List[str], df: Optional[pd.DataFrame] = None) -> dict:
    """
    Merge keywords from multiple entities programmatically.

    Args:
        entity_keywords_list: List of keywords JSON strings from multiple entities
        df: Full DataFrame to lookup merged entity keywords (optional, for context)

    Returns:
        Merged keyword dictionary with unique values per field
    """
    merged_keywords = {}
    keyword_fields = [
        'century', 'country', 'literary_period', 'art_period',
        'historical_period', 'year', 'author', 'genre',
        'geo_type', 'institution_type'
    ]

    # Initialize with empty sets for collecting unique values
    keyword_sets = {field: set() for field in keyword_fields}

    # Parse and collect keywords from all entities
    for keywords_json in entity_keywords_list:
        keyword_dict = parse_keywords_from_json(keywords_json)
        for field, value in keyword_dict.items():
            if field in keyword_sets and value:
                keyword_sets[field].add(value.lower().strip())

    # Convert sets to single values
    for field, value_set in keyword_sets.items():
        if value_set:
            # If multiple values, join with semicolon; otherwise take single value
            if len(value_set) == 1:
                merged_keywords[field] = list(value_set)[0]
            else:
                # Multiple values: join with semicolon (sorted for determinism)
                merged_keywords[field] = '; '.join(sorted(value_set))

    return merged_keywords

def extract_metadata_from_row(row: dict) -> dict:
    """
    Extract document metadata fields from a row.
    Returns a dict with metadata fields, handling missing values gracefully.
    """
    metadata = {
        'document_title': str(row.get('document_title', '')).strip() if pd.notna(row.get('document_title')) else '',
        'collection_name': str(row.get('collection_name', '')).strip() if pd.notna(row.get('collection_name')) else '',
        'book_name': str(row.get('book_name', '')).strip() if pd.notna(row.get('book_name')) else '',
        'publication_year': str(row.get('publication_year', '')).strip() if pd.notna(row.get('publication_year')) else '',
        'genre': str(row.get('genre', '')).strip() if pd.notna(row.get('genre')) else '',
        'file_path': str(row.get('file_path', '')).strip() if pd.notna(row.get('file_path')) else ''
    }
    return metadata

def aggregate_metadata(metadata_list: List[dict]) -> dict:
    """
    Aggregate multiple metadata dictionaries into semicolon-separated strings.
    Deduplicates values and returns aggregated metadata.
    """
    aggregated = {
        'document_titles': set(),
        'collections': set(),
        'books': set(),
        'years': set(),
        'genres': set(),
        'file_paths': set()
    }

    for metadata in metadata_list:
        if metadata.get('document_title'):
            aggregated['document_titles'].add(metadata['document_title'])
        if metadata.get('collection_name'):
            aggregated['collections'].add(metadata['collection_name'])
        if metadata.get('book_name'):
            aggregated['books'].add(metadata['book_name'])
        if metadata.get('publication_year'):
            aggregated['years'].add(metadata['publication_year'])
        if metadata.get('genre'):
            aggregated['genres'].add(metadata['genre'])
        if metadata.get('file_path'):
            aggregated['file_paths'].add(metadata['file_path'])

    # Convert sets to semicolon-separated sorted strings
    return {
        'document_titles': '; '.join(sorted(aggregated['document_titles'])) if aggregated['document_titles'] else '',
        'collections': '; '.join(sorted(aggregated['collections'])) if aggregated['collections'] else '',
        'books': '; '.join(sorted(aggregated['books'])) if aggregated['books'] else '',
        'years': '; '.join(sorted(aggregated['years'])) if aggregated['years'] else '',
        'genres': '; '.join(sorted(aggregated['genres'])) if aggregated['genres'] else '',
        'file_paths': '; '.join(sorted(aggregated['file_paths'])) if aggregated['file_paths'] else '',
        'occurrence_count': len(metadata_list)
    }

async def process_entity_with_backoff(row: dict, idx: int, provider: str, model_name: str,
                              api_key_manager: APIKeyManager,
                              entity_tracker: PersistentEntityIDTracker,
                              stats_tracker: Optional[TokenUsageStats] = None,
                              max_retries: int = 5, base_delay: float = 1.0,
                              max_delay: float = 60.0, backoff_multiplier: float = 2.0,
                              df: Optional[pd.DataFrame] = None,
                              collection_name: Optional[str] = None) -> Optional[dict]:
    """
    Process a single entity with proper exponential backoff and API key switching

    Args:
        entity_tracker: PersistentEntityIDTracker for tracking processed entities
        stats_tracker: Optional TokenUsageStats instance for cost tracking
        df: Full DataFrame containing all entities (needed for metadata lookup)
        collection_name: Optional Qdrant collection name for vector search (defaults to global)
    """
    entity_name = row['entity_name']
    entity_type = row['entity_type']
    entity_category = row['entity_category']

    # Extract metadata from current row
    root_metadata = extract_metadata_from_row(row)
    
    for attempt in range(max_retries):
        try:
            # Re-initialize LLM with current API key
            structured_llm = get_llm(provider, model_name, temperature=1, structured_output_schema=MergedResponse)
            
            query_text = prepare_query_text(row)

            # Use tracker's entity IDs for deduplication in vector search
            # No temporary copy needed - tracker maintains persistent state
            matches = await query_hybrid_search(query_text, entity_type, entity_name,
                                               row['entity_id'], entity_tracker.get_all(),
                                               collection_name=collection_name)
            input_text = format_input_text(row, matches)

            llm_start = datetime.now()
            chain = (prompt | structured_llm).with_config(
                {"run_name": f"MatchingEntities_{provider}_{model_name}_bioy"}
            )

            # Wrap LLM call with cost tracking for OpenAI models
            if provider.lower() == "openai" and stats_tracker is not None:
                with get_openai_callback() as cb:
                    response = chain.invoke({"input": input_text})
                    llm_duration = (datetime.now() - llm_start).total_seconds()

                    # Calculate cost using our pricing table (cb.total_cost may be 0 for newer models)
                    calculated_cost = stats_tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens)

                    # Track token usage and cost
                    stats_tracker.add_usage(
                        prompt_tokens=cb.prompt_tokens,
                        completion_tokens=cb.completion_tokens,
                        cost=calculated_cost,
                        context=f"merge_entity_{entity_name}_{idx}"
                    )
                    logger.info(f"  💰 Tokens: {cb.total_tokens} (in: {cb.prompt_tokens}, out: {cb.completion_tokens}), Cost: ${calculated_cost:.6f}")
            else:
                # For non-OpenAI providers or when tracking is disabled
                response = chain.invoke({"input": input_text})
                llm_duration = (datetime.now() - llm_start).total_seconds()

            logger.info(f"  ⏱️  LLM processing took {llm_duration:.2f}s")
            
            result = response.model_dump()

            if result['is_merged']:
                merged_result = result['merged_result']

                # 🔹 Always use root entity metadata
                merged_result['entity_name'] = entity_name
                merged_result['entity_type'] = entity_type
                merged_result['entity_category'] = entity_category
                merged_result['entity_identification'] = row['entity_identification']

                # 🔹 Merge & normalize descriptions, keywords, aliases, and quotes
                all_descriptions = []
                all_keywords_json = []
                all_aliases = []
                all_quotes = []

                # 1. Root entity description + keywords + aliases + quotes
                if row.get('entity_description'):
                    all_descriptions.append(row['entity_description'])

                # Extract root entity aliases
                if row.get('aliases'):
                    all_aliases.append(row['aliases'])

                # Extract root entity quotes
                if row.get('quotes'):
                    all_quotes.append(row['quotes'])

                # Extract root entity keywords from JSON keywords column
                if row.get('keywords'):
                    all_keywords_json.append(row['keywords'])

                # 2. Merge from duplicates if present in LLM output
                if merged_result.get('merged_description'):
                    all_descriptions.append(merged_result['merged_description'])

                # 3. Normalize final merged fields
                initial_merged_description = merge_descriptions(all_descriptions)

                # 4. Validate and clean merged description for duplicates
                merged_result['merged_description'] = validate_merged_description(
                    initial_merged_description,
                    row['entity_identification']
                )

                # 🔹 Collect metadata, aliases, and quotes from root entity and all merged entities
                all_metadata = [root_metadata]  # Start with root entity metadata

                if merged_result.get('merged_entity_ids'):
                    # Look up metadata, aliases, and quotes for each merged entity
                    for merged_entity_id in merged_result['merged_entity_ids']:
                        try:
                            # First, try to find in DataFrame (current batch)
                            if df is not None:
                                merged_entity_row = df[df['entity_id'] == merged_entity_id]
                                if not merged_entity_row.empty:
                                    entity_row_dict = merged_entity_row.iloc[0]
                                    merged_metadata = extract_metadata_from_row(entity_row_dict)
                                    all_metadata.append(merged_metadata)
                                    # Collect aliases from merged entity
                                    if entity_row_dict.get('aliases'):
                                        all_aliases.append(entity_row_dict['aliases'])
                                    # Collect quotes from merged entity
                                    if entity_row_dict.get('quotes'):
                                        all_quotes.append(entity_row_dict['quotes'])
                                    # Collect keywords from merged entity
                                    if entity_row_dict.get('keywords'):
                                        all_keywords_json.append(entity_row_dict['keywords'])
                                    continue

                            # Fallback: Extract from Qdrant matches if not found in DataFrame
                            # (This handles entities from previous batches already in vector DB)
                            if matches:
                                for match in matches:
                                    match_payload = match.get('payload', {})
                                    if match_payload.get('entity_id') == merged_entity_id:
                                        merged_metadata = extract_metadata_from_row(match_payload)
                                        all_metadata.append(merged_metadata)
                                        # Collect aliases from Qdrant payload if available
                                        if match_payload.get('aliases'):
                                            all_aliases.append(match_payload['aliases'])
                                        # Collect quotes from Qdrant payload if available
                                        if match_payload.get('quotes'):
                                            all_quotes.append(match_payload['quotes'])
                                        # Collect keywords from Qdrant payload if available
                                        if match_payload.get('keywords'):
                                            all_keywords_json.append(match_payload['keywords'])
                                        logger.debug(f"  📦 Retrieved metadata for {merged_entity_id} from Qdrant payload")
                                        break
                        except Exception as e:
                            logger.warning(f"  ⚠️  Could not extract metadata for merged entity {merged_entity_id}: {str(e)}")

                # Aggregate all collected metadata
                aggregated_metadata = aggregate_metadata(all_metadata)
                merged_result.update(aggregated_metadata)

                # 5. Merge keywords programmatically from all collected entities
                merged_keywords_dict = merge_keywords_from_entities(all_keywords_json, df)
                merged_result['merged_keywords'] = keywords_to_list(merged_keywords_dict)

                # 6. Merge aliases and quotes
                merged_result['merged_aliases'] = merge_aliases(all_aliases)
                merged_result['merged_quotes'] = merge_quotes(all_quotes)

                # 🔹 Track merged IDs - persist immediately
                entity_tracker.add_multiple(merged_result['merged_entity_ids'])
                entity_tracker.add(row['entity_id'])

                logger.info(f"  ✅ Row {idx} merged with entity_ids: {merged_result['merged_entity_ids']}")
                logger.info(f"  📚 Aggregated from {aggregated_metadata['occurrence_count']} document(s)")

                # Reset API key switches on successful processing
                api_key_manager.reset_switches()
                return merged_result
            else:
                # Validate standalone entity description as well
                validated_description = validate_merged_description(
                    row['entity_description'],
                    row['entity_identification']
                )

                # For standalone entities, metadata comes from single source (root entity only)
                aggregated_metadata = aggregate_metadata([root_metadata])

                # Extract standalone entity keywords from JSON keywords column
                standalone_keywords = parse_keywords_from_json(row.get('keywords', '[]'))

                # Extract standalone entity aliases and quotes
                standalone_aliases = row.get('aliases', '[]')  # Default to empty JSON array
                standalone_quotes = row.get('quotes', '[]')  # Default to empty JSON array

                new_entity = {
                    'root_entity_id': row['entity_id'],
                    'entity_name': row['entity_name'],
                    'entity_identification': row['entity_identification'],
                    'merged_description': validated_description,
                    'merged_references': extract_reference_texts(row['references']),
                    'merged_locations': [""],
                    'merged_entity_ids': [],
                    'merged_aliases': standalone_aliases if standalone_aliases else '[]',  # Keep as JSON string
                    'merged_quotes': standalone_quotes if standalone_quotes else '[]',  # Keep as JSON string
                    'entity_type': entity_type,
                    'entity_category': entity_category,
                    # Convert keywords to key:value list format
                    'merged_keywords': keywords_to_list(standalone_keywords)
                }

                # Add aggregated metadata to standalone entity
                new_entity.update(aggregated_metadata)

                entity_tracker.add(row['entity_id'])
                logger.info(f"  ✅ Row {idx} added as standalone entity with entity_id: {row['entity_id']}")

                # Reset API key switches on successful processing
                api_key_manager.reset_switches()
                return new_entity
                
        except Exception as e:
            error_str = str(e)
            logger.error(f"  ❌ Error processing entity {idx} (attempt {attempt + 1}/{max_retries}): {error_str}")
            
            # Check if this is a rate limit error and we should switch API keys
            if (provider == "openai" and 
                is_rate_limit_error(e) and 
                api_key_manager.switch_to_backup()):
                
                # Give the new key a moment to be recognized
                time.sleep(1)
                continue  # Retry immediately with new key
            
            # Determine if error is retryable
            if not is_retryable_error(e):
                logger.error(f"  🚫 Non-retryable error for entity {idx}: {error_str}")
                raise NonRetryableError(error_str)
            
            if attempt == max_retries - 1:  # Last attempt
                logger.error(f"  🔚 Max retries reached for entity {idx}")
                return None
            
            # Calculate delay with jitter
            delay = calculate_backoff_delay(attempt, base_delay, max_delay, backoff_multiplier)
            logger.info(f"  ⏳ Retrying after {delay:.1f}s...")
            time.sleep(delay)
    
    return None

def prepare_query_text(row):
    try:
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
                    logger.warning(f"Could not parse references. Attempting to extract text content.")
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

        query_text = f"{row['entity_name']}: {row['entity_identification']}. {row['entity_description']}. Reference Text: {' '.join(ref_texts)}"
        return query_text
    except Exception as e:
        logger.error(f"Error processing row: {e}")
        # Return a basic query text with just the entity name and description if references fail
        return f"{row['entity_name']}: {row['entity_identification']}. {row['entity_description']}."

def format_input_text(target_row, matches):
    """
    Format the target entity and its matching results into a string for the LLM.
    Exclude the target entity from matches if present.
    """
    try:
        # Safely access target_row fields with default values for missing or None fields
        target_entity_id = target_row.get('entity_id', 'unknown_id')
        
        # Format Contextual References
        references_str = target_row.get('references', 'N/A')
        formatted_references = ""
        try:
            if pd.isna(references_str):
                formatted_references = "None"
            else:
                try:
                    refs = json.loads(references_str)
                except Exception:
                    try:
                        refs = ast.literal_eval(references_str)
                    except Exception:
                        refs = []
                if not isinstance(refs, list):
                    refs = [refs] if refs else []
                ref_lines = []
                for ref in refs:
                    if isinstance(ref, dict):
                        text = ref.get('text', '')
                        source = ref.get('source', '')
                        location = ref.get('location', '')
                        line = f"Text: {text} | Source: {source} | Location: {location}"
                        ref_lines.append(line)
                    else:
                        ref_lines.append(str(ref))
                formatted_references = "\n".join(ref_lines) if ref_lines else "None"
        except Exception as e:
            logger.error(f"Error formatting references: {e}")
            formatted_references = str(references_str)

        target_text = (
            f"=== PRIMARY ENTITY TO ANALYZE ===\n"
            f"Entity ID: {target_row.get('entity_id', 'N/A')}\n"
            f"Full Name: {target_row.get('entity_name', 'N/A')}\n"
            f"Identity Profile: {target_row.get('entity_identification', 'N/A')}\n"
            f"Description: {target_row.get('entity_description', 'N/A')}\n"
            f"Contextual References:\n{formatted_references}\n"
        )
        
        matches_text = "\n=== CANDIDATE ENTITIES FOR COMPARISON ===\n"
        
        if not matches:
            matches_text += "No matching results found.\n"
        else:
            try:
                result_count = 0
                for i, point in enumerate(matches, 1):
                    try:
                        # Ensure point has payload; skip if not
                        payload = point.get('payload', {})
                        if not payload:
                            continue
                            
                        # Skip if this is the target entity
                        entity_id = payload.get('entity_id', 'N/A')
                        if entity_id == target_entity_id:
                            continue
                            
                        # Extract payload fields with defaults
                        entity_name = payload.get('entity_name', 'N/A')
                        entity_type = payload.get('entity_type', 'N/A')
                        entity_category = payload.get('entity_category', 'N/A')
                        entity_identification = payload.get('entity_identification', 'N/A')
                        entity_description = payload.get('entity_description', 'N/A')
                        references = payload.get('references', 'N/A')
                        location = payload.get('location', 'N/A')

                        # Safely get score with default value
                        try:
                            score = point.get('score', 0.0)
                            score_formatted = f"{score:.5f}"
                        except (TypeError, ValueError):
                            score_formatted = "N/A"
                        
                        result_count += 1
                        # Format each match with enhanced structure
                        matches_text += (
                            f"--- CANDIDATE #{result_count} ---\n"
                            f"Entity ID: {entity_id}\n"
                            f"Full Name: {entity_name}\n"
                            f"Identity Profile: {entity_identification}\n"
                            f"Description: {entity_description}\n"
                            f"Contextual References: {references}\n"
                            f"--- END CANDIDATE #{result_count} ---\n\n"
                        )
                    except Exception as e:
                        logger.error(f"Error processing match point {i}: {e}")
                        continue
                
                if result_count == 0:
                    matches_text += "No matching results found after filtering.\n"
            except Exception as e:
                logger.error(f"Error processing matches: {e}")
                matches_text += f"Error processing matches: {str(e)}\n"
                
        return target_text + matches_text
    except Exception as e:
        logger.error(f"Error in format_input_text: {e}")
        # Return a simplified but functional input text to avoid complete failure
        return (f"Target Entity:\nentity_id: {target_row.get('entity_id', 'unknown')}\n"
                f"entity_name: {target_row.get('entity_name', 'unknown')}\n"
                f"\nMatching Results:\nError formatting matches: {str(e)}")

def extract_reference_texts(references_str):
    try:
        if pd.isna(references_str):
            return ""
            
        try:
            # First try to parse as JSON since it might be JSON-encoded
            refs = json.loads(references_str)
        except json.JSONDecodeError:
            try:
                # If JSON fails, try ast.literal_eval
                refs = ast.literal_eval(references_str)
            except (SyntaxError, ValueError):
                # If both fail, try to extract any text content
                logger.warning(f"Could not parse references. Attempting to extract text content.")
                if isinstance(references_str, str):
                    # Try to find any text content between quotes
                    text_matches = re.findall(r'"text"\s*:\s*"([^"]*)"', references_str)
                    if text_matches:
                        return "\n".join(text_matches)
                    else:
                        return references_str
                else:
                    return str(references_str)

        # Ensure refs is a list
        if not isinstance(refs, list):
            refs = [refs] if refs else []

        # Extract text from references, handling both dict and string formats
        ref_texts = []
        for ref in refs:
            if isinstance(ref, dict):
                text = ref.get('text', '')
            elif isinstance(ref, str):
                text = ref
            else:
                text = str(ref)
            if text:
                ref_texts.append(text)

        return "\n".join(ref_texts)
    except Exception as e:
        logger.error(f"Error parsing references: {e}")
        return str(references_str) if references_str is not None else ""

async def generate_unique_entities_csv(
    results_csv_path: str,
    output_csv_path: str,
    provider: str,
    model_name: str,
    stats_tracker: Optional[TokenUsageStats] = None,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_multiplier: float = 2.0,
    continue_on_failure: bool = True,
    max_consecutive_failures: int = 3,
    checkpoint_interval: int = 100
):
    """
    Enhanced entity processing with proper error handling, exponential backoff, and API key switching.
    
    Args:
        results_csv_path: Path to the input CSV file with entities
        output_csv_path: Path to save the output CSV file
        provider: The LLM provider ("openai" or "google")
        model_name: The model name to use with the provider
        max_retries: Maximum number of retry attempts for LLM call
        base_delay: Initial delay in seconds for backoff
        max_delay: Maximum delay cap for backoff
        backoff_multiplier: Exponential growth factor for backoff
        continue_on_failure: Whether to continue processing after entity failures
        max_consecutive_failures: Stop if this many consecutive entities fail
        checkpoint_interval: Save checkpoint every N entities
    """
    logger.info("\n" + "="*60)
    logger.info("🚀 Starting entity processing with enhanced error handling")
    logger.info("="*60)
    
    # Initialize API key manager
    api_key_manager = APIKeyManager()
    logger.info(f"🔑 API Key Manager initialized. Primary key: {'✅' if api_key_manager.primary_key else '❌'}, Backup key: {'✅' if api_key_manager.backup_key else '❌'}")
    
    logger.info(f"📂 Loading results CSV from {results_csv_path}")
    df = pd.read_csv(results_csv_path)

    # Checkpointing setup
    checkpoint_dir = "temporary_unique_files"
    os.makedirs(checkpoint_dir, exist_ok=True)
    checkpoint_manager = EntityMergingCheckpoint(checkpoint_dir)

    # Initialize persistent entity tracker
    entity_tracker = PersistentEntityIDTracker(
        os.path.join(checkpoint_dir, "processed_entity_ids.json"),
        auto_save=True
    )

    # Try to resume from checkpoint
    checkpoint_state = checkpoint_manager.load_checkpoint()
    start_idx = 0
    merged_entities = []

    if checkpoint_state:
        logger.info("🔄 Resuming from checkpoint...")
        start_idx = checkpoint_state['last_processed_index'] + 1
        merged_entities = checkpoint_manager.load_processed_entities()
        logger.info(f"   Resuming from index {start_idx}/{len(df)}")
        logger.info(f"   Already processed: {len(merged_entities)} entities")
        logger.info(f"   Tracked entity IDs: {entity_tracker.get_count()}")

    failed_entities = []
    consecutive_failures = 0

    start_time = datetime.now()
    total_rows = len(df)

    logger.info(f"📊 Processing {total_rows - start_idx} remaining entities (total: {total_rows})")
    logger.info(f"💾 Checkpoints will be saved every {checkpoint_interval} entities")

    for idx, row in df.iterrows():
        # Skip already processed entities
        if idx < start_idx:
            continue

        try:
            entity_start = datetime.now()
            logger.info(f"\n🔄 Processing entity {idx+1}/{total_rows} ({((idx+1)/total_rows)*100:.1f}%): {row['entity_name']}")
            
            if entity_tracker.contains(row['entity_id']):
                logger.info(f"  ⏭️  Skipping entity {idx+1}: entity_id '{row['entity_id']}' already processed or merged.")
                continue

            # Process entity with backoff and API key switching
            result = await process_entity_with_backoff(
                row, idx, provider, model_name, api_key_manager,
                entity_tracker, stats_tracker,
                max_retries, base_delay, max_delay, backoff_multiplier,
                df=df
            )
            
            if result is not None:
                merged_entities.append(result)
                consecutive_failures = 0  # Reset consecutive failure counter
                logger.info(f"  ✅ Entity {idx+1} processed successfully")
            else:
                # Entity failed after all retries
                failed_entities.append({
                    "entity_index": idx,
                    "entity_id": row['entity_id'],
                    "entity_name": row['entity_name'],
                    "error": "Max retries exceeded"
                })
                consecutive_failures += 1
                
                logger.error(f"  ❌ Entity {idx+1} failed after {max_retries} retries")
                
                if not continue_on_failure:
                    logger.error("  🛑 Stopping processing due to entity failure")
                    break
                
                # Check consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    logger.error(f"  🛑 Stopping: {consecutive_failures} consecutive failures")
                    break
            
            # Save checkpoint every N processed entities using the new checkpoint manager
            if len(merged_entities) % checkpoint_interval == 0 and len(merged_entities) > 0:
                checkpoint_manager.save_checkpoint(
                    merged_entities=merged_entities,
                    processed_entity_ids=entity_tracker.get_all(),
                    last_processed_index=idx,
                    total_rows=total_rows
                )

                # Also save batch CSV for backward compatibility
                start_idx_batch = len(merged_entities) - checkpoint_interval + 1
                end_idx_batch = len(merged_entities)
                checkpoint_filename = f"processed_entities_{start_idx_batch:04d}-{end_idx_batch:04d}.csv"
                checkpoint_path = os.path.join(checkpoint_dir, checkpoint_filename)

                checkpoint_df = pd.DataFrame(merged_entities[-checkpoint_interval:])
                checkpoint_df = checkpoint_df[[
                    'root_entity_id', 'entity_name', 'entity_type', 'entity_category',
                    'entity_identification', 'merged_description', 'merged_aliases', 'merged_quotes', 'merged_references',
                    'merged_locations', 'merged_entity_ids',
                    'merged_century', 'merged_country', 'merged_literary_period', 'merged_art_period',
                    'merged_historical_period', 'merged_year', 'merged_author', 'merged_genre',
                    'merged_geo_type', 'merged_institution_type',
                    'document_titles', 'collections', 'books', 'years', 'genres', 'file_paths', 'occurrence_count'
                ]]
                checkpoint_df.to_csv(checkpoint_path, index=False)
                logger.info(f"  💾 Checkpoint: Saved {checkpoint_interval} entities to {checkpoint_path}")
            
            entity_duration = (datetime.now() - entity_start).total_seconds()
            logger.info(f"  ⏱️  Entity {idx+1} processed in {entity_duration:.2f}s")
            
            # Brief pause between successful requests
            if result is not None:
                time.sleep(0.5)
                
        except NonRetryableError as e:
            logger.error(f"  ❌ Non-retryable error for entity {idx+1}: {str(e)}")
            failed_entities.append({
                "entity_index": idx,
                "entity_id": row['entity_id'],
                "entity_name": row['entity_name'],
                "error": f"Non-retryable: {str(e)}"
            })
            consecutive_failures += 1
            
            if not continue_on_failure:
                break
                
        except Exception as e:
            logger.error(f"  ❌ Unexpected error for entity {idx+1}: {str(e)}")
            failed_entities.append({
                "entity_index": idx,
                "entity_id": row['entity_id'],
                "entity_name": row['entity_name'],
                "error": f"Unexpected: {str(e)}"
            })
            consecutive_failures += 1
            
            if not continue_on_failure:
                break
    
    # Save final checkpoint if there were failures
    if failed_entities:
        checkpoint_manager.save_checkpoint(
            merged_entities=merged_entities,
            processed_entity_ids=entity_tracker.get_all(),
            last_processed_index=len(df) - 1,
            total_rows=total_rows
        )
        save_partial_progress(merged_entities, checkpoint_dir, len(df), len(df))
        # Ensure tracker state is saved
        entity_tracker.flush()

    # Save final results
    try:
        if not merged_entities:
            logger.error("  ❌ No entities were processed successfully. Cannot create output CSV.")
            logger.error(f"  Total rows in input: {total_rows}, Successfully processed: 0")
            return

        merged_df = pd.DataFrame(merged_entities)

        # Verify expected columns exist
        required_columns = [
            'root_entity_id', 'entity_name', 'entity_type', 'entity_category',
            'entity_identification', 'merged_description', 'merged_aliases', 'merged_quotes', 'merged_references',
            'merged_locations', 'merged_entity_ids', 'merged_keywords',
            'document_titles', 'collections', 'books', 'years', 'genres', 'file_paths', 'occurrence_count'
        ]

        missing_columns = [col for col in required_columns if col not in merged_df.columns]
        if missing_columns:
            logger.error(f"  ❌ Missing expected columns in merged entities: {missing_columns}")
            logger.error(f"  Available columns: {list(merged_df.columns)}")
            return

        merged_df = merged_df[required_columns]
        merged_df.to_csv(output_csv_path, index=False)
        logger.info(f"  💾 Final results saved to '{output_csv_path}'")

        # Clear checkpoint only if processing completed successfully
        if not failed_entities or len(merged_entities) == total_rows:
            checkpoint_manager.clear_checkpoint()
            entity_tracker.clear()
            logger.info("✅ Processing completed successfully. Checkpoints cleared.")
    except Exception as e:
        logger.error(f"  ❌ Failed to save final results: {str(e)}")
    
    total_duration = (datetime.now() - start_time).total_seconds()
    success_rate = len(merged_entities) / total_rows * 100 if total_rows > 0 else 0
    
    logger.info("\n" + "="*60)
    logger.info("📊 ENTITY PROCESSING SUMMARY")
    logger.info("="*60)
    logger.info(f"⏱️  Total processing time: {total_duration:.2f}s")
    logger.info(f"✅ Successfully processed: {len(merged_entities)}/{total_rows} entities")
    logger.info(f"📈 Success rate: {success_rate:.1f}%")
    logger.info(f"❌ Failed entities: {len(failed_entities)}")
    logger.info(f"🔄 API key switches: {api_key_manager.switch_attempts}")
    logger.info(f"🔑 Final API key: {api_key_manager.current_key}")
    logger.info(f"📊 Total tracked entity IDs: {entity_tracker.get_count()}")
    
    if total_rows > 0:
        logger.info(f"⚡ Average time per entity: {total_duration/total_rows:.2f}s")
    
    if failed_entities:
        logger.info(f"🚫 Failed entity IDs: {[f['entity_id'] for f in failed_entities[:10]]}")  # Show first 10
        if len(failed_entities) > 10:
            logger.info(f"   ... and {len(failed_entities) - 10} more")
    
    logger.info("="*60)
    logger.info("🎉 Entity processing complete!")