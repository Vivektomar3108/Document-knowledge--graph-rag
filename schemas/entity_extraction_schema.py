from pydantic import BaseModel, Field
from typing import List, Optional

class EntityKeywords(BaseModel):
    """Separate keyword fields instead of combined list"""
    century: Optional[str] = Field(None, description="Main century of activity (e.g., '19th', '20th')")
    country: Optional[str] = Field(None, description="Country of origin or main activity")
    literary_period: Optional[str] = Field(None, description="Literary period from controlled list (for authors/literary works)")
    art_period: Optional[str] = Field(None, description="Art period from controlled list (for artists/artworks)")
    historical_period: Optional[str] = Field(None, description="Historical period from controlled list (for historical figures)")
    year: Optional[str] = Field(None, description="Year of first publication/premiere (for works)")
    author: Optional[str] = Field(None, description="Normalized name of the creator (for works)")
    genre: Optional[str] = Field(None, description="Genre from controlled list (for works)")
    geo_type: Optional[str] = Field(None, description="Geographic type from controlled list (for places)")
    institution_type: Optional[str] = Field(None, description="Institution type from controlled list (for institutions)")

class Reference(BaseModel):
    text: str = Field(..., description="The exact quote or paraphrase from the current chunk mentioning the entity")
    category: str = Field(..., description="Type of reference: biographical, criticism, influence, collaboration, mention, discovery, etc. Use 'mention' if unsure.")
    source: str = Field(..., description="Source document name and chunk ID where this reference appears")
    location: Optional[str] = Field(None, description="Approximation of location within chunk (e.g., sentence number if feasible)")
    date: Optional[str] = Field(None, description="When this reference occurred if applicable and mentioned in chunk")

# DEPRECATED: Relationship extraction removed in simplified entity extraction approach
# These classes are kept for backward compatibility but are no longer used in the pipeline
class Relationship(BaseModel):
    relationship_type: str = Field(..., description="The type of relationship from this entity to the target. MUST be from the predefined list in the prompt.")
    target_entity_name: str = Field(..., description="The normalized 'name' of the target entity.")
    evidence_text: Optional[str] = Field(None, description="The specific quote from the chunk that provides evidence for this relationship.")
    relationship_relevance: str = Field("essential", description="Relevance level - choose ONE: 'essential', 'significant', 'contextual'.")

class IndirectReference(BaseModel):
    target: str = Field(..., description="Name of the indirectly referenced entity")
    relationship_type: str = Field(..., description="Type of relationship derived from chunk context")

class BorgesEntity(BaseModel):
    name: str = Field(
        ...,
        description="Normalized name of the entity. For PEOPLE: 'Last Name, First Name (Birth Year - Death Year if known)', otherwise 'Last Name, First Name'. For all other entities, use the most common, complete name."
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="All textual forms, variations, periphrases, or nicknames used in the text to refer to this entity"
    )
    category: str = Field(
        ...,
        description="The main category from the 9 categories: LITERATURE, PHILOSOPHY, HISTORY, GEOGRAPHY, FICTION, ART, CINEMA, RELIGION, SCIENCE"
    )
    entity_type: str = Field(
        ...,
        description="The entity TYPE as per the guidelines: Persona, Obra, Lugar, Institución, Evento, Concepto"
    )
    keywords: EntityKeywords = Field(
        default_factory=EntityKeywords,
        description="Keyword fields with values from controlled lists"
    )
    identification: Optional[str] = Field(
        None,
        description="A concise, objective, encyclopedic identification of the entity followed by a sentence about its relationship to Borges or his work."
    )
    description_from_chunk_summary: Optional[str] = Field(
        None,
        description="A narrative summary of all information and context provided about this entity *within the current text chunk*."
    )
    sources: List[str] = Field(
        default_factory=list,
        description="List of source references where the entity appears (e.g., document names, chunk IDs)"
    )
    quotes: List[str] = Field(
        default_factory=list,
        description="List of exact and representative textual quotes from the current chunk"
    )
    references: List[Reference] = Field(
        default_factory=list,
        description="List of direct quotes or paraphrases from the current text chunk documenting the mention or relationship to this entity."
    )

class BorgesGraphNode(BaseModel):
    entity: BorgesEntity = Field(..., description="An entity related to Borges identified in the chunk")
    
class NewBorgesGraphNodes(BaseModel):
    nodes: List[BorgesGraphNode] = Field(..., description="List of Borges graph nodes extracted from the text chunk. Aim for comprehensiveness.")