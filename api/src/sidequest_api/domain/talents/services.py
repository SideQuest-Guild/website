"""Talent trees from Battle.net (cached in-process; never stored), and members' saved talent builds.

Battle.net's talent-tree index groups class and specialization trees by a shared ``tree_id`` embedded in each
entry's link (``/talent-tree/{tree_id}[/playable-specialization/{spec_id}]``); there is no direct lookup by class
name, so :func:`get_class_talents` parses it once per class and keeps the built trees in ``_tree_cache`` for the
life of the process (classic talent trees never change between Battle.net calls; a process restart picks up any
patch).

A build's ``code`` is validated against the live trees before it is ever stored: each tree's digits, in order,
must fit the node's max rank, respect prerequisites (a node needs its ``requires`` node at max rank first) and row
gating (row ``r`` opens once ``TALENT_ROW_POINTS * (r - 1)`` points are spent elsewhere in that tree), and the
build's total must not exceed ``MAX_TALENT_POINTS``.
"""

import asyncio
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT, HTTP_503_SERVICE_UNAVAILABLE
from sqlalchemy import func, select
from wow import WowError

from sidequest_common.models import Member, TalentBuild
from sidequest_common.schemas import (
    MAX_TALENT_BUILDS,
    MAX_TALENT_POINTS,
    TALENT_ROW_POINTS,
    ClassTalents,
    TalentBuildCreate,
    TalentBuildSchema,
    TalentNode,
    TalentRank,
    TalentTreeSchema,
    WowClass,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient
    from wow.models import TalentTree, TalentTreeNode

BATTLENET_UNREACHABLE = "Battle.net did not answer; try again in a minute"
_TREE_HREF = re.compile(r"/talent-tree/(\d+)$")
_SPEC_HREF = re.compile(r"/talent-tree/(\d+)/playable-specialization/(\d+)$")

_tree_cache: dict[str, ClassTalents] = {}
TREE_ROWS = 7
TREE_COLUMNS = 4


def _node_schema(node: TalentTreeNode, rows: dict[int, int], first_col: int) -> TalentNode:
    """One talent node, with its prerequisite.

    Battle.net links some prerequisite pairs both ways in ``locked_by``; the prerequisite is the one in an earlier row.
    """
    first = node.ranks[0].tooltip.talent
    return TalentNode(
        id=node.id,
        row=node.display_row,
        col=node.display_col - first_col + 1,
        max_rank=len(node.ranks),
        talent_id=first.id,
        name=first.name or "",
        ranks=[
            TalentRank(spell_id=rank.tooltip.spell_tooltip.spell.id, description=rank.tooltip.spell_tooltip.description)
            for rank in node.ranks
        ],
        requires=next(
            (other for other in node.locked_by if rows.get(other, node.display_row) < node.display_row), None
        ),
    )


def _tree_schema(tree: TalentTree, icon_url: str | None) -> TalentTreeSchema:
    """One spec's tree, with columns counted from 1.

    Battle.net numbers columns across the whole class window (the three trees sit side by side, e.g. 1-4, 7-10 and
    14-17), so each tree's columns are shifted to start at 1; order within a tree is unchanged.

    Battle.net also lists a few stray copies far outside the window (a second Lightning Reflexes at column 170, Holy
    Specialization at row 33); the game doesn't show them, so neither does the calculator.
    """
    first_col = min((node.display_col for node in tree.spec_talent_nodes), default=1)
    nodes = sorted(
        (
            node
            for node in tree.spec_talent_nodes
            if 1 <= node.display_row <= TREE_ROWS and 0 <= node.display_col - first_col < TREE_COLUMNS
        ),
        key=lambda node: (node.display_row, node.display_col),
    )
    rows = {node.id: node.display_row for node in nodes}
    return TalentTreeSchema(
        spec_id=tree.playable_specialization.id,
        name=tree.name,
        icon_url=icon_url,
        nodes=[_node_schema(n, rows, first_col) for n in nodes],
    )


async def _spec_icon_url(spec_id: int, game_data: AsyncClient) -> str | None:
    try:
        media = await game_data.playable_specializations.media(spec_id)
    except WowError:
        return None
    return next((asset.value for asset in media.assets if asset.key == "icon"), None)


async def get_class_talents(wow_class: WowClass, game_data: AsyncClient) -> ClassTalents:
    """The class's three talent trees, built from Battle.net and cached for the life of the process."""
    cached = _tree_cache.get(wow_class.value)
    if cached is not None:
        return cached
    try:
        index = await game_data.talent_trees.index()
    except WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    class_name = wow_class.value.capitalize()
    # Links carry a ``?namespace=...`` query, so match on the URL path only.
    tree_id = next(
        (
            int(match.group(1))
            for entry in index.class_talent_trees
            if entry.name == class_name and (match := _TREE_HREF.search(urlsplit(entry.key.href).path))
        ),
        None,
    )
    if tree_id is None:
        msg = f"No talent tree for class {wow_class.value}"
        raise NotFoundException(msg)
    spec_ids = [
        int(match.group(2))
        for entry in index.spec_talent_trees
        if (match := _SPEC_HREF.search(urlsplit(entry.key.href).path)) and int(match.group(1)) == tree_id
    ]
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [
                (
                    group.create_task(game_data.talent_trees.get(tree_id, spec_id)),
                    group.create_task(_spec_icon_url(spec_id, game_data)),
                )
                for spec_id in spec_ids
            ]
    except* WowError as exc:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=BATTLENET_UNREACHABLE) from exc
    trees = [_tree_schema(tree.result(), icon.result()) for tree, icon in tasks]
    result = ClassTalents(wow_class=wow_class, trees=trees)
    _tree_cache[wow_class.value] = result
    return result


