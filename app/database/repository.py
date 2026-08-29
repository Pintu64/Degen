from __future__ import annotations
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database.models import Call, Milestone, PriceSnapshot, Token, TokenSnapshotRecord
from app.domain import CandidateAnalysis, Chain, TokenSnapshot

class Repository:
    def __init__(self,session:AsyncSession): self.session=session
    async def upsert_token(self,s:TokenSnapshot)->Token:
        stmt=insert(Token).values(chain=s.chain.value,contract_address=s.contract_address,name=s.name,symbol=s.symbol).on_conflict_do_update(constraint="uq_token_chain_address",set_={"name":s.name,"symbol":s.symbol,"updated_at":func.now()}).returning(Token.id)
        token_id=(await self.session.execute(stmt)).scalar_one(); return await self.session.get(Token,token_id)
    async def create_call(self,a:CandidateAnalysis,milestones:tuple[Decimal,...])->Call:
        s=a.snapshot
        if s.price is None or s.price<=0: raise ValueError("A valid reference price is required")
        token=await self.upsert_token(s); call=Call(token_id=token.id,reference_price=s.price,reference_timestamp=s.timestamp,initial_market_cap=s.market_cap,initial_liquidity=s.liquidity,initial_volume=s.volume_24h,initial_score=a.score.score,initial_risk=a.risk.level.value,initial_snapshot=s.model_dump(mode="json"),status="ACTIVE",current_price=s.price,current_multiple=Decimal("1"),highest_price=s.price,highest_multiple=Decimal("1"),highest_timestamp=s.timestamp)
        self.session.add(call); await self.session.flush()
        self.session.add_all([Milestone(call_id=call.id,target_multiple=m,target_price=s.price*m,status="PENDING") for m in milestones]); await self.session.commit(); return call
    async def active_calls(self)->list[Call]:
        result=await self.session.execute(select(Call).where(Call.status=="ACTIVE").options(selectinload(Call.token),selectinload(Call.milestones)).order_by(Call.id)); return list(result.scalars().unique())
    async def call_history(self,limit:int=50)->list[Call]:
        result=await self.session.execute(select(Call).options(selectinload(Call.token)).order_by(Call.created_at.desc()).limit(limit)); return list(result.scalars().unique())
    async def get_call(self,call_id:int)->Call|None:
        result=await self.session.execute(select(Call).where(Call.id==call_id).options(selectinload(Call.token),selectinload(Call.milestones))); return result.scalar_one_or_none()
    async def has_active_call(self,chain:Chain,address:str)->bool:
        q=select(func.count()).select_from(Call).join(Token).where(Token.chain==chain.value,Token.contract_address==address,Call.status=="ACTIVE"); return (await self.session.scalar(q) or 0)>0
    async def save_token_snapshot(self,token_id:int,s:TokenSnapshot): self.session.add(TokenSnapshotRecord(token_id=token_id,timestamp=s.timestamp,provider=s.provider,payload=s.model_dump(mode="json")))
    async def update_tracking(self,call:Call,s:TokenSnapshot,multiple:Decimal)->list[Milestone]:
        now=s.timestamp; new_high=multiple>call.highest_multiple
        values={"current_price":s.price,"current_multiple":multiple,"updated_at":now}
        if new_high: values.update(highest_price=s.price,highest_multiple=multiple,highest_timestamp=now)
        await self.session.execute(update(Call).where(Call.id==call.id).values(**values))
        self.session.add(PriceSnapshot(call_id=call.id,price=s.price,multiple=multiple,market_cap=s.market_cap,liquidity=s.liquidity,volume=s.volume_24h,timestamp=now,provider=s.provider))
        pending=[m for m in call.milestones if m.status=="PENDING" and call.current_multiple<m.target_multiple<=multiple]
        claimed=[]
        for m in pending:
            result=await self.session.execute(update(Milestone).where(Milestone.id==m.id,Milestone.status=="PENDING").values(status="HIT",hit_price=s.price,hit_timestamp=now).returning(Milestone.id))
            if result.scalar_one_or_none(): m.status="HIT"; m.hit_price=s.price; m.hit_timestamp=now; claimed.append(m)
        await self.session.commit(); return claimed
    async def mark_milestone_sent(self,milestone_id:int,message_id:int):
        await self.session.execute(update(Milestone).where(Milestone.id==milestone_id).values(telegram_message_id=message_id)); await self.session.commit()
    async def mark_call_alert_sent(self,call_id:int,message_id:int):
        await self.session.execute(update(Call).where(Call.id==call_id).values(alert_message_id=message_id)); await self.session.commit()
    async def unsent_milestones(self)->list[Milestone]:
        result=await self.session.execute(select(Milestone).where(Milestone.status=="HIT",Milestone.telegram_message_id.is_(None)).options(selectinload(Milestone.call).selectinload(Call.token)))
        return list(result.scalars().unique())
    async def unsent_call_alerts(self)->list[Call]:
        result=await self.session.execute(select(Call).where(Call.alert_message_id.is_(None)).options(selectinload(Call.token)).order_by(Call.id))
        return list(result.scalars().unique())
    async def cleanup_snapshots(self,days:int)->int:
        result=await self.session.execute(delete(PriceSnapshot).where(PriceSnapshot.timestamp<datetime.now(UTC)-timedelta(days=days))); await self.session.commit(); return result.rowcount or 0
    async def stats(self)->dict:
        calls=(await self.session.execute(select(Call))).scalars().all(); milestones=(await self.session.execute(select(Milestone))).scalars().all()
        aths=[Decimal(c.highest_multiple) for c in calls]; sorted_aths=sorted(aths)
        if not sorted_aths: median=Decimal("0")
        elif len(sorted_aths)%2: median=sorted_aths[len(sorted_aths)//2]
        else:
            middle=len(sorted_aths)//2; median=(sorted_aths[middle-1]+sorted_aths[middle])/Decimal("2")
        return {"total":len(calls),"active":sum(c.status=="ACTIVE" for c in calls),"closed":sum(c.status!="ACTIVE" for c in calls),"average_ath":sum(aths,Decimal("0"))/len(aths) if aths else Decimal("0"),"median_ath":median,"maximum_ath":max(aths,default=Decimal("0")),"below_1x":sum(c.current_multiple<1 for c in calls),"above_1x":sum(c.current_multiple>=1 for c in calls),"milestones":{str(t):sum(m.status=="HIT" and m.target_multiple==t for m in milestones) for t in sorted({m.target_multiple for m in milestones})}}
