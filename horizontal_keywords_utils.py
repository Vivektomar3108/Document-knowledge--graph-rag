import pandas as pd
from typing import Optional
from llm_utils import get_llm
from prompts.horizontal_keywords_prompt import create_horizontal_keywords_prompt
from schemas.horizontal_keyword_schema import HorizontalKeywordsBatchOutput
from sub_categories_shorter_names_mapping import subcategory_map
from langchain_community.callbacks.manager import get_openai_callback
# --- Logging Configuration ---
from logger import setup_logger
logger = setup_logger(__name__)

# Import cost tracking utilities
from cost_tracking_utils import TokenUsageStats

def clean_horizontal_keywords(entity_name: str, hkeys: list[str]) -> list[str]:
    if not hkeys:
        return []
    clean_list = []
    entity_lower = entity_name.lower()
    for h in hkeys:
        h_clean = h.strip()
        # Skip empty or invalid entries
        if not h_clean or ":" not in h_clean:
            continue
        # Skip self-referential or Borges-related keys
        if entity_lower in h_clean.lower() or "borges, jorge luis" in h_clean.lower():
            continue
        if h_clean not in clean_list:
            clean_list.append(h_clean)
    return clean_list

def map_subcategory(subcat, mapping):
    for long_text, short_text in mapping.items():
        if long_text.lower() in subcat.lower():
            logger.debug(f"long text '{long_text}' mapped to short text '{short_text}' for subcategory '{subcat}'.")
            return short_text
    logger.info(f"long text: {long_text} not found in subcategory mapping for subcategory '{subcat}'. Keeping original.")
    return subcat  # keep original if no match

async def process_csv_for_horizontal_keywords(input_csv_path: str, output_csv_path: str, provider: str, model: str,
                                              batch_size: int = 25, stats_tracker: Optional[TokenUsageStats] = None):
    """
    Reads an aggregated entity CSV, generates rich horizontal keywords in batches, and saves the result.
    This version uses the direct .with_structured_output() method for cleaner code.

    Args:
        stats_tracker: Optional TokenUsageStats instance for cost tracking
    """
    logger.info(f"Starting HORIZONTAL keyword generation for '{input_csv_path}'.")
    logger.info(f"Using model: {provider}/{model} with batch size: {batch_size}.")

    try:
        df = pd.read_csv(input_csv_path)
        if 'merged_description' not in df.columns or 'root_entity_id' not in df.columns:
            logger.error("Input CSV must contain 'root_entity_id' and 'merged_description' columns.")
            return
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_csv_path}")
        return

    # Bind the Pydantic schema directly to the LLM. This is the cleaner pattern.
    structured_llm = get_llm(provider, model, temperature=0.0, structured_output_schema=HorizontalKeywordsBatchOutput)

    prompt = create_horizontal_keywords_prompt()
    
    # The chain is now simpler, without the explicit parser.
    chain = (prompt | structured_llm).with_config(
                {"run_name": f"horizontal_keywords_{provider}_{model}"})
    # --- END OF REFACTORING ---

    all_keywords_map = {}
    total_rows = len(df)
    
    # Process the DataFrame in batches (this loop remains the same)
    for i in range(0, total_rows, batch_size):
        batch_df = df.iloc[i:i+batch_size]
        logger.info(f"Processing batch {i//batch_size + 1}/{(total_rows + batch_size - 1)//batch_size} (rows {i+1}-{min(i+batch_size, total_rows)})...")

        batch_input_list = []
        for _, row in batch_df.iterrows():
            description = str(row.get('merged_description', ''))
            identification = str(row.get('entity_identification', ''))
            if len(description.split()) > 400:
                description = ' '.join(description.split()[:400]) + "..."
            batch_input_list.append(
                f"Entity:\n- ID: {row['root_entity_id']}\n- Name: {row['entity_name']}\n- Identification: {identification}\n- Description: {description}"
            )
        formatted_batch = "\n---\n".join(batch_input_list)

        try:
            # Wrap LLM call with cost tracking for OpenAI models
            if provider.lower() == "openai" and stats_tracker is not None:
                with get_openai_callback() as cb:
                    # The .invoke call now returns the parsed Pydantic object directly
                    response_obj = await chain.ainvoke({"batch_input": formatted_batch})

                    # Calculate cost using our pricing table (cb.total_cost may be 0 for newer models)
                    calculated_cost = stats_tracker.calculate_cost(cb.prompt_tokens, cb.completion_tokens)

                    # Track token usage and cost
                    stats_tracker.add_usage(
                        prompt_tokens=cb.prompt_tokens,
                        completion_tokens=cb.completion_tokens,
                        cost=calculated_cost,
                        context=f"horizontal_keywords_batch_{i//batch_size + 1}"
                    )
                    logger.info(f"  💰 Tokens: {cb.total_tokens} (in: {cb.prompt_tokens}, out: {cb.completion_tokens}), Cost: ${calculated_cost:.6f}")
            else:
                # For non-OpenAI providers or when tracking is disabled
                response_obj = await chain.ainvoke({"batch_input": formatted_batch})

            # The response is already a Pydantic object, not a dict
            for result in response_obj.results:
                root_id = result.root_entity_id
                # Try to find the entity name for this root_id
                match = batch_df.loc[batch_df['root_entity_id'] == root_id, 'entity_name']

                if match.empty:
                    logger.warning(f"⚠️ Skipping unknown root_entity_id: {root_id} (not found in current batch)")
                    continue  # Skip this one safely, don't break the loop

                entity_name = match.values[0]
                cleaned_hkeys = clean_horizontal_keywords(entity_name, result.horizontal_keywords)
                all_keywords_map[root_id] = cleaned_hkeys
         
            logger.info(f"Successfully processed batch {i//batch_size + 1}.")
        except Exception as e:
            logger.error(f"Failed to process batch {i//batch_size + 1}: {e}", exc_info=True)
            for _, row in batch_df.iterrows():
                if row['root_entity_id'] not in all_keywords_map:
                    all_keywords_map[row['root_entity_id']] = ['ERROR_PROCESSING']

    # Map the results back to the DataFrame (this logic remains the same)
    logger.info("Mapping all generated keywords back to the DataFrame.")
    df['horizontal_keywords'] = df['root_entity_id'].map(all_keywords_map)

    df['horizontal_keywords'] = df['horizontal_keywords'].apply(lambda x: str(x) if isinstance(x, list) else str([]))

    df["entity_sub_category"] = df["entity_sub_category"].apply(lambda x: map_subcategory(str(x), subcategory_map))
    # Save the updated DataFrame
    try:
        df.to_csv(output_csv_path, index=False)
        logger.info(f"Successfully saved results with horizontal keywords to '{output_csv_path}'.")
    except IOError as e:
        logger.error(f"Failed to write output CSV file: {e}")
