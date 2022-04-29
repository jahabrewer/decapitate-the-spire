from __future__ import annotations

import copy
import functools
import logging
import os
import pprint
import random
from enum import Enum
from typing import List, Callable, Type, Dict, Optional, TYPE_CHECKING

from decapitate_the_spire.character import MonsterGroup, Sentry, SlaverRed, SlimeBoss, TheGuardian, Cultist, GremlinNob, \
    JawWorm, FungiBeast, Hexaghost, Lagavulin, SlaverBlue, Looter, SpikeSlimeS, AcidSlimeM, AcidSlimeS, SpikeSlimeM, \
    LouseNormal, LouseDefensive, AcidSlimeL, SpikeSlimeL, GremlinWarrior, GremlinThief, GremlinFat, GremlinTsundere, \
    GremlinWizard, Monster
from decapitate_the_spire.event import Event, DebugThrowOnEnterEvent, BigFishEvent

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG, Map, MapCoord
from decapitate_the_spire.rng import Rng
from decapitate_the_spire.room import Room, RestRoom, MonsterRoom, TreasureRoom, MonsterRoomElite, EventRoom, ShopRoom

logger = logging.getLogger(__name__)


class EncounterName(Enum):
    SMALL_SLIMES = 0
    CULTIST = 1
    JAW_WORM = 2
    TWO_LOUSE = 3
    BLUE_SLAVER = 4
    GREMLIN_GANG = 5
    LOOTER = 6
    LARGE_SLIME = 7
    LOTS_OF_SLIMES = 8
    EXORDIUM_THUGS = 9
    EXORDIUM_WILDLIFE = 10
    RED_SLAVER = 11
    THREE_LOUSE = 12
    TWO_FUNGI_BEASTS = 13
    GREMLIN_NOB = 14
    LAGAVULIN = 15
    THREE_SENTRIES = 16
    THE_GUARDIAN = 17
    HEXAGHOST = 18
    SLIME_BOSS = 19
    MUSHROOM_LAIR = 20


class MonsterHelperHelper:
    @classmethod
    def throw_because_unimplemented(cls):
        raise NotImplementedError()

    @classmethod
    def spawn_small_slimes(cls, ctx: CCG.Context):
        if ctx.misc_rng.random_boolean():
            monsters = [SpikeSlimeS(ctx), AcidSlimeM(ctx)]
        else:
            monsters = [AcidSlimeS(ctx), SpikeSlimeM(ctx)]
        return MonsterGroup(ctx, monsters)

    @classmethod
    def get_louse(cls, ctx: CCG.Context):
        return (
            LouseNormal(ctx) if ctx.misc_rng.random_boolean() else LouseDefensive(ctx)
        )

    @classmethod
    def bottom_wildlife(cls, ctx: CCG.Context):
        return MonsterGroup(
            ctx,
            [cls.bottom_get_strong_wildlife(ctx), cls.bottom_get_weak_wildlife(ctx)],
        )

    @classmethod
    def bottom_get_strong_wildlife(cls, ctx: CCG.Context):
        return FungiBeast(ctx) if ctx.misc_rng.random_boolean() else JawWorm(ctx)

    @classmethod
    def bottom_get_weak_wildlife(cls, ctx: CCG.Context):
        i = ctx.misc_rng.random_from_0_to(2)
        if i == 0:
            m = cls.get_louse(ctx)
        elif i == 1:
            m = SpikeSlimeM(ctx)
        elif i == 2:
            m = AcidSlimeM(ctx)
        else:
            raise Exception()
        return m

    @classmethod
    def large_slime(cls, ctx: CCG.Context):
        m = AcidSlimeL(ctx) if ctx.misc_rng.random_boolean() else SpikeSlimeL(ctx)
        return MonsterGroup(ctx, [m])

    @classmethod
    def get_slaver(cls, ctx: CCG.Context):
        return (
            SlaverRed(
                ctx,
            )
            if ctx.misc_rng.random_boolean()
            else SlaverBlue(
                ctx,
            )
        )

    @classmethod
    def bottom_get_strong_humanoid(cls, ctx: CCG.Context):
        i = ctx.misc_rng.random_from_0_to(2)
        if i == 0:
            m = Cultist(ctx)
        elif i == 1:
            m = cls.get_slaver(ctx)
        elif i == 2:
            m = Looter(ctx)
        else:
            raise Exception()
        return m

    @classmethod
    def bottom_humanoid(cls, ctx: CCG.Context):
        return MonsterGroup(
            ctx,
            [cls.bottom_get_weak_wildlife(ctx), cls.bottom_get_strong_humanoid(ctx)],
        )

    @classmethod
    def spawn_gremlins(cls, ctx: CCG.Context):
        gremlin_pool = [
            GremlinWarrior,
            GremlinWarrior,
            GremlinThief,
            GremlinThief,
            GremlinFat,
            GremlinFat,
            GremlinTsundere,
            GremlinWizard,
        ]
        return cls.assemble_from_pool(ctx, gremlin_pool, 4)

    @classmethod
    def assemble_from_pool(
        cls, ctx: CCG.Context, pool: List[Type[Monster]], count: int
    ):
        assert count < len(pool)
        monsters = []
        for i in range(count):
            gremlin_i = ctx.misc_rng.random_from_0_to(len(pool) - 1)
            monsters.append(pool[gremlin_i](ctx))
            del pool[gremlin_i]
        return MonsterGroup(ctx, monsters)

    @classmethod
    def spawn_many_small_slimes(cls, ctx: CCG.Context):
        return MonsterGroup(
            ctx,
            [
                SpikeSlimeS(ctx),
                SpikeSlimeS(ctx),
                SpikeSlimeS(ctx),
                AcidSlimeS(ctx),
                AcidSlimeS(ctx),
            ],
        )


