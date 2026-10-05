"""Lifecycle-managed Supabase client and best-effort event persistence."""

from typing import Any

from supabase import AsyncClient, create_async_client


class SupabaseService:
    def __init__(self) -> None:
        self.client: AsyncClient | None = None

    async def connect(self, url: str | None, key: str | None) -> None:
        if url and key:
            self.client = await create_async_client(url, key)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.auth.close()
            await self.client.postgrest.aclose()
            self.client = None

    async def persist_event(self, event: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
        if self.client is None:
            return
        await (
            self.client.table("security_events")
            .insert(
                {
                    "event_id": event["event_id"],
                    "source_id": event["source_id"],
                    "event": event,
                    "alerts": alerts,
                }
            )
            .execute()
        )


supabase_service = SupabaseService()
