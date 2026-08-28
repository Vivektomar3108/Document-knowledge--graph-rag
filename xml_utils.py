"""
XML Utilities for Borges Knowledge Graph Project
Handles XML file parsing, text extraction, and caching functionality.
"""

import os
import glob
import hashlib
import xml.etree.ElementTree as ET
from typing import Tuple, List, Optional
from logger import setup_logger

logger = setup_logger(__name__)


def extract_text_from_xml(xml_path: str) -> str:
    """
    Extracts text content from an XML file, preserving structure.
    Handles the specific XML format used in Borges corpus.

    Args:
        xml_path: Path to the XML file

    Returns:
        Concatenated text content from all text elements

    Raises:
        FileNotFoundError: If XML file doesn't exist
        ET.ParseError: If XML is malformed
        Exception: For other parsing errors
    """
    try:
        logger.info(f"Parsing XML file: {xml_path}")

        # Parse the XML file
        tree = ET.parse(xml_path, parser=ET.XMLParser(encoding='latin-1'))
        root = tree.getroot()

        text_parts = []

        # Extract metadata from root attributes if available
        metadata = {}
        if root.attrib:
            metadata = {
                'nombre': root.attrib.get('Nombre', ''),
                'año_pub': root.attrib.get('AñoPub', root.attrib.get('A�oPub', '')),
                'genero': root.attrib.get('Género', root.attrib.get('G�nero', ''))
            }
            logger.debug(f"Extracted metadata: {metadata}")

        # Recursive function to extract text from all elements
        def extract_element_text(element, depth=0):
            """Recursively extract text from XML elements."""
            # Add element's own text
            if element.text and element.text.strip():
                text_parts.append(element.text.strip())

            # Process all child elements
            for child in element:
                extract_element_text(child, depth + 1)

                # Add tail text (text after closing tag)
                if child.tail and child.tail.strip():
                    text_parts.append(child.tail.strip())

        # Extract all text recursively
        extract_element_text(root)

        # Concatenate all text parts with appropriate spacing
        extracted_text = ' '.join(text_parts)

        # Log extraction statistics
        char_count = len(extracted_text)
        word_count = len(extracted_text.split())
        logger.info(f"Successfully extracted {char_count} characters ({word_count} words) from {os.path.basename(xml_path)}")

        return extracted_text

    except FileNotFoundError:
        logger.error(f"XML file not found: {xml_path}")
        raise
    except ET.ParseError as e:
        logger.error(f"XML parsing error in {xml_path}: {str(e)}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error parsing XML {xml_path}: {str(e)}", exc_info=True)
        raise


def load_xml_text(xml_path: str) -> str:
    """
    Loads an XML file and returns the concatenated text content.
    Caches extracted text in parsed_xml_content to avoid reprocessing.
    Handles errors gracefully and logs them. Returns an empty string on failure.

    Args:
        xml_path: Path to the XML file

    Returns:
        Extracted text content or empty string on failure
    """
    try:
        # Prepare cache directory and file path
        cache_dir = "parsed_xml_content"
        os.makedirs(cache_dir, exist_ok=True)

        xml_basename = os.path.basename(xml_path)
        # Use hash to avoid issues with duplicate names or special chars
        xml_hash = hashlib.md5(xml_path.encode('latin-1')).hexdigest()
        cache_filename = f"{os.path.splitext(xml_basename)[0]}_{xml_hash}.txt"
        cache_path = os.path.join(cache_dir, cache_filename)

        # If cached file exists, load and return its content
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='latin-1') as f:
                    cached_text = f.read()
                logger.info(f"Loaded cached text for {xml_path} from {cache_path}")
                return cached_text
            except Exception as e:
                logger.error(f"Failed to read cached file {cache_path}: {str(e)}. Will reprocess XML.")

        # Otherwise, process the XML file
        borges_text = extract_text_from_xml(xml_path)

        # Save the extracted text to cache
        try:
            with open(cache_path, 'w', encoding='latin-1') as f:
                f.write(borges_text)
            logger.info(f"Saved extracted text for {xml_path} to {cache_path}")
        except Exception as e:
            logger.error(f"Failed to write cache file {cache_path}: {str(e)}")

        return borges_text

    except FileNotFoundError:
        logger.error(f"XML file not found: {xml_path}. Returning empty string.")
    except PermissionError:
        logger.error(f"Permission denied when opening {xml_path}. Returning empty string.")
    except ET.ParseError:
        logger.error(f"XML parsing error in {xml_path}. File may be malformed. Returning empty string.")
    except Exception as e:
        logger.error(f"Failed to load XML text from {xml_path}: {str(e)}", exc_info=True)

    return ""


