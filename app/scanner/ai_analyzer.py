from __future__ import annotations
import asyncio
import json
import logging
from time import monotonic
from openai import AsyncOpenAI
from app.config import Settings
from app.domain import CandidateAnalysis

class AIAnalyzer:
    """Optional narrative analysis. Deterministic filters and score remain authoritative."""
    def __init__(self,settings:Settings):
        self.settings=settings
        self.client=AsyncOpenAI(api_key=settings.ai_api_key,base_url=settings.ai_base_url) if settings.ai_enabled and settings.ai_api_key else None
        self._disabled_until=0.0

    @property
    def available(self)->bool:
        return self.client is not None and monotonic()>=self._disabled_until

    def _disable_temporarily(self)->None:
        self._disabled_until=monotonic()+self.settings.ai_failure_cooldown_seconds

    async def close(self)->None:
        if self.client is not None:
            await self.client.close()

    async def analyze(self,analysis:CandidateAnalysis)->str|None:
        if not self.available:return None
        try:
            payload=analysis.model_dump(mode="json",exclude={"ai_summary"})
            response=await asyncio.wait_for(self.client.chat.completions.create(model=self.settings.ai_model,temperature=0.1,messages=[{"role":"system","content":"Analyze only the supplied JSON. Never infer missing facts. Explicitly write 'Data unavailable' for missing information. The deterministic score is authoritative. Return concise sections: Summary, Bullish factors, Bearish factors, Risk factors, Missing information, Market context, Reason passed, Confidence."},{"role":"user","content":json.dumps(payload)}]),timeout=self.settings.ai_timeout_seconds)
            content=response.choices[0].message.content if response.choices else None
            if not content:
                raise ValueError("AI provider returned no text")
            return content.strip()
        except Exception:
            self._disable_temporarily()
            logging.exception("AI_PROVIDER_UNAVAILABLE",extra={"model":self.settings.ai_model,"cooldown_seconds":self.settings.ai_failure_cooldown_seconds})
            return None