def validate_build_code(class_talents: ClassTalents, code: str) -> None:
    """Checks ``code`` against the live trees: digit count, max rank, prerequisites, row gating and point total.

    Raises ``HTTPException`` (400) with a plain-English reason on the first rule it breaks.
    """
    segments = code.split("-")
    if len(segments) != len(class_talents.trees):
        msg = f"A {class_talents.wow_class.value} build needs {len(class_talents.trees)} tree segments, separated by -"
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
    total = 0
    for tree, segment in zip(class_talents.trees, segments, strict=True):
        if not re.fullmatch(r"[0-9]*", segment):
            msg = f"{tree.name}'s talent code may only hold digits"
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
        if len(segment) > len(tree.nodes):
            msg = f"{tree.name} doesn't have that many talent nodes"
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
        ranks = [int(digit) for digit in segment] + [0] * (len(tree.nodes) - len(segment))
        spent_by_id = dict(zip((node.id for node in tree.nodes), ranks, strict=True))
        for node, rank in zip(tree.nodes, ranks, strict=True):
            if rank == 0:
                continue
            if rank > node.max_rank:
                msg = f"{node.name} only has {node.max_rank} ranks"
                raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
            spent_before_row = sum(r for n, r in zip(tree.nodes, ranks, strict=True) if n.row < node.row)
            if spent_before_row < TALENT_ROW_POINTS * (node.row - 1):
                msg = f"{tree.name}'s row {node.row} isn't open yet \u2014 spend more points in earlier rows first"
                raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
            if node.requires is not None:
                prereq = next(n for n in tree.nodes if n.id == node.requires)
                if spent_by_id.get(node.requires, 0) < prereq.max_rank:
                    msg = f"{node.name} needs {prereq.name} at max rank first"
                    raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)
        total += sum(ranks)
    if total > MAX_TALENT_POINTS:
        msg = f"A build can't spend more than {MAX_TALENT_POINTS} points in total"
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=msg)


class TalentBuildsRepository(SQLAlchemyAsyncRepository[TalentBuild]):
    """Talent build persistence."""

    model_type = TalentBuild


class TalentBuildsService(SQLAlchemyAsyncRepositoryService[TalentBuild]):
    """Saved talent builds: a member's own, and the ones officers pin for raids."""

    repository_type = TalentBuildsRepository

    @staticmethod
    def _to_schema(build: TalentBuild, member_name: str) -> TalentBuildSchema:
        return TalentBuildSchema(
            id=build.id,
            wow_class=WowClass(build.wow_class),
            name=build.name,
            code=build.code,
            note=build.note,
            pinned=build.pinned,
            member_id=build.member_id,
            member_name=member_name,
            created_at=build.created_at,
        )

    async def list_for_member(self, member: Member) -> list[TalentBuildSchema]:
        """``member``'s own saved builds across every class, newest first."""
        session: AsyncSession = self.repository.session
        builds = (
            (
                await session.execute(
                    select(TalentBuild)
                    .where(TalentBuild.member_id == member.id)
                    .order_by(TalentBuild.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [self._to_schema(build, member.display_name) for build in builds]

    async def list_pinned(self, wow_class: WowClass) -> list[TalentBuildSchema]:
        """The officer-pinned raid builds for ``wow_class``, newest first."""
        session: AsyncSession = self.repository.session
        rows = (
            await session.execute(
                select(TalentBuild, Member)
                .join(Member, Member.id == TalentBuild.member_id)
                .where(TalentBuild.wow_class == wow_class.value, TalentBuild.pinned == True)  # noqa: E712
                .order_by(TalentBuild.created_at.desc())
            )
        ).all()
        return [self._to_schema(build, member.display_name) for build, member in rows]

    async def create_for_member(
        self, member: Member, data: TalentBuildCreate, game_data: AsyncClient
    ) -> TalentBuildSchema:
        """Validates ``data.code`` against the live trees, then saves it. 409 once the member holds 20 builds."""
        class_talents = await get_class_talents(data.wow_class, game_data)
        validate_build_code(class_talents, data.code)
        session: AsyncSession = self.repository.session
        count = (
            await session.execute(
                select(func.count()).select_from(TalentBuild).where(TalentBuild.member_id == member.id)
            )
        ).scalar_one()
        if count >= MAX_TALENT_BUILDS:
            msg = f"You can save at most {MAX_TALENT_BUILDS} talent builds; delete one first"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        build = await self.create(
            TalentBuild(
                member_id=member.id, wow_class=data.wow_class.value, name=data.name, code=data.code, note=data.note
            ),
            auto_commit=True,
        )
        return self._to_schema(build, member.display_name)

    async def delete_own(self, member: Member, build_id: UUID) -> None:
        """Deletes ``build_id``, 404 unless it belongs to ``member``."""
        build = await self.get_one_or_none(id=build_id, member_id=member.id)
        if build is None:
            msg = f"No talent build {build_id}"
            raise NotFoundException(msg)
        await self.delete(build.id, auto_commit=True)

    async def set_pinned(self, build_id: UUID, *, pinned: bool) -> TalentBuildSchema:
        """Pins or unpins a build for raids. 404 if it doesn't exist."""
        session: AsyncSession = self.repository.session
        row = (
            await session.execute(
                select(TalentBuild, Member)
                .join(Member, Member.id == TalentBuild.member_id)
                .where(TalentBuild.id == build_id)
            )
        ).first()
        if row is None:
            msg = f"No talent build {build_id}"
            raise NotFoundException(msg)
        build, member = row
        build.pinned = pinned
        build = await self.update(build, auto_commit=True)
        return self._to_schema(build, member.display_name)
