from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from typing import Optional, Type

def get_llm(provider: str, model_name: str, temperature: float = 0.0, structured_output_schema: Optional[Type[BaseModel]] = None):
    """
    Returns a language model instance based on the specified provider and model name.

    Args:
        provider (str): The LLM provider ("openai" or "google").
        model_name (str): The name of the model to use.
        temperature (float): The temperature for the LLM.
        structured_output_schema (Optional[Type[BaseModel]]): The Pydantic model for structured output.

    Returns:
        An instance of a language model, potentially with structured output configured.
    """
    if provider.lower() == "openai":
        llm = ChatOpenAI(model=model_name, temperature=temperature)
    elif provider.lower() == "google":
        llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    else:
        raise ValueError(f"Unsupported provider: {provider}. Use 'openai' or 'google'.")
    
    if structured_output_schema:
        return llm.with_structured_output(structured_output_schema)
    
    return llm 