"""Knowledge service - loads and serves affiliate marketing knowledge from imported files"""
import os
import logging

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")


class KnowledgeService:
    """Loads and caches affiliate marketing knowledge from Markdown files"""

    _cache = {}

    @classmethod
    def _load(cls, filename: str) -> str:
        if filename in cls._cache:
            return cls._cache[filename]
        filepath = os.path.join(KNOWLEDGE_DIR, filename)
        try:
            with open(filepath, "r") as f:
                content = f.read()
            cls._cache[filename] = content
            return content
        except FileNotFoundError:
            logger.warning(f"Knowledge file not found: {filepath}")
            return ""

    @classmethod
    def get_offer_frameworks(cls) -> str:
        return cls._load("offer-frameworks.md")

    @classmethod
    def get_platform_rules(cls) -> str:
        return cls._load("platform-rules.md")

    @classmethod
    def get_ftc_compliance(cls) -> str:
        return cls._load("ftc-compliance.md")

    @classmethod
    def get_glossary(cls) -> str:
        return cls._load("affiliate-glossary.md")

    @classmethod
    def get_case_studies(cls) -> str:
        return cls._load("case-studies.md")

    @classmethod
    def get_seo_strategy(cls) -> str:
        return cls._load("seo-strategy.md")

    @classmethod
    def get_context_for_script_generation(cls) -> str:
        """Returns combined knowledge relevant for script generation"""
        parts = []

        frameworks = cls.get_offer_frameworks()
        if frameworks:
            parts.append("=== CONVERSION FRAMEWORKS ===\n" + frameworks[:2000])

        compliance = cls.get_ftc_compliance()
        if compliance:
            parts.append("=== FTC COMPLIANCE RULES ===\n" + compliance[:1000])

        platform = cls.get_platform_rules()
        if platform:
            parts.append("=== PLATFORM TACTICS ===\n" + platform[:1000])

        return "\n\n".join(parts) if parts else ""

    @classmethod
    def get_context_for_image_generation(cls) -> str:
        """Returns knowledge relevant for image prompt crafting"""
        cases = cls.get_case_studies()
        if cases:
            return "=== PROVEN AD BENCHMARKS ===\n" + cases[:1500]
        return ""

    @classmethod
    def list_available(cls) -> list:
        """List all available knowledge files"""
        if not os.path.isdir(KNOWLEDGE_DIR):
            return []
        return [f for f in os.listdir(KNOWLEDGE_DIR) if f.endswith(".md")]