def get_xml_files(xml_dir: str) -> List[str]:
    """
    Returns a list of XML file paths in the given directory and subdirectories.
    Handles errors and logs them.

    Args:
        xml_dir: Directory path to search for XML files

    Returns:
        List of XML file paths, empty list on error
    """
    try:
        logger.info(f"Searching for XML files in directory: {xml_dir}")

        # Search for XML files recursively
        xml_pattern = os.path.join(xml_dir, "**", "*.xml")
        xml_files = glob.glob(xml_pattern, recursive=True)

        if not xml_files:
            logger.warning(f"No XML files found in directory: {xml_dir}")
            return []

        logger.info(f"Found {len(xml_files)} XML files in {xml_dir}")

        # Log first few files as samples
        sample_size = min(5, len(xml_files))
        logger.info(f"Sample files (first {sample_size}):")
        for xml_file in xml_files[:sample_size]:
            logger.info(f"  - {os.path.basename(xml_file)}")

        if len(xml_files) > sample_size:
            logger.info(f"  ... and {len(xml_files) - sample_size} more files")

        return xml_files

    except Exception as e:
        logger.error(f"Error finding XML files in {xml_dir}: {str(e)}", exc_info=True)
        return []


def load_xml_and_metadata(xml_path: str) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    """
    Loads XML text and metadata, returns (document_name, xml_text, metadata_dict).
    Handles errors and logs them. Returns (None, None, None) on failure.

    Args:
        xml_path: Path to the XML file

    Returns:
        Tuple of (document_name, xml_text, metadata_dict) or (None, None, None) on failure

        metadata_dict contains:
        - collection_name: Extracted from path
        - book_name: Extracted from path
        - index_name: Extracted from path
        - document_title: From XML 'Nombre' attribute
        - publication_year: From XML 'AñoPub' attribute
        - genre: From XML 'Género' attribute
        - file_path: Full file path
    """
    try:
        xml_basename = os.path.basename(xml_path)
        # Replace spaces with underscores for document name
        document_name = os.path.splitext(xml_basename)[0].replace(" ", "_")

        logger.info(f"Loading text from XML: {xml_path}")
        xml_text = load_xml_text(xml_path)

        if not xml_text:
            logger.warning(f"No text extracted from {xml_basename}")
            return None, None, None

        # Extract metadata from path structure
        path_metadata = extract_path_metadata(xml_path)

        # Extract metadata from XML attributes
        xml_metadata = get_xml_metadata(xml_path)

        # Merge both metadata sources
        complete_metadata = {**path_metadata, **xml_metadata}

        logger.info(f"Successfully loaded text and metadata for {xml_basename} - length: {len(xml_text)} characters")
        logger.debug(f"Complete metadata: {complete_metadata}")

        return document_name, xml_text, complete_metadata

    except FileNotFoundError:
        logger.error(f"XML file not found: {xml_path}. Skipping.")
    except PermissionError:
        logger.error(f"Permission denied when opening {xml_path}. Skipping.")
    except Exception as e:
        logger.error(f"Failed to load XML text from {xml_path}: {str(e)}", exc_info=True)

    return None, None, None