class EventName(Enum):
    ACCURSED_BLACKSMITH = 1
    BONFIRE_ELEMENTALS = 2
    DESIGNER = 3
    DUPLICATOR = 4
    FACE_TRADER = 5
    FOUNTAIN_OF_CLEANSING = 6
    KNOWING_SKULL = 7
    LAB = 8
    NLOTH = 9
    # Skip note for yourself
    SECRET_PORTAL = 10
    THE_JOUST = 11
    WE_MEET_AGAIN = 12
    THE_WOMAN_IN_BLUE = 13
    MUSHROOMS = 14
    COLOSSEUM = 15
    THE_MOAI_HEAD = 16
    DEAD_ADVENTURER = 17
    THE_CLERIC = 18
    BEGGAR = 19
    TOMB_OF_LORD_RED_MASK = 20
    WHEEL_OF_CHANGE = 21
    WINDING_HALLS = 22
    MASKED_BANDITS = 23
    THE_MAUSOLEUM = 24
    SCRAP_OOZE = 25
    MIND_BLOOM = 26
    BACK_TO_BASICS = 27
    VAMPIRES = 28
    MYSTERIOUS_SPHERE = 29
    LIVING_WALL = 30
    CURSED_TOME = 31
    GOLDEN_IDOL = 32
    GOLDEN_WING = 33
    DRUG_DEALER = 34
    NEST = 35
    THE_LIBRARY = 36
    LIARS_GAME = 37
    GOLDEN_SHRINE = 38
    FALLING = 39
    BIG_FISH = 40
    FORGOTTEN_ALTAR = 41
    SENSORY_STONE = 42
    TRANSMOGRIFIER = 43
    WORLD_OF_GOOP = 44
    MATCH_AND_KEEP = 45
    UPGRADE_SHRINE = 46
    PURIFIER = 47
    SHINING_LIGHT = 48
    ADDICT = 49
    GHOSTS = 50


