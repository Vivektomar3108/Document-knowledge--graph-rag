"""
Description Validation Utilities

This module provides post-processing validation for merged entity descriptions
to detect and remove duplicate information.
"""

import re
from typing import List, Tuple, Optional
import numpy as np
from logger import setup_logger
from langchain_community.callbacks.manager import get_openai_callback

logger = setup_logger(__name__)

# Import cost tracking utilities
from cost_tracking_utils import TokenUsageStats

# Module-level stats tracker (can be overridden)
_stats_tracker: Optional[TokenUsageStats] = None

def set_stats_tracker(tracker: Optional[TokenUsageStats]):
    """Set the module-level stats tracker for description validation."""
    global _stats_tracker
    _stats_tracker = tracker

class ValidationConfig:
    """Configuration options for description validation"""
    SEMANTIC_SIMILARITY_THRESHOLD = 0.85
    MIN_SENTENCE_LENGTH = 20
    ENABLE_LLM_QUALITY_CONTROL = True
    LLM_QC_THRESHOLD = 0.8  # If cleaned text is <80% of original, use LLM QC
    
    # Identification-Description duplicate detection thresholds
    IDENTIFICATION_HIGH_SIMILARITY_THRESHOLD = 0.80  # Remove definitely
    IDENTIFICATION_MEDIUM_SIMILARITY_THRESHOLD = 0.60  # LLM decides
    IDENTIFICATION_LOW_SIMILARITY_THRESHOLD = 0.40   # Keep definitely


def validate_merged_description(description: str, identification: Optional[str] = None) -> str:
    """
    Main validation pipeline for merged descriptions with identification overlap detection.
    
    Args:
        description: The merged description text to validate
        identification: The entity identification to check for overlaps (optional)
        
    Returns:
        Cleaned description with duplicates removed
    """
    if not description or len(description.strip()) < 10:
        logger.info("Description too short for validation, returning as-is")
        return description
    
    logger.info(f"Validating description of length {len(description)}")
    original_length = len(description)
    
    try:
        # Phase 1: Remove identification duplicates (if identification provided)
        if identification and identification.strip():
            logger.info("Phase 1: Checking for identification-description overlaps")
            description = remove_identification_duplicates(description, identification)
            logger.info(f"After identification deduplication: {len(description)} chars")
        
        # Phase 2: Internal description duplicate detection
        logger.info("Phase 2: Internal description duplicate detection")
        
        # Step 1: Detect exact duplicates
        exact_dupes = detect_exact_duplicates(description)
        logger.info(f"Found {len(exact_dupes)} exact duplicates")
        
        # Step 2: Detect semantic duplicates  
        semantic_dupes = detect_semantic_duplicates(description)
        logger.info(f"Found {len(semantic_dupes)} semantic duplicate pairs")
        
        # Step 3: Remove duplicates
        cleaned_description = remove_duplicates(description, exact_dupes, semantic_dupes)
        
        # Phase 3: LLM quality control (if significant changes made)
        if (ValidationConfig.ENABLE_LLM_QUALITY_CONTROL and 
            len(cleaned_description) < original_length * ValidationConfig.LLM_QC_THRESHOLD):
            logger.info("Phase 3: Significant changes detected, applying LLM quality control")
            cleaned_description = llm_quality_control(cleaned_description, identification)
        
        logger.info(f"Validation complete. Length reduced from {original_length} to {len(cleaned_description)}")
        return cleaned_description
        
    except Exception as e:
        logger.error(f"Error during description validation: {str(e)}", exc_info=True)
        # Return original description if validation fails
        return description


