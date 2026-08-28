import pandas as pd
import ast
import uuid
import logging
import json
from logger import get_logger

logger = get_logger(__name__)

def create_normalized_entity_tables(
    unique_entities_csv_path: str,
    raw_results_csv_path: str,
    output_entities_csv_path: str,
    output_references_csv_path: str
):
    """
    Transforms the unique_entities.csv and raw_results.csv into two normalized tables:
    1. ENTITIES table (entities_normalized.csv)
    2. SOURCES table (sources.csv) - replaces references_locations.csv
    """
    logger.info(f"Starting normalization process...")
    logger.info(f"Reading unique entities from: {unique_entities_csv_path}")
    try:
        df_unique = pd.read_csv(unique_entities_csv_path)
    except FileNotFoundError:
        logger.error(f"File not found: {unique_entities_csv_path}. Aborting normalization.")
        return
    except pd.errors.EmptyDataError:
        logger.error(f"File is empty: {unique_entities_csv_path}. Aborting normalization.")
        return

    logger.info(f"Reading raw results from: {raw_results_csv_path}")
    try:
        df_raw = pd.read_csv(raw_results_csv_path)
    except FileNotFoundError:
        logger.error(f"File not found: {raw_results_csv_path}. Aborting normalization.")
        return
    except pd.errors.EmptyDataError:
        logger.error(f"File is empty: {raw_results_csv_path}. Aborting normalization.")
        return

    # 1. Build mapping from raw entity_id to root_entity_id
    logger.info("Building raw_entity_id to root_entity_id map...")
    raw_to_root_map = {}
    for _, row in df_unique.iterrows():
        root_id = row['root_entity_id']
        raw_to_root_map[root_id] = root_id  # The root_id itself maps to itself
        try:
            # merged_entity_ids is a string representation of a list
            merged_ids_str = row['merged_entity_ids']
            if pd.isna(merged_ids_str) or not merged_ids_str.strip():
                merged_ids = []
            else:
                merged_ids = ast.literal_eval(merged_ids_str)
            
            for merged_id in merged_ids:
                raw_to_root_map[merged_id] = root_id
        except (ValueError, SyntaxError) as e:
            logger.warning(f"Could not parse merged_entity_ids for root_id {root_id}: '{row['merged_entity_ids']}'. Error: {e}")
            continue
    logger.info(f"Built map with {len(raw_to_root_map)} entries.")

    # 2. Prepare SOURCES table (replacing REFERENCES_LOCATIONS)
    logger.info("Preparing SOURCES table...")
    sources_data = []
    for _, row in df_raw.iterrows():
        raw_entity_id = row['entity_id']
        root_entity_id = raw_to_root_map.get(raw_entity_id)

        if not root_entity_id:
            logger.warning(f"Raw entity_id '{raw_entity_id}' not found in root map. Skipping references for it.")
            continue
        
        # Extract metadata from row
        document_name = row.get('document_title', '')
        collection = row.get('collection_name', '')
        book = row.get('book_name', '')
        year = row.get('publication_year', '')
        genre = row.get('genre', '')  # Add genre
        
        try:
            references_list_str = row['references']
            if pd.isna(references_list_str) or not references_list_str.strip():
                extracted_references = []
            else:
                try:
                    extracted_references = json.loads(references_list_str)
                except json.JSONDecodeError:
                    try:
                        extracted_references = ast.literal_eval(references_list_str)
                    except (ValueError, SyntaxError) as e:
                        logger.warning(f"Could not parse 'references' for entity_id {raw_entity_id}: '{references_list_str}'. Error: {e}. Skipping.")
                        continue
            
            if not isinstance(extracted_references, list):
                logger.warning(f"Expected list from 'references' column for entity_id {raw_entity_id}, but got {type(extracted_references)}. Content: {references_list_str}. Skipping.")
                continue

            for ref_item in extracted_references:
                if isinstance(ref_item, dict) and 'text' in ref_item:
                    reference_text = ref_item['text']
                    sources_data.append({
                        'source_id': str(uuid.uuid4()),
                        'entity_id': root_entity_id,
                        'document_name': document_name,
                        'collection': collection,
                        'book': book,
                        'year': year,
                        'genre': genre,
                        'reference_text': reference_text
                    })
                else:
                    logger.warning(f"Malformed reference item for entity_id {raw_entity_id}: {ref_item}. Skipping.")
        except (ValueError, SyntaxError) as e:
            logger.warning(f"Could not parse 'references' for entity_id {raw_entity_id}: '{row['references']}'. Error: {e}. Skipping.")
            continue
        except Exception as e:
            logger.error(f"Unexpected error processing references for entity_id {raw_entity_id}: {e}. Raw references: '{row.get('references', 'N/A')}'. Skipping.")
            continue

    df_sources = pd.DataFrame(sources_data)
    if df_sources.empty:
        logger.warning("No source data was generated. SOURCES table will be empty.")
    else:
        logger.info(f"Generated SOURCES table with {len(df_sources)} rows.")

    # 3. Prepare ENTITIES table (use single KEYWORDS column with key:value format)
    logger.info("Preparing ENTITIES table...")
    # Select columns including merged_keywords (which is now a list)
    entity_columns = [
        'root_entity_id', 'entity_name', 'entity_identification', 'merged_description',
        'entity_type', 'entity_category',
        'merged_keywords',  # Single column with key:value list
        'merged_aliases', 'merged_quotes'  # Keep aliases and quotes
    ]
    
    # Only select columns that exist in df_unique
    existing_columns = [col for col in entity_columns if col in df_unique.columns]
    df_entities = df_unique[existing_columns].copy()
    
    # Rename columns
    rename_map = {
        'root_entity_id': 'ID',
        'entity_name': 'NAME',
        'entity_identification': 'IDENTIFICATION',
        'merged_description': 'DESCRIPTION',
        'merged_keywords': 'KEYWORDS',  # Single column
        'merged_aliases': 'ALIASES',
        'merged_quotes': 'QUOTES'
    }
    df_entities.rename(columns=rename_map, inplace=True)

    # 4. Calculate NUMBER_OF_REFERENCES
    if not df_sources.empty:
        ref_counts = df_sources.groupby('entity_id').size().reset_index(name='NUMBER_OF_REFERENCES')
        df_entities = pd.merge(df_entities, ref_counts, left_on='ID', right_on='entity_id', how='left')
        df_entities.drop(columns=['entity_id'], inplace=True, errors='ignore')
        df_entities['NUMBER_OF_REFERENCES'] = df_entities['NUMBER_OF_REFERENCES'].fillna(0).astype(int)
    else:
        df_entities['NUMBER_OF_REFERENCES'] = 0
        
    logger.info(f"Generated ENTITIES table with {len(df_entities)} rows.")


    # 5. Save output CSVs
    try:
        logger.info(f"Saving ENTITIES table to: {output_entities_csv_path}")
        df_entities.to_csv(output_entities_csv_path, index=False)
        logger.info(f"Saving SOURCES table to: {output_references_csv_path}")
        df_sources.to_csv(output_references_csv_path, index=False)
        logger.info("Normalization process completed successfully.")
    except Exception as e:
        logger.error(f"Error saving normalized CSV files: {e}")