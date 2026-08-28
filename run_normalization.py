import logging
from normalization_utils import create_normalized_entity_tables

# Configure logging
from logger import setup_logger
logger = setup_logger(__name__)

def main():
    # Replace these paths with your actual file paths
    unique_entities_csv_path = "results/agg_relationships.csv"
    raw_results_csv_path = "results/AUTOBIOGRAPHICAL_NOTES_28p._results_raw_gpt_4_1.csv"
    output_entities_csv_path = "results/entities_normalized_relationships.csv"
    output_references_csv_path = "results/references_locations_relationships.csv"

    # Run the normalization
    create_normalized_entity_tables(
        unique_entities_csv_path=unique_entities_csv_path,
        raw_results_csv_path=raw_results_csv_path,
        output_entities_csv_path=output_entities_csv_path,
        output_references_csv_path=output_references_csv_path
    )

if __name__ == "__main__":
    main() 