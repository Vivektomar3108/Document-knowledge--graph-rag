from langchain_core.prompts import (
    FewShotChatMessagePromptTemplate,
    ChatPromptTemplate
)
from prompts.new_simplified_entity_extraction_prompt import SIMPLIFIED_ENTITY_EXTRACTION_PROMPT

def new_entity_extraction_prompt():
    system = SIMPLIFIED_ENTITY_EXTRACTION_PROMPT
    return ChatPromptTemplate.from_messages(
        [
            ('system', system),
            ('human', '{input}'),
        ]
    )


def build_extraction_prompt(custom_prompt: str = None):
    """Build extraction prompt template.

    Uses custom_prompt when provided (e.g. from the API prompt-management
    endpoint), otherwise falls back to the built-in default.
    """
    system = custom_prompt if custom_prompt else SIMPLIFIED_ENTITY_EXTRACTION_PROMPT
    return ChatPromptTemplate.from_messages(
        [
            ('system', system),
            ('human', '{input}'),
        ]
    )