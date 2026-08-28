from typing import List, Optional
from pydantic import BaseModel, Field

class MergedResult(BaseModel):
    root_entity_id: str = Field(..., description = "The entity_id of the target entity")
    entity_name: str = Field(..., description="The name of the merged entity, typically the target entity's name")
    merged_description: str = Field(..., description="The combined description of the merged entities in a clear, factual tone")
    merged_references: str = Field(..., description="Merged reference text. Every unique reference text should be separated by newlines")
    merged_locations: List[str] = Field(..., description="A list of unique location strings from the merged entities")
    merged_entity_ids: List[str] = Field(..., description="A list of entity_id values for all entities merged with the target entity")
    entity_type: str = Field(..., description="Entity type")
    # Keywords are now merged programmatically in entity_utils.py, not by LLM

class MergedResponse(BaseModel):
    is_merged: bool = Field(..., description="Whether any entities have been merged or not")
    merged_result: Optional[MergedResult] = Field(None, description="The merged entity details if merging occurred, otherwise None")
