"""
Test script to estimate pipeline cost for XML corpus processing.
Processes 2-3 XML files and generates cost estimation for full corpus.
"""

import os
import sys
import asyncio
from datetime import datetime
from xml_utils import get_xml_files
from main import process_document_directory
from logger import setup_logger

logger = setup_logger(__name__)


async def estimate_xml_corpus_cost():
    """
    Run cost estimation for XML corpus processing.
    """
    print("\n" + "=" * 70)
    print("BORGES KNOWLEDGE GRAPH - XML CORPUS COST ESTIMATION")
    print("=" * 70 + "\n")

    # Configuration
    SAMPLE_DIR = "xmls"  # Directory with 2-3 sample XML files
    FULL_CORPUS_DIR = r"D:\borges knowledge graph\OBRA ENSAYISTICA EN XML\OBRA ENSAYISTICA EN XML"

    # Models used in pipeline
    EXTRACTION_PROVIDER = "openai"
    EXTRACTION_MODEL = "gpt-4.1"
    MERGING_PROVIDER = "openai"
    MERGING_MODEL = "gpt-4.1-mini"

    print(f"Configuration:")
    print(f"  Sample Directory: {SAMPLE_DIR}")
    print(f"  Full Corpus Directory: {FULL_CORPUS_DIR}")
    print(f"  Extraction Model: {EXTRACTION_MODEL}")
    print(f"  Merging Model: {MERGING_MODEL}")
    print()

    # Step 1: Get sample XML files and count characters
    logger.info(f"Scanning sample directory: {SAMPLE_DIR}")
    sample_files = get_xml_files(SAMPLE_DIR)

    if not sample_files:
        logger.error(f"No XML files found in {SAMPLE_DIR}. Exiting.")
        return

    logger.info(f"Found {len(sample_files)} sample XML files")

    # Count characters in sample files
    from xml_utils import load_xml_text
    sample_char_count = 0
    sample_word_count = 0

    print(f"\nSample files to process:")
    for i, f in enumerate(sample_files, 1):
        text = load_xml_text(f)
        char_count = len(text)
        word_count = len(text.split())
        sample_char_count += char_count
        sample_word_count += word_count
        print(f"  {i}. {os.path.basename(f)}")
        print(f"     Characters: {char_count:,}, Words: {word_count:,}")

    print(f"\n  Total Sample Characters: {sample_char_count:,}")
    print(f"  Total Sample Words: {sample_word_count:,}")
    print()

    # Step 2: Create output directory for cost estimation
    output_dir = f"cost_estimation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Step 3: Run pipeline on sample files with cost tracking
    print("\n" + "=" * 70)
    print("PROCESSING SAMPLE FILES...")
    print("=" * 70 + "\n")

    results = await process_document_directory(
        input_dir=SAMPLE_DIR,
        output_dir=output_dir,
        file_type="xml",
        extraction_provider=EXTRACTION_PROVIDER,
        extraction_model=EXTRACTION_MODEL,
        merging_provider=MERGING_PROVIDER,
        merging_model=MERGING_MODEL,
        used_llamaparse=False,
        enable_cost_tracking=True
    )

    if not results:
        logger.error("Pipeline failed to process sample files")
        return

    # Step 4: Count characters in full corpus
    print("\n" + "=" * 70)
    print("COUNTING CHARACTERS IN FULL CORPUS...")
    print("=" * 70 + "\n")

    logger.info(f"Scanning full corpus directory: {FULL_CORPUS_DIR}")
    full_corpus_files = get_xml_files(FULL_CORPUS_DIR)

    if not full_corpus_files:
        logger.warning(f"No XML files found in full corpus directory: {FULL_CORPUS_DIR}")
        logger.warning("Will provide character-based scaling instructions for manual calculation")
        full_corpus_char_count = None
    else:
        logger.info(f"Found {len(full_corpus_files)} XML files in full corpus")
        print(f"Counting characters in {len(full_corpus_files)} files...")

        full_corpus_char_count = 0
        full_corpus_word_count = 0

        for i, xml_file in enumerate(full_corpus_files, 1):
            if i % 100 == 0:
                print(f"  Processed {i}/{len(full_corpus_files)} files...")

            try:
                text = load_xml_text(xml_file)
                full_corpus_char_count += len(text)
                full_corpus_word_count += len(text.split())
            except Exception as e:
                logger.error(f"Error counting characters in {xml_file}: {str(e)}")
                continue

        print(f"\n  Total Full Corpus Characters: {full_corpus_char_count:,}")
        print(f"  Total Full Corpus Words: {full_corpus_word_count:,}")
        print()

    # Step 5: Display cost extrapolation
    print("\n" + "=" * 70)
    print(f"COST ESTIMATION RESULTS")
    print("=" * 70)
    print(f"\nSample Statistics:")
    print(f"  Files: {len(sample_files)}")
    print(f"  Characters: {sample_char_count:,}")
    print(f"  Words: {sample_word_count:,}")
    print()

    if full_corpus_char_count is not None:
        print(f"Full Corpus Statistics:")
        print(f"  Files: {len(full_corpus_files)}")
        print(f"  Characters: {full_corpus_char_count:,}")
        print(f"  Words: {full_corpus_word_count:,}")
        print()

        char_scaling_factor = full_corpus_char_count / sample_char_count
        print(f"Character-based Scaling Factor: {char_scaling_factor:.2f}x")
        print()

    print("Cost reports have been exported to:")
    print(f"  {output_dir}/cost_reports/")
    print()

    if full_corpus_char_count is not None:
        print("To calculate full corpus cost:")
        print(f"1. Open '{output_dir}/cost_reports/pipeline_cost_summary.csv'")
        print(f"2. Find the 'total_cost_usd' value")
        print(f"3. Multiply by character scaling factor: {char_scaling_factor:.2f}")
        print()
        print("Example:")
        print("  If sample cost = $2.50")
        print(f"  Full corpus cost = $2.50 × {char_scaling_factor:.2f} = ${2.50 * char_scaling_factor:.2f}")
    else:
        print("To calculate full corpus cost manually:")
        print(f"1. Count total characters in full corpus directory")
        print(f"2. Calculate scaling factor = (full_corpus_chars / {sample_char_count:,})")
        print(f"3. Open '{output_dir}/cost_reports/pipeline_cost_summary.csv'")
        print(f"4. Multiply 'total_cost_usd' by the scaling factor")

    print()
    print("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(estimate_xml_corpus_cost())
        print("\n✅ Cost estimation complete!")

    except KeyboardInterrupt:
        print("\n\n❌ Cost estimation interrupted by user.")
        logger.info("Cost estimation interrupted by user")

    except Exception as e:
        logger.error(f"Fatal error in cost estimation: {str(e)}", exc_info=True)
        print(f"\n❌ ERROR: {str(e)}")
        print("Check logs for details.")
        sys.exit(1)