class MapGenerator:
    @classmethod
    def generate_dungeon(cls, height: int, width: int, path_density: int, rng: Rng):
        map = cls.create_nodes(height, width)
        map = cls.create_paths(map, path_density, rng)
        map = cls.filter_redundant_edges_from_row(map)
        return map

    @classmethod
    def create_nodes(cls, height: int, width: int) -> List[List[MapRoomNode]]:
        nodes = []
        for y in range(height):
            row = []
            for x in range(width):
                row.append(MapRoomNode(x, y))
            nodes.append(row)

        return nodes

    @classmethod
    def create_paths(cls, nodes: List[List[MapRoomNode]], path_density: int, rng: Rng):
        first_starting_node = -1
        # -1 because source doesn't understand counting from 0 -_-
        row_size_kinda = len(nodes[0]) - 1

        for i in range(path_density):
            starting_node = rng.random(0, row_size_kinda)
            if i == 0:
                first_starting_node = starting_node

            while starting_node == first_starting_node and i == 1:
                starting_node = rng.random(0, row_size_kinda)

            cls._create_paths(nodes, MapEdge(starting_node, -1, starting_node, 0), rng)

        return nodes

    @classmethod
    def _create_paths(  # noqa: C901
        cls, nodes: List[List[MapRoomNode]], edge: MapEdge, rng: Rng
    ):
        current_node = cls._get_node(edge.dst_x, edge.dst_y, nodes)

        if edge.dst_y + 1 >= len(nodes):
            new_edge = MapEdge(edge.dst_x, edge.dst_y, 3, edge.dst_y + 2)
            current_node.add_edge(new_edge)
            current_node.edges.sort(
                key=functools.cmp_to_key(MapEdge.compare_coordinates)
            )
            return nodes

        row_width = len(nodes[edge.dst_y])
        row_end_node = row_width - 1
        if edge.dst_x == 0:
            min = 0
            max = 1
        elif edge.dst_x == row_end_node:
            min = -1
            max = 0
        else:
            min = -1
            max = 1

        new_edge_x = edge.dst_x + rng.random(min, max)
        new_edge_y = edge.dst_y + 1
        target_node_candidate = cls._get_node(new_edge_x, new_edge_y, nodes)
        min_ancestor_gap = 3
        max_ancestor_gap = 5
        parents = target_node_candidate.get_parents()

        if len(parents) > 0:
            for parent in parents:
                if parent != current_node:
                    ancestor = cls.get_common_ancestor(
                        parent, current_node, max_ancestor_gap
                    )
                    if ancestor:
                        ancestor_gap = new_edge_y - ancestor.y
                        if ancestor_gap < min_ancestor_gap:
                            if target_node_candidate.x > current_node.x:
                                new_edge_x = edge.dst_x + rng.random(-1, 0)
                                if new_edge_x < 0:
                                    new_edge_x = edge.dst_x
                            elif target_node_candidate.x == current_node.x:
                                new_edge_x = edge.dst_x + rng.random(-1, 1)
                                if new_edge_x > row_end_node:
                                    new_edge_x = edge.dst_x - 1
                                elif new_edge_x < 0:
                                    new_edge_x = edge.dst_x + 1
                            else:
                                new_edge_x = edge.dst_x + rng.random(0, 1)
                                if new_edge_x > row_end_node:
                                    new_edge_x = edge.dst_x

                            target_node_candidate = cls._get_node(
                                new_edge_x, new_edge_y, nodes
                            )

        if edge.dst_x != 0:
            right_node = cls._get_node(edge.dst_x - 1, edge.dst_y, nodes)
            if right_node.has_edges():
                left_edge_of_right_node = cls._get_max_edge(right_node.edges)
                if left_edge_of_right_node.dst_x > new_edge_x:
                    new_edge_x = left_edge_of_right_node.dst_x

        if edge.dst_x < row_end_node:
            right_node = cls._get_node(edge.dst_x + 1, edge.dst_y, nodes)
            if right_node.has_edges():
                left_edge_of_right_node = cls._get_min_edge(right_node.edges)
                if left_edge_of_right_node.dst_x < new_edge_x:
                    new_edge_x = left_edge_of_right_node.dst_x

        target_node_candidate = cls._get_node(new_edge_x, new_edge_y, nodes)
        new_edge = MapEdge(edge.dst_x, edge.dst_y, new_edge_x, new_edge_y)
        current_node.add_edge(new_edge)
        sorted(
            current_node.edges, key=functools.cmp_to_key(MapEdge.compare_coordinates)
        )
        target_node_candidate.add_parent(current_node)
        return cls._create_paths(nodes, new_edge, rng)

    @classmethod
    def _get_node(cls, x: int, y: int, nodes: List[List[MapRoomNode]]):
        return nodes[y][x]

    @classmethod
    def get_common_ancestor(cls, a: MapRoomNode, b: MapRoomNode, max_depth: int):
        assert a.y == b.y
        assert a != b

        # Not sure why source compares x to y...
        if a.x < b.y:
            left = a
            right = b
        else:
            left = b
            right = a

        current_y = a.y

        while True:
            if current_y >= 0 and current_y >= a.y - max_depth:
                if len(left.get_parents()) > 0 and len(right.get_parents()) > 0:
                    left = cls.get_node_with_max_x(left.get_parents())
                    right = cls.get_node_with_min_x(right.get_parents())
                    if left == right:
                        return left
                    current_y -= 1
                    continue

            return None

    @classmethod
    def get_node_with_max_x(cls, nodes: List[MapRoomNode]):
        assert len(nodes) > 0

        maxx = nodes[0]
        for node in nodes:
            if node.x > maxx.x:
                maxx = node

        return maxx

    @classmethod
    def get_node_with_min_x(cls, nodes: List[MapRoomNode]):
        assert len(nodes) > 0

        minn = nodes[0]
        for node in nodes:
            if node.x < minn.x:
                minn = node

        return minn

    @classmethod
    def _get_max_edge(cls, edges: List[MapEdge]):
        edges_copy = copy.copy(edges)
        sorted(edges_copy, key=functools.cmp_to_key(MapEdge.compare_coordinates))
        return edges[-1]

    @classmethod
    def _get_min_edge(cls, edges: List[MapEdge]):
        edges_copy = copy.copy(edges)
        sorted(edges_copy, key=functools.cmp_to_key(MapEdge.compare_coordinates))
        return edges[0]

    @classmethod
    def filter_redundant_edges_from_row(cls, map: List[List[MapRoomNode]]):
        existing_edges = []
        delete_list = []

        # This was a tough translation, might be wrong.
        for node in map[0]:
            if not node.has_edges():
                continue

            for e in node.edges:
                for prev_edge in existing_edges:
                    if e.dst_x == prev_edge.dst_x and e.dst_y == prev_edge.dst_y:
                        delete_list.append(e)
                existing_edges.append(e)

            for e in delete_list:
                try:
                    node.edges.remove(e)
                except ValueError:
                    # Source ignores this failure, and it does happen sometimes.
                    ...
            delete_list.clear()

        return map

    @classmethod
    def to_string(cls, mapp: Map, show_room_symbols: bool = False):
        def pad(n: int):
            return " " * n

        left_padding_size = 5
        s = ""

        for row_num in reversed(range(len(mapp))):
            row = mapp[row_num]

            s += f"{os.linesep} {pad(left_padding_size)}"

            for node in row:
                right = "/" if any((e.dst_x > node.x for e in node.edges)) else " "
                mid = "|" if any((e.dst_x == node.x for e in node.edges)) else " "
                left = "\\" if any((e.dst_x < node.x for e in node.edges)) else " "

                s += left + mid + right

            s += f"{os.linesep}{row_num} {pad(left_padding_size - len(str(row_num)))}"

            for node in row:
                node_symbol = " "
                if row_num != len(mapp) - 1:
                    if node.has_edges():
                        node_symbol = node.get_room_symbol(show_room_symbols)
                else:
                    for lower_node in mapp[row_num - 1]:
                        for lower_edge in lower_node.edges:
                            if lower_edge.dst_x == node.x:
                                node_symbol = node.get_room_symbol(show_room_symbols)

                s += f" {node_symbol} "

        return s