def remove_identification_duplicates(description: str, identification: str) -> str:
    """
    Remove sentences from description that duplicate identification content.
    
    Uses a three-tier approach:
    - High similarity (>0.8): Remove automatically
    - Medium similarity (0.6-0.8): Use LLM to decide
    - Low similarity (<0.6): Keep automatically
    
    Args:
        description: The description text to clean
        identification: The identification text to compare against
        
    Returns:
        Description with identification duplicates removed
    """
    if not description or not identification:
        return description
    
    # Split description into sentences
    sentences = re.split(r'[.!?]+', description)
    sentences = [s.strip() for s in sentences if s.strip() and len(s) > 10]
    
    if len(sentences) < 1:
        return description
    
    try:
        from sentence_transformers import SentenceTransformer
        
        # Load embedding model
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Get embeddings for identification and all description sentences
        identification_embedding = model.encode([identification])
        sentence_embeddings = model.encode(sentences)
        
        # Calculate similarities
        similarities = []
        for i, sentence_embedding in enumerate(sentence_embeddings):
            similarity = np.dot(identification_embedding[0], sentence_embedding) / (
                np.linalg.norm(identification_embedding[0]) * np.linalg.norm(sentence_embedding)
            )
            similarities.append((i, sentences[i], similarity))
        
        # Categorize sentences based on similarity thresholds
        keep_sentences = []
        medium_similarity_sentences = []
        
        for idx, sentence, similarity in similarities:
            if similarity > ValidationConfig.IDENTIFICATION_HIGH_SIMILARITY_THRESHOLD:
                logger.debug(f"Removing high similarity sentence (sim={similarity:.3f}): {sentence[:50]}...")
                # Remove this sentence (don't add to keep_sentences)
                continue
            elif similarity > ValidationConfig.IDENTIFICATION_MEDIUM_SIMILARITY_THRESHOLD:
                logger.debug(f"Medium similarity sentence (sim={similarity:.3f}): {sentence[:50]}...")
                medium_similarity_sentences.append(sentence)
            else:
                logger.debug(f"Keeping low similarity sentence (sim={similarity:.3f}): {sentence[:50]}...")
                keep_sentences.append(sentence)
        
        # Use LLM to decide on medium similarity sentences
        if medium_similarity_sentences and ValidationConfig.ENABLE_LLM_QUALITY_CONTROL:
            llm_kept_sentences = llm_decide_identification_overlap(
                medium_similarity_sentences, identification
            )
            keep_sentences.extend(llm_kept_sentences)
        else:
            # If LLM not available, err on the side of keeping content
            keep_sentences.extend(medium_similarity_sentences)
        
        # Reconstruct description
        if not keep_sentences:
            logger.warning("All sentences would be removed - keeping original description")
            return description
        
        cleaned_description = '. '.join(keep_sentences)
        if not cleaned_description.endswith('.'):
            cleaned_description += '.'
        
        removed_count = len(sentences) - len(keep_sentences)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} identification-duplicate sentences")
        
        return cleaned_description
        
    except ImportError:
        logger.warning("sentence-transformers not available, skipping identification duplicate detection")
        return description
    except Exception as e:
        logger.error(f"Error in identification duplicate detection: {str(e)}")
        return description


