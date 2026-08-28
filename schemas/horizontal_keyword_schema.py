from typing import List
from pydantic import BaseModel, Field

class HorizontalKeywordResult(BaseModel):
    """Represents the horizontal keywords for a single entity."""
    root_entity_id: str = Field(..., description="The unique ID of the entity, matching the input.")
    horizontal_keywords: List[str] = Field(
        default_factory=list,
        description="A list of generated horizontal keywords in 'key:value' format. Returns an empty list if no connection is found."
    )

class HorizontalKeywordsBatchOutput(BaseModel):
    """The complete output for a batch of entities."""
    results: List[HorizontalKeywordResult] = Field(..., description="A list of entities with their generated horizontal keywords.")