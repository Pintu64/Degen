from abc import ABC, abstractmethod
from app.domain import Chain, TokenSnapshot

class ProviderError(RuntimeError): pass

class TokenDiscoveryProvider(ABC):
    name = "base"
    @abstractmethod
    async def discover_tokens(self, chain: Chain) -> list[TokenSnapshot]: ...
    @abstractmethod
    async def get_snapshot(self, chain: Chain, address: str) -> TokenSnapshot | None: ...