class MapEdge:
    def __init__(self, src_x: int, src_y: int, dst_x: int, dst_y: int):
        self.src_x = src_x
        self.src_y = src_y
        self.dst_x = dst_x
        self.dst_y = dst_y

    def __repr__(self):
        return f"Edge ({self.src_x}, {self.src_y}) -> ({self.dst_x}, {self.dst_y})"

    @staticmethod
    def from_coords(src: MapCoord, dst: MapCoord):
        return MapEdge(src[0], src[1], dst[0], dst[1])

    @staticmethod
    def compare_coordinates(a: MapEdge, b: MapEdge):
        if a.dst_x > b.dst_x:
            return 1
        if a.dst_x < b.dst_x:
            return -1
        if a.dst_y > b.dst_y:
            return 1
        if a.dst_y < b.dst_y:
            return -1

        return 0


class RoomTypeAssigner:
    @classmethod
    def assign_row_as_room_type(
        cls, ctx: CCG.Context, row: List[MapRoomNode], room_type: Type[Room]
    ):
        for node in row:
            # Source checks this with if
            assert not node.room
            node.room = room_type(ctx)

    @classmethod
    def distribute_rooms_across_map(
        cls, ctx: CCG.Context, rng: Rng, mapp: Map, room_list: List[Room]
    ):
        node_count = cls.get_connected_non_assigned_node_count(mapp)

        while len(room_list) < node_count:
            room_list.append(MonsterRoom(ctx))

        # Source only warns on this
        assert len(room_list) == node_count

        random.shuffle(room_list, rng.random_float)
        cls.assign_rooms_to_nodes(mapp, room_list)
        logger.debug(f"{len(room_list)} unassigned rooms")

        cls.last_minute_node_checker(ctx, mapp)

    @classmethod
    def get_connected_non_assigned_node_count(cls, mapp: Map):
        count = 0

        for row in mapp:
            for n in row:
                if n.has_edges() and n.room is None:
                    count += 1

        return count

    @classmethod
    def assign_rooms_to_nodes(cls, mapp: Map, room_list: List[Room]):
        for row in mapp:
            for n in row:
                assert n
                if n.has_edges() and n.room is None:
                    room_to_be_set = cls.get_next_room_type_according_to_rules(
                        mapp, n, room_list
                    )
                    if room_to_be_set:
                        room_list.remove(room_to_be_set)
                        n.room = room_to_be_set

    @classmethod
    def get_next_room_type_according_to_rules(
        cls, mapp: Map, node: MapRoomNode, room_list: List[Room]
    ):
        parents = node.get_parents()
        siblings = cls.get_siblings(mapp, node)

        for room_to_be_set in room_list:
            if cls.rule_assignable_to_row(node, room_to_be_set):
                if not cls.rule_parent_matches(
                    parents, room_to_be_set
                ) and not cls.rule_sibling_matches(siblings, room_to_be_set):
                    return room_to_be_set

                if node.y == 0:
                    return room_to_be_set

        return None

    @classmethod
    def get_siblings(cls, mapp: Map, node: MapRoomNode):
        siblings = []

        for parent in node.get_parents():
            for parent_edge in parent.edges:
                sibling_node = mapp[parent_edge.dst_y][parent_edge.dst_x]
                if sibling_node != node:
                    siblings.append(sibling_node)

        return siblings

    @classmethod
    def rule_assignable_to_row(cls, node: MapRoomNode, room_to_be_set: Room):
        if node.y <= 4 and isinstance(room_to_be_set, (RestRoom, MonsterRoomElite)):
            return False

        return node.y < 13 or not isinstance(room_to_be_set, RestRoom)

    @classmethod
    def rule_parent_matches(cls, parents: List[MapRoomNode], room_to_be_set: Room):
        for parent_node in parents:
            parent_room = parent_node.room

            if (
                parent_room is not None
                and isinstance(
                room_to_be_set, (RestRoom, TreasureRoom, ShopRoom, MonsterRoomElite)
            )
                and type(room_to_be_set) == type(parent_room)
            ):
                return True

        return False

    @classmethod
    def rule_sibling_matches(cls, siblings: List[MapRoomNode], room_to_be_set: Room):
        for sibling_node in siblings:
            sibling_room = sibling_node.room

            # Because MonsterRoom is superclass to MonsterRoomBoss, which isn't in the list, check type exactly.
            applicable_room_types = [
                RestRoom,
                MonsterRoom,
                EventRoom,
                MonsterRoomElite,
                ShopRoom,
            ]
            if (
                sibling_room is not None
                and type(room_to_be_set) in applicable_room_types
                and type(room_to_be_set) == type(sibling_room)
            ):
                return True

        return False

    @classmethod
    def last_minute_node_checker(cls, ctx: CCG.Context, mapp: Map):
        for row in mapp:
            for node in row:
                assert node
                if node.has_edges() and node.room is None:
                    logger.debug(f"{node} has no room, setting to MonsterRoom")
                    node.room = MonsterRoom(ctx)


