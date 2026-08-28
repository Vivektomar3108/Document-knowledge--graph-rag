from langchain_community.document_loaders import PyPDFLoader
from dotenv import load_dotenv
import os
import glob
import logging

load_dotenv(override=True)

LLAMAPARSE_API_KEY = os.getenv("LLAMAPARSE_API_KEY")

def load_pdf_text(pdf_path, used_llamaparse):
    """
    Loads a PDF file and returns the concatenated text content.
    Caches extracted text in parsed_pdf_content to avoid reprocessing.
    Handles errors gracefully and logs them. Returns an empty string on failure.
    """
    import hashlib
    try:
        # Prepare cache directory and file path
        cache_dir = "parsed_pdf_content"
        os.makedirs(cache_dir, exist_ok=True)
        pdf_basename = os.path.basename(pdf_path)
        # Use hash to avoid issues with duplicate names or special chars
        pdf_hash = hashlib.md5(pdf_path.encode('utf-8')).hexdigest()
        cache_filename = f"{os.path.splitext(pdf_basename)[0]}_{pdf_hash}.txt"
        cache_path = os.path.join(cache_dir, cache_filename)

        # If cached file exists, load and return its content
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_text = f.read()
                logging.info(f"Loaded cached text for {pdf_path} from {cache_path}")
                return cached_text
            except Exception as e:
                logging.error(f"Failed to read cached file {cache_path}: {str(e)}. Will reprocess PDF.")

        # Otherwise, process the PDF as before
        if not used_llamaparse:
            loader = PyPDFLoader(pdf_path)
            response = loader.load()
            borges_text = ""
            for i in response:
                borges_text += i.page_content
        else:
            from llama_cloud_services import LlamaParse
            parser = LlamaParse(
                    api_key=LLAMAPARSE_API_KEY,
                    parse_mode="parse_page_with_lvm",
                    vendor_multimodal_model_name="openai-gpt-4-1",
                    system_prompt_append="When parsing, identify and repair text fragmentation caused by footnotes",
                    verbose=True,
                    result_type="markdown"
                )
            documents = parser.load_data(pdf_path)
            borges_text = ""
            for doc in documents:
                borges_text += doc.text
        # Save the extracted text to cache
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(borges_text)
            logging.info(f"Saved extracted text for {pdf_path} to {cache_path}")
        except Exception as e:
            logging.error(f"Failed to write cache file {cache_path}: {str(e)}")
        return borges_text
    except FileNotFoundError:
        logging.error(f"PDF file not found: {pdf_path}. Returning empty string.")
    except PermissionError:
        logging.error(f"Permission denied when opening {pdf_path}. Returning empty string.")
    except Exception as e:
        logging.error(f"Failed to load PDF text from {pdf_path}: {str(e)}", exc_info=True)
    return ""

def get_pdf_files(pdf_dir):
    """
    Returns a list of PDF file paths in the given directory. Handles errors and logs them.
    """
    try:
        pdf_pattern = os.path.join(pdf_dir, "*.pdf")
        logging.info(f"Searching for PDF files using pattern: {pdf_pattern}")
        pdf_files = glob.glob(pdf_pattern)
        if not pdf_files:
            logging.error(f"No PDF files found in directory: {pdf_dir}")
            return []
        logging.info(f"Found {len(pdf_files)} PDF files in {pdf_dir}:")
        for pdf in pdf_files:
            logging.info(f"  - {os.path.basename(pdf)}")
        return pdf_files
    except Exception as e:
        logging.error(f"Error finding PDF files in {pdf_dir}: {str(e)}", exc_info=True)
        return []

def load_pdf_and_metadata(pdf_path, used_llamaparse):
    """
    Loads PDF text and metadata, returns (document_name, pdf_text, metadata_dict).
    Handles errors and logs them. Returns (None, None, None) on failure.

    For PDFs, XML-specific fields (document_title, publication_year, genre) are empty.
    Path structure metadata is still extracted.
    """
    try:
        from xml_utils import extract_path_metadata

        pdf_basename = os.path.basename(pdf_path)
        document_name = os.path.splitext(pdf_basename)[0].replace(" ", "_")
        logging.info(f"Loading text from PDF: {pdf_path}")
        pdf_text = load_pdf_text(pdf_path, used_llamaparse)

        # Extract path metadata (same as XML)
        metadata = extract_path_metadata(pdf_path)

        # PDF-specific: set XML fields to empty
        metadata.update({
            'document_title': '',
            'publication_year': '',
            'genre': ''
        })

        logging.info(f"Successfully loaded text and metadata for {pdf_basename} - length: {len(pdf_text)} characters")
        logging.debug(f"PDF metadata: {metadata}")

        return document_name, pdf_text, metadata
    except FileNotFoundError:
        logging.error(f"PDF file not found: {pdf_path}. Skipping.")
    except PermissionError:
        logging.error(f"Permission denied when opening {pdf_path}. Skipping.")
    except Exception as e:
        logging.error(f"Failed to load PDF text from {pdf_path}: {str(e)}", exc_info=True)
    return None, None, None
