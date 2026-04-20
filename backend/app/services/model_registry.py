"""Model registry - catalog of all available AI models"""
import os
import json
import logging
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
REGISTRY_PATH = os.path.join(DATA_DIR, "model_registry.json")


class ModelRegistryService:
    _cache = None

    @classmethod
    def _load(cls) -> dict:
        if cls._cache:
            return cls._cache
        try:
            with open(REGISTRY_PATH, "r") as f:
                cls._cache = json.load(f)
            return cls._cache
        except FileNotFoundError:
            logger.warning(f"Model registry not found: {REGISTRY_PATH}")
            return {}

    @classmethod
    def get_all(cls) -> dict:
        registry = cls._load()
        # Annotate with availability based on configured API keys
        key_map = {
            "GEMINI_API_KEY": bool(settings.gemini_api_key),
            "OPENAI_API_KEY": bool(settings.openai_api_key),
            "FAL_API_KEY": bool(settings.fal_api_key),
            "IDEOGRAM_API_KEY": bool(settings.ideogram_api_key),
            "REPLICATE_API_TOKEN": bool(settings.replicate_api_token),
        }

        for category, models in registry.items():
            for model in models:
                req_key = model.get("requires_key", "")
                model["available"] = key_map.get(req_key, False)

        return registry

    @classmethod
    def get_by_category(cls, category: str) -> list:
        return cls.get_all().get(category, [])

    @classmethod
    def get_available_count(cls) -> dict:
        registry = cls.get_all()
        counts = {}
        for category, models in registry.items():
            total = len(models)
            available = sum(1 for m in models if m.get("available"))
            counts[category] = {"total": total, "available": available}
        return counts
