from src.data.models.outbox import Outbox
from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, event: Outbox) -> Outbox:
        self.session.add(event)
        await self.session.flush()
        return event
