"""Wishlists: items members want, and, for officers, who wants an item next to their loot points.

A wish never changes the loot rules or the addon; it only tells officers who wants a drop. Adding an item fetches
it through ``ItemsService`` first, so a wish is always for an item Battle.net knows and its name is stored.
"""

from typing import TYPE_CHECKING

from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import delete, func, select

from sidequest_api.domain.epgp.services import EpgpService
from sidequest_common.models import BattlenetItem, ItemWish, Member
from sidequest_common.schemas import MAX_ITEM_WISHES, ItemWisher, ItemWishSchema

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient

    from sidequest_api.domain.items.services import ItemsService

TRIAL_STATUS = "trial"


class WishlistService:
    """Read and change members' wishlists."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for(self, member: Member) -> list[ItemWishSchema]:
        """``member``'s wishes, newest first, with each item's name, quality and slot."""
        rows = (
            await self._session.execute(
                select(ItemWish, BattlenetItem)
                .join(BattlenetItem, BattlenetItem.item_id == ItemWish.item_id, isouter=True)
                .where(ItemWish.member_id == member.id)
                .order_by(ItemWish.created_at.desc())
            )
        ).all()
        return [
            ItemWishSchema(
                item_id=wish.item_id,
                name=item.name if item else f"Item {wish.item_id}",
                quality=item.quality if item else "COMMON",
                inventory_type_name=item.inventory_type_name if item else "",
                note=wish.note,
                added_at=wish.created_at,
            )
            for wish, item in rows
        ]

    async def save(
        self,
        member: Member,
        item_id: int,
        note: str | None,
        *,
        items_service: ItemsService,
        game_data: AsyncClient,
    ) -> list[ItemWishSchema]:
        """Add ``item_id`` to ``member``'s wishlist, or change its note. 404 for an unknown item, 409 when full."""
        await items_service.get_item(item_id, game_data)
        note = (note or "").strip() or None
        wish = (
            await self._session.execute(
                select(ItemWish).where(ItemWish.member_id == member.id, ItemWish.item_id == item_id)
            )
        ).scalar_one_or_none()
        if wish is None:
            count = (
                await self._session.execute(
                    select(func.count()).select_from(ItemWish).where(ItemWish.member_id == member.id)
                )
            ).scalar_one()
            if count >= MAX_ITEM_WISHES:
                msg = f"A wishlist holds {MAX_ITEM_WISHES} items; remove one first"
                raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
            self._session.add(ItemWish(member_id=member.id, item_id=item_id, note=note))
        else:
            wish.note = note
        await self._session.commit()
        return await self.list_for(member)

    async def remove(self, member: Member, item_id: int) -> None:
        """Take ``item_id`` off ``member``'s wishlist. Nothing happens if it isn't there."""
        await self._session.execute(
            delete(ItemWish).where(ItemWish.member_id == member.id, ItemWish.item_id == item_id)
        )
        await self._session.commit()

    async def wishers(self, item_id: int) -> list[ItemWisher]:
        """Everyone who wants ``item_id``, highest priority (EP/GP) first, then whoever asked first."""
        rows = (
            await self._session.execute(
                select(ItemWish, Member)
                .join(Member, Member.id == ItemWish.member_id)
                .where(ItemWish.item_id == item_id)
            )
        ).all()
        if not rows:
            return []
        standings = {row.member_id: row for row in (await EpgpService(self._session).get_standings()).rows}
        wishers = []
        for wish, member in rows:
            standing = standings.get(member.id)
            wishers.append(
                ItemWisher(
                    member_id=member.id,
                    member_name=member.display_name,
                    note=wish.note,
                    added_at=wish.created_at,
                    ep=standing.ep if standing else 0.0,
                    gp=standing.gp if standing else 0.0,
                    pr=standing.pr if standing else 0.0,
                    trial=standing.trial if standing else member.raid_status == TRIAL_STATUS,
                )
            )
        return sorted(wishers, key=lambda wisher: (-wisher.pr, wisher.added_at))
