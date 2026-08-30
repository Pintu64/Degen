from datetime import UTC, datetime
from decimal import Decimal

class InvalidPrice(ValueError): pass

def validate_price(price: Decimal, timestamp: datetime, max_age_seconds: int, now: datetime | None=None)->None:
    now=now or datetime.now(UTC)
    if not price.is_finite() or price<=0: raise InvalidPrice("Price must be positive and finite")
    if timestamp.tzinfo is None: raise InvalidPrice("Price timestamp must be timezone-aware")
    if (now-timestamp).total_seconds()>max_age_seconds: raise InvalidPrice("Price is stale")

def calculate_multiple(reference:Decimal,current:Decimal)->Decimal:
    if not reference.is_finite() or reference<=0: raise InvalidPrice("Reference price must be positive and finite")
    if not current.is_finite() or current<=0: raise InvalidPrice("Current price must be positive and finite")
    return current/reference

def calculate_drawdown(ath_multiple:Decimal,current_multiple:Decimal)->Decimal:
    if ath_multiple<=0: return Decimal("0")
    return ((current_multiple/ath_multiple)-Decimal("1"))*Decimal("100")

def crossed(previous:Decimal,current:Decimal,target:Decimal)->bool: return previous<target<=current

def is_anomalous(previous:Decimal,current:Decimal,max_jump:Decimal)->bool:
    if not previous.is_finite() or not current.is_finite() or not max_jump.is_finite() or current<=0 or max_jump<=1:
        return True
    return previous>0 and (current/previous>max_jump or previous/current>max_jump)