def llm_decide_identification_overlap(sentences: List[str], identification: str) -> List[str]:
    """
    Use LLM to decide which medium-similarity sentences should be kept.
    
    Args:
        sentences: List of sentences that have medium similarity to identification
        identification: The identification text to compare against
        
    Returns:
        List of sentences that should be kept
    """
    try:
        from llm_utils import get_llm
        
        sentences_text = '\n'.join([f"{i+1}. {sentence}" for i, sentence in enumerate(sentences)])
        
        prompt = f"""You are reviewing sentences from an entity description to avoid duplication with the entity's identification.

IDENTIFICATION: {identification}

SENTENCES TO REVIEW:
{sentences_text}

For each numbered sentence, determine if it provides NEW information beyond what's already in the identification, or if it's essentially repeating the same information.

Return only the numbers (separated by commas) of sentences that provide NEW information and should be KEPT. If a sentence essentially repeats identification information, don't include its number.

Example response: 1,3,4
If no sentences should be kept, respond with: NONE

Response:"""
        
        llm = get_llm("openai", "gpt-4.1-nano")

        # Wrap LLM call with cost tracking if tracker is available
        if _stats_tracker is not None:
            with get_openai_callback() as cb:
                response = llm.invoke(prompt)
                result = response.content.strip()

                # Calculate cost using our pricing table (cb.total_cost may be 0 for newer models)
                calculated_cost = _stats_tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens)

                # Track token usage and cost
                _stats_tracker.add_usage(
                    prompt_tokens=cb.prompt_tokens,
                    completion_tokens=cb.completion_tokens,
                    cost=calculated_cost,
                    context="identification_overlap_decision"
                )
                logger.debug(f"  💰 Tokens: {cb.total_tokens}, Cost: ${calculated_cost:.6f}")
        else:
            response = llm.invoke(prompt)
            result = response.content.strip()
        
        if result.upper() == "NONE":
            return []
        
        # Parse the response to get sentence numbers
        try:
            keep_indices = [int(x.strip()) - 1 for x in result.split(',') if x.strip().isdigit()]
            kept_sentences = [sentences[i] for i in keep_indices if 0 <= i < len(sentences)]
            
            logger.info(f"LLM decided to keep {len(kept_sentences)}/{len(sentences)} medium-similarity sentences")
            return kept_sentences
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing LLM response '{result}': {e}")
            # If parsing fails, keep all sentences to be safe
            return sentences
            
    except Exception as e:
        logger.error(f"Error in LLM identification overlap decision: {str(e)}")
        # If LLM fails, keep all sentences to be safe
        return sentences


def detect_exact_duplicates(description: str) -> List[str]:
    """
    Find sentences/phrases that appear multiple times exactly.
    
    Args:
        description: Text to analyze for exact duplicates
        
    Returns:
        List of duplicate sentences/phrases
    """
    # Split into sentences
    sentences = re.split(r'[.!?]+', description)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    seen = {}
    duplicates = []
    
    for sentence in sentences:
        # Normalize: lowercase, remove extra spaces
        normalized = ' '.join(sentence.lower().split())
        if len(normalized) < 10:  # Skip very short fragments
            continue
            
        if normalized in seen:
            duplicates.append(sentence)
        else:
            seen[normalized] = sentence
            
    return duplicates


def detect_semantic_duplicates(description: str, threshold: Optional[float] = None) -> List[Tuple[str, str]]:
    """
    Find semantically similar sentences using embeddings.
    
    Args:
        description: Text to analyze for semantic duplicates
        threshold: Similarity threshold (uses config default if None)
        
    Returns:
        List of tuples containing semantically similar sentence pairs
    """
    if threshold is None:
        threshold = ValidationConfig.SEMANTIC_SIMILARITY_THRESHOLD
    
    # Split into sentences
    sentences = re.split(r'[.!?]+', description)
    sentences = [s.strip() for s in sentences 
                if s.strip() and len(s) > ValidationConfig.MIN_SENTENCE_LENGTH]
    
    if len(sentences) < 2:
        return []
    
    try:
        # Import here to handle missing dependency gracefully
        from sentence_transformers import SentenceTransformer
        
        # Load embedding model (this will be cached by sentence-transformers)
        model = SentenceTransformer('all-MiniLM-L6-v2')
        embeddings = model.encode(sentences)
        
        duplicates = []
        for i in range(len(sentences)):
            for j in range(i + 1, len(sentences)):
                # Calculate cosine similarity
                similarity = np.dot(embeddings[i], embeddings[j]) / (
                    np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[j])
                )
                if similarity > threshold:
                    duplicates.append((sentences[i], sentences[j]))
        
        return duplicates
        
    except ImportError:
        logger.warning("sentence-transformers not available, skipping semantic duplicate detection")
        return []
    except Exception as e:
        logger.error(f"Error in semantic duplicate detection: {str(e)}")
        return []