class RoomResult(Enum):
    EVENT = 0
    # ELITE
    TREASURE = 1
    SHOP = 2
    MONSTER = 3


class EventHelper:
    _NAME_TO_EVENT = {
        EventName.BIG_FISH: BigFishEvent,
    }

    @classmethod
    def get_event(cls, ctx: CCG.Context, name: EventName) -> Event:
        event_type = cls._NAME_TO_EVENT.get(name, DebugThrowOnEnterEvent)
        return event_type(ctx)

    CHANCES = {
        RoomResult.TREASURE: 0.02,
        RoomResult.SHOP: 0.03,
        RoomResult.MONSTER: 0.1,
    }

    @staticmethod
    def roll(ctx: CCG.Context):
        roll = ctx.event_rng.random_float()
        cumul_treasure_chance = EventHelper.CHANCES[RoomResult.TREASURE]
        cumul_shop_chance = EventHelper.CHANCES[RoomResult.SHOP] + cumul_treasure_chance
        cumul_monster_chance = (
            EventHelper.CHANCES[RoomResult.MONSTER] + cumul_shop_chance
        )

        if roll < cumul_treasure_chance:
            rolled_room_result = RoomResult.TREASURE
        elif roll < cumul_shop_chance:
            rolled_room_result = RoomResult.SHOP
        elif roll < cumul_monster_chance:
            rolled_room_result = RoomResult.MONSTER
        else:
            rolled_room_result = RoomResult.EVENT

        # TODO tiny chest, juzu

        if rolled_room_result == RoomResult.MONSTER:
            EventHelper.CHANCES[RoomResult.MONSTER] = 0.1
        else:
            EventHelper.CHANCES[RoomResult.MONSTER] += 0.1

        if rolled_room_result == RoomResult.SHOP:
            EventHelper.CHANCES[RoomResult.SHOP] = 0.03
        else:
            EventHelper.CHANCES[RoomResult.SHOP] += 0.03

        if rolled_room_result == RoomResult.TREASURE:
            EventHelper.CHANCES[RoomResult.TREASURE] = 0.02
        else:
            EventHelper.CHANCES[RoomResult.TREASURE] += 0.02

        chances_repr = pprint.pformat(EventHelper.CHANCES)
        logger.debug(
            f"Event roll {roll} means {rolled_room_result}, room chances now:{os.linesep}{chances_repr}"
        )
        return rolled_room_result

    @staticmethod
    def reset_probabilities():
        logger.debug("Reset event probabilities")
        EventHelper.CHANCES[RoomResult.MONSTER] = 0.1
        EventHelper.CHANCES[RoomResult.SHOP] = 0.03
        EventHelper.CHANCES[RoomResult.TREASURE] = 0.02