def extract_path_metadata(file_path: str) -> dict:
    """
    Extract collection, book, and index names from file path.

    Expected path structure:
    - xmls/OBRA ENSAYISTICA EN XML/Atlas/1983.xml
    - pdfs/Collection Name/Book Name/document.pdf

    Args:
        file_path: Path to the file

    Returns:
        Dictionary with path-based metadata:
        {
            'collection_name': str,
            'book_name': str,
            'index_name': str,
            'file_path': str
        }
    """
    try:
        # Normalize path separators
        normalized_path = os.path.normpath(file_path)
        parts = normalized_path.split(os.sep)

        # Extract file name without extension as index_name
        file_name = os.path.basename(file_path)
        index_name = os.path.splitext(file_name)[0].replace(" ", "_")

        # Try to extract book and collection from path
        # Assumes structure: .../collection/book/file.ext
        if len(parts) >= 3:
            book_name = parts[-2]  # Parent directory
            collection_name = parts[-3]  # Grandparent directory
        elif len(parts) == 2:
            book_name = parts[-2]
            collection_name = ""
        else:
            book_name = ""
            collection_name = ""

        metadata = {
            'collection_name': collection_name,
            'book_name': book_name,
            'index_name': index_name,
            'file_path': file_path
        }

        logger.debug(f"Extracted path metadata: {metadata}")
        return metadata

    except Exception as e:
        logger.error(f"Error extracting path metadata from {file_path}: {str(e)}")
        return {
            'collection_name': '',
            'book_name': '',
            'index_name': '',
            'file_path': file_path
        }


def get_xml_metadata(xml_path: str) -> dict:
    """
    Extracts metadata from XML file root attributes with English keys.
    Returns empty dict if metadata cannot be extracted.

    Args:
        xml_path: Path to the XML file

    Returns:
        Dictionary containing XML attribute metadata with English keys
    """
    try:
        tree = ET.parse(xml_path, parser=ET.XMLParser(encoding='latin-1'))
        root = tree.getroot()

        metadata = {
            'document_title': root.attrib.get('Nombre', ''),
            'publication_year': root.attrib.get('AñoPub', root.attrib.get('A�oPub', '')),
            'genre': root.attrib.get('Género', root.attrib.get('G�nero', ''))
        }

        logger.debug(f"Extracted XML metadata from {os.path.basename(xml_path)}: {metadata}")
        return metadata

    except Exception as e:
        logger.error(f"Failed to extract XML metadata from {xml_path}: {str(e)}")
        return {
            'document_title': '',
            'publication_year': '',
            'genre': ''
        }


def validate_xml_file(xml_path: str) -> bool:
    """
    Validates if an XML file is well-formed and readable.

    Args:
        xml_path: Path to the XML file

    Returns:
        True if valid, False otherwise
    """
    try:
        # Check if file exists
        if not os.path.exists(xml_path):
            logger.error(f"XML file does not exist: {xml_path}")
            return False

        # Check if file is readable
        if not os.access(xml_path, os.R_OK):
            logger.error(f"XML file is not readable: {xml_path}")
            return False

        # Try to parse the XML
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Check if root has any content
        if root is None:
            logger.error(f"XML file has no root element: {xml_path}")
            return False

        logger.debug(f"XML file is valid: {xml_path}")
        return True

    except ET.ParseError as e:
        logger.error(f"XML parsing error in {xml_path}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error validating XML file {xml_path}: {str(e)}")
        return False


def get_xml_statistics(xml_files: List[str]) -> dict:
    """
    Generates statistics for a list of XML files.

    Args:
        xml_files: List of XML file paths

    Returns:
        Dictionary containing statistics
    """
    try:
        total_files = len(xml_files)
        valid_files = 0
        total_chars = 0
        total_words = 0

        logger.info(f"Generating statistics for {total_files} XML files...")

        for xml_file in xml_files:
            if validate_xml_file(xml_file):
                valid_files += 1
                try:
                    text = load_xml_text(xml_file)
                    total_chars += len(text)
                    total_words += len(text.split())
                except Exception as e:
                    logger.error(f"Error processing {xml_file} for statistics: {str(e)}")

        stats = {
            'total_files': total_files,
            'valid_files': valid_files,
            'invalid_files': total_files - valid_files,
            'total_characters': total_chars,
            'total_words': total_words,
            'avg_chars_per_file': total_chars // valid_files if valid_files > 0 else 0,
            'avg_words_per_file': total_words // valid_files if valid_files > 0 else 0
        }

        logger.info(f"Statistics generated: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Error generating statistics: {str(e)}")
        return {}
