def get_entity_merging_prompt():
    return """# Entity Analysis and Merging System

## Your Task
You will analyze a primary entity (with name, description, reference texts, and entity_id) against some potential match candidates (each with their own entity_id, names, descriptions, and reference texts). Your goal is to determine which entities should be merged because they refer to the same real-world entity.

## Input Format
For each analysis task, you will receive:
- **Primary Entity**: 
  - entity_id: A unique identifier for the entity
  - entity_name: Name of the entity
  - entity_identification: Identification of the entity
  - description: Description of the entity
  - references: Reference texts providing contextual information
  - keywords: Keyword metadata fields
- **Match Candidates**: some potential matching entities, each with:
  - entity_id: A unique identifier
  - entity_name: Name of the entity
  - entity_identification: Identification of the entity
  - description: Description of the entity
  - references: Reference texts providing contextual information
  - location: Location data

## Merging Guidelines
- Merge entities only when there is **very high confidence** they refer to the same real-world entity. Base this decision on a holistic analysis of their names, identifications, descriptions, and especially the contextual information provided in their reference texts.
- **CRITICAL: Family Member Distinction Protocol:**
    - NEVER merge family members (father, mother, son, daughter, brother, sister, husband, wife, grandfather, grandmother, cousin, uncle, aunt).
    - Treat any two entities as DISTINCT if one of the following is true:
        * Their names differ in the given names (e.g., "Jorge Luis Borges" vs. "Jorge Guillermo Borges").
        * Their identifications or descriptions explicitly mention a kinship term (e.g., "father of", "mother of", "son of", "grandfather of", "wife of", "daughter of", "spouse of").
        * Their life dates are not overlapping in a plausible way (e.g., one born in 1832, another in 1899).
    - Family members must always remain separate entities even if they share surname, birthplace, or similar references.
- When merging:
  - **`entity_name`**: Generally, use the Primary Entity's name. However, if a Match Candidate offers a more complete, canonical, or commonly accepted version (e.g., full name with dates vs. partial name), select that more representative name.
  - **`merged_description`**: Create a comprehensive description by following this process:
    1. **Extract unique information**: Identify distinct factual statements from each entity's description
    2. **Remove exact duplicates**: Eliminate any repeated phrases, sentences, or identical information
    3. **Remove semantic duplicates**: Identify and merge information that conveys the same meaning in different words
    4. **Synthesize coherently**: Combine the unique information into a single, flowing narrative
    5. **Avoid identification repetition**: Do **not** restate general facts already given in the `Identification`
    6. **Final verification**: Ensure no information appears twice in the final merged description
    Maintain a neutral, narrative style that could stand alone as a factual summary without any redundancy.
  - Include all unique reference texts, separated by newlines.
  - List all unique location strings from the merged entities.
  - **`merged_entity_ids`**: List the `entity_id` values of all Match Candidates that were merged with the Primary Entity. **Crucially, do not include the Primary Entity's `entity_id` in this list.**
  - **Keyword fields**: Merge keyword metadata from all entities. For each keyword field (century, country, literary_period, art_period, historical_period, year, author, genre, geo_type, institution_type), take the first non-empty value with priority to the primary entity.
If, after careful analysis, you determine that none of the Match Candidates confidently refer to the same real-world entity as the Primary Entity, indicate that no merge occurred.

## Output Requirements
- Indicate whether a merge occurred (is_merged: true/false).
- If merged, provide:
  - root_entity_id: The entity_id of the target/primary entity
  - entity_name: The chosen name for the merged entity.
  - merged_description: The combined description in a clear, factual tone.
  - merged_references: All unique reference texts, separated by newlines.
  - merged_locations: A list of unique location strings.
  - merged_entity_ids: A list of entity_id values for all entities merged with the target/primary entity. Do Not Include Primary/Root Entity Id in this list.
  - Separate merged keyword fields:
    * merged_century: Merged century value
    * merged_country: Merged country value
    * merged_literary_period: Merged literary_period value
    * merged_art_period: Merged art_period value
    * merged_historical_period: Merged historical_period value
    * merged_year: Merged year value
    * merged_author: Merged author value
    * merged_genre: Merged genre value
    * merged_geo_type: Merged geo_type value
    * merged_institution_type: Merged institution_type value
  - If not merged, return null for the merged result.
"""