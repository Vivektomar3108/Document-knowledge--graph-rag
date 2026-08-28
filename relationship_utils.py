import csv
import json
import logging

logger = logging.getLogger(__name__)

def create_relationship_csv(input_file_path, output_file_path):
    """
    Processes a CSV file to extract relationships and creates a new CSV 
    with 'Source Entity', 'Relationship', and 'Target Entity' columns.

    Args:
        input_file_path (str): The path to the input CSV file.
        output_file_path (str): The path where the output CSV file will be saved.
    """
    logger.info(f"Creating relationship CSV from '{input_file_path}'...")
    try:
        with open(input_file_path, 'r', newline='', encoding='utf-8') as infile, \
             open(output_file_path, 'w', newline='', encoding='utf-8') as outfile:
            
            reader = csv.DictReader(infile)
            writer = csv.writer(outfile)
            
            writer.writerow(['ID','Source entity', 'Relationship', 'Target entity', 'Relationship Relevance'])
            
            for row in reader:
                source_entity_name = row.get('NAME', '')
                relationships_str = row.get('RELATIONSHIP', '')
                source_entity_id = row.get('ID', '')
                
                if relationships_str and relationships_str.strip().startswith('['):
                    try:
                        relationships_list = json.loads(relationships_str)
                        for rel in relationships_list:
                            relationship_type = rel.get('relationship_type')
                            target_entity_name = rel.get('target_entity_name')
                            relationship_relevance = rel.get('relationship_relevance')
                            
                            if relationship_type and target_entity_name:
                                writer.writerow([source_entity_id, source_entity_name, relationship_type, target_entity_name, relationship_relevance])
                    except json.JSONDecodeError:
                        logger.warning(f"Could not decode JSON for source entity: {source_entity_name}")
        logger.info(f"Relationship CSV created successfully at '{output_file_path}'.")
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file_path}")
    except Exception as e:
        logger.error(f"An error occurred while creating the relationship CSV: {e}") 