class MonsterHelper:
    _encounter_name_to_monster_group_supplier: Dict[
        EncounterName, Callable[[CCG.Context], MonsterGroup]
    ] = {
        EncounterName.SMALL_SLIMES: MonsterHelperHelper.spawn_small_slimes,
        EncounterName.TWO_LOUSE: lambda ctx: MonsterGroup(
            ctx,
            [MonsterHelperHelper.get_louse(ctx), MonsterHelperHelper.get_louse(ctx)],
        ),
        EncounterName.THREE_SENTRIES: lambda ctx: MonsterGroup(
            ctx, [Sentry(ctx), Sentry(ctx), Sentry(ctx)]
        ),
        EncounterName.RED_SLAVER: lambda ctx: MonsterGroup(ctx, [SlaverRed(ctx)]),
        EncounterName.SLIME_BOSS: lambda ctx: MonsterGroup(ctx, [SlimeBoss(ctx)]),
        EncounterName.THE_GUARDIAN: lambda ctx: MonsterGroup(ctx, [TheGuardian(ctx)]),
        EncounterName.CULTIST: lambda ctx: MonsterGroup(ctx, [Cultist(ctx)]),
        EncounterName.EXORDIUM_WILDLIFE: MonsterHelperHelper.bottom_wildlife,
        EncounterName.LARGE_SLIME: MonsterHelperHelper.large_slime,
        EncounterName.THREE_LOUSE: lambda ctx: MonsterGroup(
            ctx,
            [
                MonsterHelperHelper.get_louse(ctx),
                MonsterHelperHelper.get_louse(ctx),
                MonsterHelperHelper.get_louse(ctx),
            ],
        ),
        EncounterName.EXORDIUM_THUGS: MonsterHelperHelper.bottom_humanoid,
        EncounterName.GREMLIN_NOB: lambda ctx: MonsterGroup(ctx, [GremlinNob(ctx)]),
        EncounterName.JAW_WORM: lambda ctx: MonsterGroup(ctx, [JawWorm(ctx)]),
        EncounterName.MUSHROOM_LAIR: lambda ctx: MonsterGroup(
            ctx, [FungiBeast(ctx), FungiBeast(ctx), FungiBeast(ctx)]
        ),
        EncounterName.HEXAGHOST: lambda ctx: MonsterGroup(ctx, [Hexaghost(ctx)]),
        EncounterName.GREMLIN_GANG: MonsterHelperHelper.spawn_gremlins,
        EncounterName.LOTS_OF_SLIMES: MonsterHelperHelper.spawn_many_small_slimes,
        EncounterName.LAGAVULIN: lambda ctx: MonsterGroup(ctx, [Lagavulin(ctx)]),
        EncounterName.BLUE_SLAVER: lambda ctx: MonsterGroup(ctx, [SlaverBlue(ctx)]),
        EncounterName.TWO_FUNGI_BEASTS: lambda ctx: MonsterGroup(
            ctx, [FungiBeast(ctx), FungiBeast(ctx)]
        ),
        EncounterName.LOOTER: lambda ctx: MonsterGroup(ctx, [Looter(ctx)]),
    }

    @classmethod
    def get_encounter(cls, ctx: CCG.Context, name: EncounterName) -> MonsterGroup:
        mg = cls._encounter_name_to_monster_group_supplier.get(name)
        logger.debug(f"Translated {name} -> {mg}")
        assert mg
        return mg(ctx)


