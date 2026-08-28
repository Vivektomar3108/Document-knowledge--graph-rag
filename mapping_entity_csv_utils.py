import pandas as pd
import ast
import logging
from logger import get_logger

logger = get_logger(__name__)

def create_filtered_entity_mapping(unmerged_csv, merged_csv, output_csv):
    """
    Create a mapping CSV between root (unique) entities and their merged children.
    Args:
        unmerged_csv: Path to the original results CSV (with all entities).
        merged_csv: Path to the unique entities CSV (with merged entities).
        output_csv: Path to save the mapping CSV.
    """
    logger.info(f"Reading unmerged CSV: {unmerged_csv}")
    unmerged_df = pd.read_csv(unmerged_csv)
    logger.info(f"Reading merged (unique entities) CSV: {merged_csv}")
    merged_df = pd.read_csv(merged_csv)
    
    unmerged_df['entity_id'] = unmerged_df['entity_id'].astype(str)
    root_entity_ids = []
    root_entity_names = []
    child_entity_ids = []
    child_entity_names = []
    
    logger.info("Processing merged entities for mapping...")
    for _, merged_row in merged_df.iterrows():
        try:
            merged_ids = ast.literal_eval(merged_row['merged_entity_ids'])
        except Exception as e:
            logger.warning(f"Failed to parse merged_entity_ids: {e}. Using as single ID.")
            merged_ids = [merged_row['merged_entity_ids']]
        if merged_ids:
            root_id = str(merged_ids[0])
            root_name = merged_row['entity_name']
            for entity_id in merged_ids:
                entity_id = str(entity_id)
                if entity_id != root_id:
                    child_info = unmerged_df[unmerged_df['entity_id'] == entity_id]
                    if not child_info.empty:
                        child_name = child_info['entity_name'].iloc[0]
                    else:
                        child_name = 'N/A'
                    root_entity_ids.append(root_id)
                    root_entity_names.append(root_name)
                    child_entity_ids.append(entity_id)
                    child_entity_names.append(child_name)
    mapping_df = pd.DataFrame({
        'root_entity_id': root_entity_ids,
        'root_entity_name': root_entity_names,
        'child_entity_id': child_entity_ids,
        'child_entity_name': child_entity_names
    })
    valid_child_ids = set(unmerged_df['entity_id'])
    mapping_df = mapping_df[mapping_df['child_entity_id'].isin(valid_child_ids)]
    mapping_df = mapping_df.drop_duplicates()
    mapping_df = mapping_df.sort_values(by=['root_entity_name', 'child_entity_name'])
    mapping_df.to_csv(output_csv, index=False)
    logger.info(f"Filtered mapping file saved to {output_csv}")
