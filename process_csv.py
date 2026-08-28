import asyncio
import logging
from main import process_existing_csv

# Configure logging
from logger import setup_logger
logger = setup_logger(__name__)

async def main():
    # Define your input CSV file path
    csv_file = "/home/ubuntu/borges_knowledge_graph/results/AUTOBIOGRAPHICAL_NOTES_28p._results_raw_gpt_4_1.csv"
    output_dir = "/home/ubuntu/borges_knowledge_graph/results"
    model_name = "gpt_test_autobiography"

    logger.info(f"Starting processing of CSV file: {csv_file}")
    
    # Call the process_existing_csv function
    results = await process_existing_csv(
        csv_path=csv_file,
        output_dir=output_dir,
        model_name=model_name
    )

    if results:
        logger.info("\n=== PROCESSING SUMMARY ===")
        logger.info(f"Processed CSV file: {results['results_csv']}")
        
        if results['unique_entities']:
            logger.info(f"- Unique entities: {results['unique_entities']}")
        else:
            logger.warning("- Unique entities: Failed to generate")
            
        if results['entity_mapping']:
            logger.info(f"- Entity mapping: {results['entity_mapping']}")
        else:
            logger.warning("- Entity mapping: Failed to generate")
    else:
        logger.error("Processing failed - no results returned.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Processing interrupted by user.")
    except Exception as e:
        logger.error(f"Processing failed with error: {str(e)}", exc_info=True) 