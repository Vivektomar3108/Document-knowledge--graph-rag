import csv
import json
import uuid
import os
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any
from schemas.entity_extraction_schema import NewBorgesGraphNodes
import logging
from logger import get_logger

logger = get_logger(__name__)

def create_chunks_csv(chunks_data: List[Dict[str, any]], source_doc_name: str, output_path: str = None):
    """
    Writes chunk information to a CSV file named after the source document.
    Includes document metadata fields.

    Args:
        chunks_data: List of dictionaries containing chunk information and metadata
        source_doc_name: Name of the source document
        output_path: Full path where the CSV should be saved. If None, uses source_doc_name_chunks.csv
    """
    if not chunks_data:
        logger.info("No chunk data to write.")
        return

    filename = output_path if output_path else f"{source_doc_name}_chunks.csv"
    start_time = datetime.now()
    logger.info(f"Writing {len(chunks_data)} chunks to {filename}...")

    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            # Updated fieldnames to include metadata
            fieldnames = [
                'chunk_id', 'file_name', 'chunk_text',
                'collection_name', 'book_name', 'index_name',
                'document_title', 'publication_year', 'genre', 'file_path'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for chunk_info in chunks_data:
                writer.writerow(chunk_info)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Successfully wrote chunks to {filename} in {duration:.2f}s")
    except IOError as e:
        logger.error(f"Error writing chunks CSV: {e}")


def create_results_csv(all_responses: List[NewBorgesGraphNodes], chunks_data: List[Dict[str, Any]], source_doc_name: str, output_path: str = None):
    """
    Writes each entity instance to a single CSV file, conforming to the simplified schema.
    Each row represents one entity and includes its detailed classification,
    and JSON strings for its references and keywords.

    Args:
        all_responses: List of NewBorgesGraphNodes objects from LLM processing.
        chunks_data: List of dictionaries containing chunk metadata.
        source_doc_name: The base name for the output CSV file.
        output_path: Full path where the CSV should be saved.
    """
    if not all_responses:
        logger.info("No responses to process for results CSV.")
        return

    filename = output_path if output_path else f"{source_doc_name}_results_raw.csv"
    start_time = datetime.now()
    logger.info(f"Starting to write entity and relationship results to {filename}...")

    # MODIFIED: Updated fieldnames to match the simplified BorgesEntity schema
    # Removed: entity_relevance, entity_sub_category, relationships, source_document
    # Added: collection_name, book_name, index_name, document_title, publication_year, genre, file_path
    fieldnames = [
        'entity_id',
        'entity_name',
        'aliases',
        'entity_category',
        'entity_type',
        'keywords',  # Back to single column with key:value format
        'entity_identification',
        'entity_description',
        'sources',
        'quotes',
        'references',
        'chunk_id',
        # Document metadata fields
        'collection_name',
        'book_name',
        'index_name',
        'document_title',
        'publication_year',
        'genre',
        'file_path'
    ]

    entity_count = 0
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for chunk_index, response in enumerate(all_responses):
                try:
                    chunk_id = chunks_data[chunk_index]['chunk_id']
                    chunk_metadata = chunks_data[chunk_index]  # Get full chunk data for metadata
                except IndexError:
                    logger.warning(f"Mismatch between responses and chunks_data at index {chunk_index}. Skipping.")
                    continue

                if not isinstance(response, NewBorgesGraphNodes) or not response.nodes:
                    continue

                for node in response.nodes:
                    entity = node.entity

                    # Process References into a JSON string
                    processed_references = []
                    if entity.references:
                        for ref in entity.references:
                            processed_references.append(ref.dict())

                    # Convert keywords object to key:value list format
                    keywords = entity.keywords
                    keywords_list = []
                    for field in ['century', 'country', 'literary_period', 'art_period',
                                  'historical_period', 'year', 'author', 'genre',
                                  'geo_type', 'institution_type']:
                        value = getattr(keywords, field, None)
                        if value:
                            formatted_value = str(value).strip().lower().replace(' ', '_')
                            keywords_list.append(f"{field}:{formatted_value}")
                    
                    row_data = {
                        'entity_id': str(uuid.uuid4()),
                        'entity_name': entity.name,
                        'aliases': json.dumps(entity.aliases, ensure_ascii=False) if entity.aliases else '[]',
                        'entity_category': entity.category or "",
                        'entity_type': entity.entity_type or "",
                        'keywords': json.dumps(sorted(keywords_list), ensure_ascii=False),
                        'entity_identification': entity.identification or "",
                        'entity_description': entity.description_from_chunk_summary or "",
                        'sources': json.dumps(entity.sources, ensure_ascii=False) if entity.sources else '[]',
                        'quotes': json.dumps(entity.quotes, ensure_ascii=False) if entity.quotes else '[]',
                        'references': json.dumps(processed_references, ensure_ascii=False),
                        'chunk_id': chunk_id,
                        # Extract metadata from chunk_metadata
                        'collection_name': chunk_metadata.get('collection_name', ''),
                        'book_name': chunk_metadata.get('book_name', ''),
                        'index_name': chunk_metadata.get('index_name', ''),
                        'document_title': chunk_metadata.get('document_title', ''),
                        'publication_year': chunk_metadata.get('publication_year', ''),
                        'genre': chunk_metadata.get('genre', ''),
                        'file_path': chunk_metadata.get('file_path', '')
                    }
                    writer.writerow(row_data)
                    entity_count += 1

        total_duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Successfully wrote {entity_count} raw entity occurrences to {filename} in {total_duration:.2f}s")

    except IOError as e:
        logger.error(f"Error writing results CSV to {filename}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during CSV creation: {e}", exc_info=True)

async def merge_csv_files(csv_files, output_file):
    """
    Merge multiple CSV files into a single CSV file.
    
    Args:
        csv_files: List of CSV file paths to merge
        output_file: Path for the merged output CSV file
    """
    logger.info(f"Starting merge of {len(csv_files)} CSV files into {output_file}")
    
    # Read each CSV file and store its DataFrame in a list
    dataframes = []
    successful_reads = 0
    
    for filename in csv_files:
        try:
            if not os.path.exists(filename):
                logger.warning(f"File not found: {filename}. Skipping.")
                continue
                
            logger.info(f"Reading CSV file: {filename}")
            df = pd.read_csv(filename)
            logger.info(f"Successfully read {os.path.basename(filename)} with {len(df)} rows")
            dataframes.append(df)
            successful_reads += 1
        except pd.errors.EmptyDataError:
            logger.error(f"CSV file is empty: {filename}. Skipping.")
            continue
        except pd.errors.ParserError as e:
            logger.error(f"CSV parsing error in {filename}: {e}. Skipping.")
            continue
        except Exception as e:
            logger.error(f"Error reading {os.path.basename(filename)}: {str(e)}. Skipping.", exc_info=True)
            continue
    
    # Concatenate all successfully read DataFrames
    if not dataframes:
        logger.error("No CSV files were successfully read. Cannot create merged file.")
        return None
        
    try:
        logger.info(f"Concatenating {len(dataframes)} dataframes...")
        merged_df = pd.concat(dataframes, ignore_index=True)
        logger.info(f"Successfully concatenated data - merged result has {len(merged_df)} rows and {len(merged_df.columns)} columns")
        
        # Save the merged DataFrame to a new CSV file
        try:
            logger.info(f"Saving merged data to: {output_file}")
            merged_df.to_csv(output_file, index=False)
            logger.info(f"Successfully saved merged data containing {len(merged_df)} rows to: {output_file}")
            return output_file
        except PermissionError:
            logger.error(f"Permission denied when writing to {output_file}. Check file permissions.")
            return None
        except OSError as e:
            logger.error(f"OS error when saving merged file to {output_file}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error saving merged file to {output_file}: {str(e)}", exc_info=True)
            return None
    except ValueError as e:
        logger.error(f"ValueError during dataframe concatenation: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during dataframe concatenation: {str(e)}", exc_info=True)
        return None