class MonsterInfo:
    def __init__(self, name: EncounterName, weight: float):
        self.name = name
        self.weight = weight

    @classmethod
    def roll(cls, monster_infos: List[MonsterInfo]):
        # This differs from source, but it lets us get away with skipping lots of silly manual work.
        chosen = random.choices(
            [mi.name for mi in monster_infos],
            weights=[mi.weight for mi in monster_infos],
        )
        # random.choices returns a list, by default of len 1
        assert len(chosen) == 1
        return chosen[0]


class MapRoomNode:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.room: Optional[Room] = None
        self.edges: List[MapEdge] = []
        self.parents: List[MapRoomNode] = []
        self.has_emerald_key = False

    def __repr__(self) -> str:
        emerald_key_repr = " EK" if self.has_emerald_key else ""
        return f"< ({self.x}, {self.y}){emerald_key_repr} with {len(self.edges)} edges, room: {self.room} >"

    def add_edge(self, new_edge):
        if not any((MapEdge.compare_coordinates(e, new_edge) == 0 for e in self.edges)):
            self.edges.append(new_edge)

    def get_parents(self):
        return self.parents

    def add_parent(self, p: MapRoomNode):
        self.parents.append(p)

    def has_edges(self):
        return len(self.edges) > 0

    def get_room_symbol(self, show_room_symbols: bool):
        if self.room and show_room_symbols:
            return self.room.room_symbol
        return "*"

    def _find_successor_edge(self, predicate: Callable[[MapEdge], bool]):
        matching_edges = [e for e in self.edges if predicate(e)]
        if len(matching_edges) == 0:
            return None
        elif len(matching_edges) == 1:
            return matching_edges[0]
        else:
            raise Exception()

    def left_successor_edge(self):
        return self._find_successor_edge(lambda e: e.dst_x < self.x)

    def center_successor_edge(self):
        return self._find_successor_edge(lambda e: e.dst_x == self.x)

    def right_successor_edge(self):
        return self._find_successor_edge(lambda e: e.dst_x > self.x)
