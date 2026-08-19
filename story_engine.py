"""Story Engine: Local LLM generation via llama.cpp

Generates a Timeline JSON from a user idea.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .timeline import Timeline

log = logging.getLogger("UltimateDirector.story_engine")

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None
    log.warning("llama-cpp-python is not installed. Local LLM Story Engine will be disabled.")

_SYSTEM_PROMPT = """You are an expert AI Video Director.
Your task is to take a user's story idea and output a valid JSON `Timeline` object.
The JSON must follow this exact structure:

{
  "project_name": "string",
  "fps": 24,
  "shots": [
    {
      "id": "shot_1",
      "duration_seconds": 2.5,
      "prompt": "Highly detailed description of the shot",
      "cast": ["character_name"],
      "camera_movement": "pan right"
    }
  ],
  "cast": [
    {
      "id": "character_name",
      "trigger_word": "character_name",
      "description": "Visual description of the character"
    }
  ],
  "references": []
}

ONLY OUTPUT VALID JSON. DO NOT WRAP IN MARKDOWN BLOCKS OR INCLUDE EXTRA TEXT.
"""

class StoryEngine:
    """Wrapper around llama.cpp to generate Timelines."""
    
    def __init__(
        self, 
        model_path: str, 
        n_ctx: int = 4096, 
        n_gpu_layers: int = -1,
        verbose: bool = False
    ):
        if Llama is None:
            raise RuntimeError("llama-cpp-python is required to use StoryEngine.")
            
        self.llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose
        )
        
    def generate_timeline(
        self, 
        idea: str, 
        max_tokens: int = 2048, 
        temperature: float = 0.7
    ) -> Timeline:
        """Generate a Timeline object from a text idea."""
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Create a video timeline for: {idea}"}
        ]
        
        log.info(f"Generating timeline for idea: {idea}")
        
        response = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False
        )
        
        content = response["choices"][0]["message"]["content"]
        
        # Try to parse the JSON
        try:
            # Clean up potential markdown formatting
            cleaned = content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
                
            data = json.loads(cleaned.strip())
            return Timeline.from_dict(data)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse LLM output as JSON: {e}\nOutput was: {content}")
            raise ValueError("LLM generated invalid JSON.") from e
