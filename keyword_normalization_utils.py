"""
Keyword Normalization Utilities

This module provides utilities for normalizing the merged_keywords column in entity CSVs.
It handles edge cases where keywords contain comma-separated values that should be split
into separate entries.

Example problematic keyword: 'century:16th,_17th'
Should become: ['century:16th', 'century:17th']
"""

import ast
import pandas as pd
from typing import List, Any
from logger import setup_logger

logger = setup_logger(__name__)


def parse_keywords(x: Any) -> List[str]:
    """
    Parse merged_keywords from various formats to list.

    Handles:
    - NaN/None values
    - Already parsed lists
    - String representations of lists (via ast.literal_eval)

    Args:
        x: The merged_keywords value in any format

    Returns:
        List of keyword strings, or empty list if invalid
    """
    if isinstance(x, list):
        return x
    try:
        if pd.isna(x):
            return []
    except (ValueError, TypeError):
        return []
    try:
        return ast.literal_eval(x)
    except Exception:
        # If it's a string but not a valid list representation, return as-is wrapped in list
        logger.debug(f"Could not parse keywords as list: {x}")
        return []


def normalize_keywords(keywords: List[str]) -> List[str]:
    """
    Expand comma-separated values within keywords.

    Handles malformed keywords like 'century:16th,_17th' by splitting them
    into separate entries: ['century:16th', 'century:17th']

    Args:
        keywords: List of keyword strings

    Returns:
        Expanded list with comma-separated values split into individual entries
    """
    expanded = []

    for kw in keywords:
        # Check if keyword contains comma-underscore pattern and has a colon separator
        if ",_" in kw and ":" in kw:
            # Split into prefix (e.g., 'century') and rest (e.g., '16th,_17th')
            prefix, rest = kw.split(":", 1)
            # Split on comma-underscore pattern
            parts = rest.split(",_")
            # Create separate keyword for each part
            for p in parts:
                expanded.append(f"{prefix}:{p}")
        else:
            # No comma-underscore pattern, keep as-is
            expanded.append(kw)

    return expanded


def sanitize_keywords(keywords: List[str]) -> List[str]:
    """
    Remove duplicate keywords while preserving order.

    Uses a set to track seen keywords and maintains insertion order
    by only adding each unique keyword once.

    Args:
        keywords: List of keyword strings (may contain duplicates)

    Returns:
        List of unique keywords in original order
    """
    seen = set()
    cleaned = []

    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            cleaned.append(kw)

    return cleaned


def normalize_merged_keywords_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply full normalization pipeline to merged_keywords column in a DataFrame.

    Pipeline steps:
    1. Parse keywords from string/list format
    2. Expand comma-separated values
    3. Remove duplicates

    Args:
        df: DataFrame with merged_keywords column

    Returns:
        DataFrame with normalized merged_keywords column
    """
    if 'merged_keywords' not in df.columns:
        logger.warning("No 'merged_keywords' column found in DataFrame. Skipping normalization.")
        return df

    logger.info(f"🔧 Normalizing merged_keywords column for {len(df)} rows")

    # Count rows with comma-underscore pattern before normalization
    original_keywords = df['merged_keywords'].apply(parse_keywords)
    problematic_count = sum(
        any(",_" in kw for kw in keywords)
        for keywords in original_keywords
    )

    if problematic_count > 0:
        logger.info(f"   Found {problematic_count} rows with comma-separated keywords to normalize")

    # Apply normalization pipeline
    df['merged_keywords'] = (
        df['merged_keywords']
        .apply(parse_keywords)
        .apply(normalize_keywords)
        .apply(sanitize_keywords)
    )

    logger.info(f"   ✅ Normalization complete")

    return df


def validate_normalized_keywords(df: pd.DataFrame) -> dict:
    """
    Validate that normalized keywords don't contain problematic patterns.

    Checks for:
    - Comma-underscore patterns in keywords
    - Empty keyword lists
    - Duplicate keywords within a row

    Args:
        df: DataFrame with normalized merged_keywords column

    Returns:
        Dictionary with validation statistics
    """
    if 'merged_keywords' not in df.columns:
        return {"error": "No merged_keywords column found"}

    stats = {
        "total_rows": len(df),
        "rows_with_comma_pattern": 0,
        "rows_with_duplicates": 0,
        "rows_with_empty_keywords": 0,
        "total_keywords": 0
    }

    for idx, row in df.iterrows():
        keywords = parse_keywords(row['merged_keywords'])

        # Check for comma pattern
        if any(",_" in kw for kw in keywords):
            stats["rows_with_comma_pattern"] += 1

        # Check for duplicates
        if len(keywords) != len(set(keywords)):
            stats["rows_with_duplicates"] += 1

        # Check for empty
        if not keywords:
            stats["rows_with_empty_keywords"] += 1

        stats["total_keywords"] += len(keywords)

    return stats
