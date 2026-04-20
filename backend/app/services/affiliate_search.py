"""Affiliate Program Search - searches Affitor directory for affiliate programs"""
import logging
import requests
from typing import Optional
from ..config import settings

logger = logging.getLogger(__name__)

AFFITOR_BASE = "https://list.affitor.com/api/v1"


class AffiliateSearchService:
    """Search and compare affiliate programs via Affitor API"""

    @staticmethod
    def search_programs(
        query: str = "",
        reward_type: str = "",
        tags: str = "",
        min_cookie_days: int = 0,
        sort: str = "trending",
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Search affiliate programs on list.affitor.com"""
        params = {
            "type": "affiliate_program",
            "sort": sort,
            "limit": min(limit, 30),  # Free tier capped at 5, but request more in case they have a key
            "offset": offset,
        }
        if query:
            params["q"] = query
        if reward_type:
            params["reward_type"] = reward_type
        if tags:
            params["tags"] = tags
        if min_cookie_days > 0:
            params["min_cookie_days"] = min_cookie_days

        headers = {}
        # If user has Affitor API key, use it for higher limits
        affitor_key = getattr(settings, 'affitor_api_key', None)
        if affitor_key:
            headers["Authorization"] = f"Bearer {affitor_key}"

        try:
            r = requests.get(
                f"{AFFITOR_BASE}/programs",
                params=params,
                headers=headers,
                timeout=15,
            )

            if r.status_code != 200:
                logger.error(f"Affitor API error: {r.status_code}")
                return {"programs": [], "error": f"API returned {r.status_code}"}

            data = r.json()
            programs = data.get("data", [])

            # Normalize and enrich
            results = []
            for p in programs:
                results.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "slug": p.get("slug"),
                    "url": p.get("url"),
                    "description": p.get("description", ""),
                    "reward_type": p.get("reward_type", ""),
                    "reward_value": p.get("reward_value", ""),
                    "reward_duration": p.get("reward_duration"),
                    "cookie_days": p.get("cookie_days"),
                    "category": p.get("category"),
                    "tags": p.get("tags", []),
                    "stars": p.get("stars_count", 0),
                    "views": p.get("views_count", 0),
                })

            return {
                "programs": results,
                "total": len(results),
                "query": query,
                "tier": data.get("tier", "free"),
            }

        except requests.RequestException as e:
            logger.error(f"Affitor search failed: {e}")
            return {"programs": [], "error": str(e)}

    @staticmethod
    def get_reward_types() -> list:
        return [
            {"id": "cps_recurring", "name": "Recurring Commission", "desc": "Earn every month the customer stays"},
            {"id": "cps_one_time", "name": "One-Time Commission", "desc": "Earn once per sale"},
            {"id": "cps_lifetime", "name": "Lifetime Commission", "desc": "Earn on all future purchases"},
            {"id": "cpl", "name": "Cost Per Lead", "desc": "Earn per signup/trial"},
            {"id": "cpc", "name": "Cost Per Click", "desc": "Earn per click"},
        ]