def remove_duplicates(description: str, exact_dupes: List[str], semantic_dupes: List[Tuple[str, str]]) -> str:
    """
    Remove identified duplicates and reconstruct description.
    
    Args:
        description: Original description text
        exact_dupes: List of exact duplicate sentences
        semantic_dupes: List of semantic duplicate pairs
        
    Returns:
        Description with duplicates removed
    """
    cleaned = description
    
    # Remove exact duplicates (keep first occurrence)
    for duplicate in exact_dupes:
        # Count occurrences
        count = cleaned.count(duplicate)
        if count > 1:
            logger.debug(f"Removing {count-1} occurrences of exact duplicate: {duplicate[:50]}...")
            # Replace all but first occurrence
            first_occurrence = True
            while duplicate in cleaned and count > 1:
                if first_occurrence:
                    # Find position of first occurrence and skip it
                    first_pos = cleaned.find(duplicate)
                    search_start = first_pos + len(duplicate)
                    first_occurrence = False
                else:
                    # Remove subsequent occurrences
                    pos = cleaned.find(duplicate, search_start if 'search_start' in locals() else 0)
                    if pos != -1:
                        cleaned = cleaned[:pos] + cleaned[pos + len(duplicate):]
                        count -= 1
                    else:
                        break
    
    # Remove semantic duplicates (keep longer/more detailed version)
    for sent1, sent2 in semantic_dupes:
        if sent1 in cleaned and sent2 in cleaned:
            if len(sent1) >= len(sent2):
                # Keep sent1, remove sent2
                logger.debug(f"Removing semantic duplicate (shorter): {sent2[:50]}...")
                cleaned = cleaned.replace(sent2, "")
            else:
                # Keep sent2, remove sent1
                logger.debug(f"Removing semantic duplicate (shorter): {sent1[:50]}...")
                cleaned = cleaned.replace(sent1, "")
    
    # Clean up extra spaces and punctuation
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Multiple spaces to single
    cleaned = re.sub(r'\s*\.\s*\.+', '.', cleaned)  # Multiple periods
    cleaned = re.sub(r'\s*,\s*,+', ',', cleaned)  # Multiple commas
    cleaned = re.sub(r'\s+([.!?])', r'\1', cleaned)  # Space before punctuation
    cleaned = re.sub(r'([.!?])\s*([A-Z])', r'\1 \2', cleaned)  # Ensure space after sentence end
    
    return cleaned.strip()


def llm_quality_control(description: str, identification: Optional[str] = None) -> str:
    """
    Final LLM pass to ensure coherent narrative after duplicate removal.
    
    Args:
        description: Description text to review and clean
        identification: Entity identification to avoid duplication with (optional)
        
    Returns:
        LLM-cleaned and coherent description
    """
    try:
        from llm_utils import get_llm
        
        # Include identification context if provided
        identification_context = ""
        if identification and identification.strip():
            identification_context = f"""
ENTITY IDENTIFICATION: {identification}

Important: Do not repeat any information that is already covered in the identification above."""
        
        prompt = f"""Review this description for any remaining duplicate information and ensure it flows coherently. 
Remove any redundant information while preserving all unique facts.
Maintain the neutral, factual tone.
Do not add any new information - only clean and organize existing content.{identification_context}

Description: {description}

Provide only the cleaned description without any additional text or explanation:"""
        
        # Use cheaper model for this cleanup task
        llm = get_llm("openai", "gpt-4.1-mini")

        # Wrap LLM call with cost tracking if tracker is available
        if _stats_tracker is not None:
            with get_openai_callback() as cb:
                response = llm.invoke(prompt)
                cleaned = response.content.strip()

                # Calculate cost using our pricing table (cb.total_cost may be 0 for newer models)
                calculated_cost = _stats_tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens)

                # Track token usage and cost
                _stats_tracker.add_usage(
                    prompt_tokens=cb.prompt_tokens,
                    completion_tokens=cb.completion_tokens,
                    cost=calculated_cost,
                    context="description_quality_control"
                )
                logger.info(f"LLM quality control completed. Tokens: {cb.total_tokens}, Cost: ${calculated_cost:.6f}")
        else:
            response = llm.invoke(prompt)
            cleaned = response.content.strip()
            logger.info("LLM quality control completed")

        return cleaned
        
    except Exception as e:
        logger.error(f"Error in LLM quality control: {str(e)}")
        # Return original description if LLM cleanup fails
        return description