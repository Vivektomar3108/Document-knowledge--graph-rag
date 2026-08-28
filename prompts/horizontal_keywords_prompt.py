import json
from langchain_core.prompts import (
    FewShotChatMessagePromptTemplate,
    ChatPromptTemplate
)

def create_horizontal_keywords_prompt():
    """Creates a refined, rule-based few-shot prompt for extracting 'personal_connection' keywords
    that reflect Borges-specific mental associations (observable, subjective, third-party)."""
    
    examples = [
        {
            "input": "Entity:\n- ID: e-123\n- Name: Battle of La Verde\n- Identification: A battle in the Argentine civil wars.\n- Description: Colonel Francisco Borges, Jorge Luis Borges's paternal grandfather, died heroically in this battle.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-123",
                    "horizontal_keywords": ["personal_connection:observable:Borges, Francisco (1833 - 1874)"]
                }]
            })
        },
        {
            "input": "Entity:\n- ID: e-111\n- Name: Edward Lane\n- Identification: An English translator of the most famous version of 'A Thousand and One Nights'.\n- Description: Borges frequently praised Lane's translation for its scholarly precision.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-111",
                    "horizontal_keywords": ["personal_connection:observable:A Thousand and One Nights"]
                }]
            })
        },

        # EXAMPLE 3 (REVISED): Fixes the self-referencing error from the old 'Adrogué' example.
        # This teaches the model that if a connection is purely Borges's own internal feeling with no
        # other entity involved, it should not generate a keyword.
        {
            "input": "Entity:\n- ID: e-555\n- Name: Adrogué\n- Identification: A town in Greater Buenos Aires, Argentina.\n- Description: Adrogué, where the Borges family spent their summers, always evoked a deep sense of nostalgia in his memory.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-555",
                    "horizontal_keywords": []
                }]
            })
        },

        # EXAMPLE 4 (REVISED): Fixes the incorrect 'third_party' classification.
        # This connection is stated by Borges himself, making it observable, not a third-party claim.
        {
            "input": "Entity:\n- ID: e-222\n- Name: Borges, Jorge Guillermo (1874 - 1938)\n- Identification: Father of Jorge Luis Borges.\n- Description: In his autobiography, Borges states that his father's philosophical anarchism was deeply influenced by the writings of Herbert Spencer.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-222",
                    "horizontal_keywords": ["personal_connection:observable:Spencer, Herbert (1820 - 1903)"]
                }]
            })
        },
        
        # EXAMPLE 5 (NEW): Addresses the "Missed Connection" feedback (Haslam/Suárez).
        # Teaches the model to identify significant relationships like marriage.
        {
            "input": "Entity:\n- ID: e-333\n- Name: Haslam, Frances (Fanny)\n- Identification: Mother of Jorge Luis Borges.\n- Description: Frances Haslam's elder sister, Caroline, married Jorge Suárez, an engineer, and settled in Argentina.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-333",
                    "horizontal_keywords": ["personal_connection:observable:Suárez, Jorge"]
                }]
            })
        },

        # EXAMPLE 6 (NEW): Addresses the "Weak/Irrelevant Connection" feedback.
        # Teaches the model to ignore trivial mentions that don't imply a significant bond.
        {
            "input": "Entity:\n- ID: e-444\n- Name: Spanish language\n- Identification: A Romance language.\n- Description: Borges's English-speaking grandmother, Fanny Haslam, spoke Spanish fluently but with a strong foreign accent.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-444",
                    "horizontal_keywords": []
                }]
            })
        },
        {
            "input": "Entity:\n- ID: e-999\n- Name: Burton, Richard Francis (1821 - 1890)\n- Identification: British explorer, writer, and translator known for his translation of 'A Thousand and One Nights'.\n- Description: Burton was best known for his English translation of the 'Arabian Nights'.",
            "output": json.dumps({
                "results": [{
                    "root_entity_id": "e-999",
                    "horizontal_keywords": ["personal_connection:observable:A Thousand and One Nights"]
                }]
    })
}
    ]

    # Example formatting
    example_prompt = ChatPromptTemplate.from_messages([
        ("human", "{input}"),
        ("ai", "{output}")
    ])

    few_shot_prompt = FewShotChatMessagePromptTemplate(
        examples=examples,
        example_prompt=example_prompt,
    )

    # Updated system message
    system_message = """
        You are a precise, rule-based data extraction system. 
        Your task is to identify *significant relationships* between the given entity (Entity A) 
        and other entities (Entity B) explicitly mentioned or clearly implied in the Description.

        Each relationship should be encoded as a Horizontal Keyword (H-key) in the format:
        `personal_connection:<type>:<Target Entity>`

        ---

        ### CRITICAL RULES (Highest Priority)

        1. **Never repeat the main entity (Entity A)** as a connection.
        - If the mentioned entity is identical or a variant of A, skip it.

        2. **Never include 'Borges, Jorge Luis (1899 - 1986)'.**
        - Borges is always implicit; never explicitly connected.

        3. **Extract relationships ONLY if the Description expresses a clear contextual emphasis**, 
        using words or patterns like:
        - *best known for*, *famous for*, *influenced by*, *translated*, *authored*, *wrote*, *fought in*, *married*, *taught by*, *founded*, *collaborated with*, *dedicated to*, *worked on*.

        4. **Relationship types (personal_connection:<subtype>)**
        - `observable` → factual or biographical relationships (family, work, historical, artistic, or intellectual)
        - `subjective` → emotional or memory-based relationships
        - `third_party` → only if clearly attributed to someone else's statement

        ---

        ### CONTEXTUAL SIGNIFICANCE FILTER

        - Keep connections if they reflect an explicit or central relationship.
        - Skip casual or trivial mentions (e.g., “X spoke Spanish,” “Y read a book in French”).
        - Skip purely linguistic or incidental references unless the work *defines* the person's identity (e.g., “best known for his translation of…”).

        ---

        ### EXAMPLES OF WHAT TO KEEP

        - “best known for his translation of *A Thousand and One Nights*” →  
        → `personal_connection:observable:A Thousand and One Nights`

        - “influenced by the writings of Herbert Spencer” →  
        → `personal_connection:observable:Spencer, Herbert (1820 - 1903)`

        - “died heroically in the Battle of La Verde” →  
        → `personal_connection:observable:Battle of La Verde`

        ---

        ### EXAMPLES OF WHAT TO SKIP

        - “spoke Spanish fluently” → trivial language ability → skip
        - “lived in Buenos Aires” → location → skip
        - “studied literature” → concept → skip
        """



    final_prompt = ChatPromptTemplate.from_messages([
        ("system", system_message),
        few_shot_prompt,
        ("human", "Process the following batch of entities and generate horizontal keywords based on the strict rules provided:\n\n{batch_input}")
    ])

    return final_prompt