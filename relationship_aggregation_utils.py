import pandas as pd
import json
import ast
import logging

logger = logging.getLogger(__name__)

def aggregate_relationships_for_unique_entities(unique_entities_csv_path: str, raw_csv_path: str, output_csv_path: str):
    """
    Aggregates relationships for unique entities after the merging process is complete.

    Args:
        unique_entities_csv_path: Path to the CSV file with unique, merged entities.
        raw_csv_path: Path to the original raw CSV with all entity occurrences and relationships.
        output_csv_path: Path to save the final CSV with aggregated relationships.
    """
    try:
        logger.info(f"Loading unique entities from: {unique_entities_csv_path}")
        unique_df = pd.read_csv(unique_entities_csv_path)
        
        logger.info(f"Loading raw entity data from: {raw_csv_path}")
        raw_df = pd.read_csv(raw_csv_path)

        all_merged_relationships = []

        logger.info("Starting relationship aggregation for each unique entity...")
        for index, unique_row in unique_df.iterrows():
            try:
                primary_occurrence_id = unique_row['root_entity_id']
                merged_occurrence_ids_str = unique_row.get('merged_entity_ids', '[]')
                merged_occurrence_ids = ast.literal_eval(merged_occurrence_ids_str) if merged_occurrence_ids_str else []
                
                all_occurrence_ids = [primary_occurrence_id] + merged_occurrence_ids
            except (ValueError, SyntaxError) as e:
                logger.error(f"Could not parse merged_entity_ids for row {index}: {unique_row['merged_entity_ids']}. Error: {e}")
                all_occurrence_ids = [unique_row.get('root_entity_id')]
            
            associated_rows = raw_df[raw_df['entity_id'].isin(all_occurrence_ids)]
            
            unique_relationships = []
            seen_relationships = set()

            for _, raw_row in associated_rows.iterrows():
                if 'relationships' not in raw_row or pd.isna(raw_row['relationships']):
                    continue
                
                try:
                    relationships_list = json.loads(raw_row['relationships'])
                    
                    for rel in relationships_list:
                        rel_key = (rel.get('relationship_type'), rel.get('target_entity_name'))
                        
                        if rel_key not in seen_relationships:
                            unique_relationships.append(rel)
                            seen_relationships.add(rel_key)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Could not parse relationships JSON for entity_id {raw_row['entity_id']}. Error: {e}. Data: {raw_row['relationships']}")
                    continue
            
            all_merged_relationships.append(json.dumps(unique_relationships, ensure_ascii=False))

        unique_df['merged_relationships'] = all_merged_relationships
        
        cols = unique_df.columns.tolist()
        if 'merged_relationships' in cols:
            try:
                ref_index = cols.index('merged_references')
                cols.insert(ref_index + 1, cols.pop(cols.index('merged_relationships')))
                unique_df = unique_df[cols]
            except ValueError:
                pass

        logger.info(f"Writing final unique entities with aggregated relationships to: {output_csv_path}")
        unique_df.to_csv(output_csv_path, index=False)
        logger.info("Aggregation complete.")

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during relationship aggregation: {e}", exc_info=True) 