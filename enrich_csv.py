import ast
import re
import json
import pandas as pd
from typing import List, Iterable, Any, Dict

def _parse_to_list(value: Any) -> List[str]:
    """
    Robustly parse a value into a list of strings.
    Supports: JSON lists, Python list repr, comma/semicolon/pipe-separated strings,
    single strings, None/NaN.
    """
    if value is None:
        return []
    # pandas NaN check
    try:
        if pd.isna(value):
            return []
    except Exception:
        pass

    # If already a list/tuple
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if x is not None and str(x).strip()]

    s = str(value).strip()
    if s == "":
        return []

    # Try JSON
    try:
        parsed = json.loads(s)
        if isinstance(parsed, (list, tuple, set)):
            return [str(x).strip() for x in parsed if x is not None and str(x).strip()]
        if isinstance(parsed, str):
            s = parsed  # fall through to separators
    except Exception:
        pass

    # Try python literal (e.g. "['a','b']")
    try:
        parsed = ast.literal_eval(s)
        if isinstance(parsed, (list, tuple, set)):
            return [str(x).strip() for x in parsed if x is not None and str(x).strip()]
        if isinstance(parsed, dict):
            # if dict, try to extract common keys (like 'text' or 'name')
            vals = []
            for k in ['text', 'name', 'value']:
                if k in parsed:
                    vals.append(str(parsed[k]).strip())
            if vals:
                return vals
    except Exception:
        pass

    # Fall back to splitting by common separators
    for sep in [',', ';', '|', '/']:
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if parts:
                return parts

    # Single token
    return [s]

def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

def enrich_merged_csv_with_fields(
    unique_entities_csv_path: str,
    original_csv_path: str,
    output_csv_path: str,
    fields_to_merge: List[str] = None,
    include_root_entity: bool = True,
    merged_ids_col: str = "merged_entity_ids",
    root_id_col: str = "root_entity_id",
    join_for_str: Dict[str,str] = None
):
    """
    Enrich merged CSV rows by fetching and merging specified columns from original CSV rows.

    Args:
        merged_csv_path: path to CSV produced by LLM merging (contains merged_entity_ids).
        original_csv_path: original CSV that has per-entity columns (entity_id, etc).
        output_csv_path: where to save the enriched merged CSV.
        fields_to_merge: list of field names to merge from original CSV. Defaults to empty (no additional merging).
        include_root_entity: whether to include the root_entity_id row when gathering merged parts.
        merged_ids_col: column name in merged CSV containing merged entity ids (a list-like string).
        root_id_col: root id column name in merged CSV.
        join_for_str: dict mapping field -> separator for the `<field>_merged_str` column.
    """
    if fields_to_merge is None:
        fields_to_merge = []  # Changed from ['vertical_keywords'] since keywords are now merged in entity processing
    if join_for_str is None:
        join_for_str = {}

    merged_df = pd.read_csv(unique_entities_csv_path, dtype=str)
    original_df = pd.read_csv(original_csv_path, dtype=str)

    # Ensure entity id column is present in original_df (assumed 'entity_id')
    if 'entity_id' not in original_df.columns:
        raise ValueError("original_csv_path must contain 'entity_id' column")

    # Build lookup dict: entity_id -> row (as dict)
    original_lookup = original_df.set_index('entity_id').to_dict(orient='index')

    enriched_rows = []
    for _, row in merged_df.iterrows():
        # parse merged entity ids
        raw = row.get(merged_ids_col, "")
        merged_ids = []
        if isinstance(raw, list):
            merged_ids = raw
        else:
            raw_s = str(raw)
            # handle empty
            if raw_s.strip() != "":
                try:
                    parsed = ast.literal_eval(raw_s)
                    if isinstance(parsed, (list, tuple, set)):
                        merged_ids = [str(x) for x in parsed]
                    else:
                        # maybe a single id string
                        merged_ids = [str(parsed)]
                except Exception:
                    # maybe JSON
                    try:
                        parsed = json.loads(raw_s)
                        if isinstance(parsed, (list, tuple, set)):
                            merged_ids = [str(x) for x in parsed]
                        else:
                            merged_ids = [str(parsed)]
                    except Exception:
                        # fallback: attempt to split by separators
                        merged_ids = [s.strip() for s in re.split(r'[,\|;]', raw_s) if s.strip()]

        # include root id optionally
        if include_root_entity:
            root_id = row.get(root_id_col)
            if root_id and str(root_id).strip() and root_id not in merged_ids:
                merged_ids = [root_id] + merged_ids

        # Prepare merged field accumulators
        merged_field_values = {f: [] for f in fields_to_merge}

        for eid in merged_ids:
            if eid in original_lookup:
                orig_row = original_lookup[eid]
                for f in fields_to_merge:
                    if f in orig_row:
                        parsed = _parse_to_list(orig_row.get(f))
                        if parsed:
                            merged_field_values[f].extend(parsed)
            else:
                # Missing original row; continue
                continue

        # Deduplicate while preserving order
        for f in fields_to_merge:
            unique_vals = _unique_preserve_order([str(x) for x in merged_field_values[f] if x is not None and str(x).strip()])
            # add two new columns per field
            row[f"{f}_merged_list"] = unique_vals
            sep = join_for_str.get(f, ", ")
            row[f"{f}_merged_str"] = sep.join(unique_vals)

        enriched_rows.append(row)

    # Build enriched DataFrame (preserve original merged_df columns plus new ones)
    enriched_df = pd.DataFrame(enriched_rows)
    # When saving lists to CSV they will be stringified. That's expected; if you want JSON, you can json.dumps the list columns:
    for f in fields_to_merge:
        list_col = f"{f}_merged_list"
        if list_col in enriched_df.columns:
            def safe_dump(x):
                if x is None:
                    return "[]"
                # If already a string, just keep it
                if isinstance(x, str):
                    return x
                # If it's a list/tuple/numpy array
                if isinstance(x, (list, tuple)):
                    return json.dumps([str(i) for i in x])
                try:
                    if pd.isna(x):
                        return "[]"
                except Exception:
                    pass
                # fallback
                return json.dumps([str(x)])
            enriched_df[list_col] = enriched_df[list_col].apply(safe_dump)


    enriched_df.to_csv(output_csv_path, index=False)
    return enriched_df
