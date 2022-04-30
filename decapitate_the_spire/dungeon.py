from __future__ import annotations

import copy
import logging
import os
import random
from abc import ABC, abstractmethod
from typing import List, final, Callable

import decapitate_the_spire as dts
from decapitate_the_spire.ascension import AscensionManager
from typing import TYPE_CHECKING

from decapitate_the_spire.card import CardGroup, CardGroupType, Card

if TYPE_CHECKING:
    from decapitate_the_spire.character import MonsterGroup
    from decapitate_the_spire.game import CCG, Map, MapCoord
    from decapitate_the_spire.event import Event
from decapitate_the_spire.config import MAP_HEIGHT, MAP_WIDTH, MAP_PATH_DENSITY
from decapitate_the_spire.map import EncounterName, MapRoomNode, EventName, MapEdge, MapGenerator, RoomTypeAssigner, EventHelper, RoomResult, MonsterHelper, MonsterInfo
from decapitate_the_spire.potion import EnergyPotion
from decapitate_the_spire.relic import Circlet, RedCirclet, GoldenIdol
from decapitate_the_spire.enums import RelicTier, CardRarity
from decapitate_the_spire.rng import Rng
from decapitate_the_spire.room import Room, RestRoom, MonsterRoom, TreasureRoom, MonsterRoomElite, EventRoom, ShopRoom, \
    DebugNoOpNeowRoom, NeowRoom, MonsterRoomBoss, SmallChest, MediumChest, LargeChest

logger = logging.getLogger(__name__)


class Dungeon(ABC):
    def __init__(self, ctx: CCG.Context, boss_y: int = 14):
        # TODO complete
        # self.ctx.d = self
        self.ctx = ctx

        # These all used to be class vars, so there'll probably be issues
        self.monster_list: List[EncounterName] = []
        self.elite_monster_list: List[EncounterName] = []
        self.boss_list: List[EncounterName] = []
        self.boss_key: EncounterName
        self.event_list = []
        self.shrine_list = []
        self.floor_num = 0
        self.next_room_node: MapRoomNode = None
        self.curr_map_node: MapRoomNode = None
        self.act_num = 0
        self.relics_to_remove_on_start = []
        self.mapp: List[List[MapRoomNode]] = None
        self.special_one_time_event_list: List[EventName] = []
        assert isinstance(boss_y, int)
        self.boss_y = boss_y

        # Default chances to Exordium
        self.shop_room_chance = 0.05
        self.rest_room_chance = 0.12
        self.treasure_room_chance = 0.0
        self.event_room_chance = 0.22
        self.elite_room_chance = 0.08
        self.small_chest_chance = 50
        self.medium_chest_chance = 33
        self.large_chest_chance = 17
        self.common_relic_chance = 50
        self.uncommon_relic_chance = 33
        self.rare_relic_chance = 17
        self.colorless_rare_chance = 0.3
        self.card_upgraded_chance = 0.0
        self.shrine_chance = 0.25

        self.card_blizz_start_offset = 5
        self.card_blizz_randomizer = 5
        self.card_blizz_growth = 1
        self.card_blizz_max_offset = -40

        self.common_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.uncommon_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.rare_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.colorless_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.curse_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)

        self.src_common_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.src_uncommon_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.src_rare_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.src_colorless_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        self.src_curse_card_pool = CardGroup(self.ctx, CardGroupType.CARD_POOL)
        # End former class vars section

        self.common_relic_pool = [
            r for r in dts.SILENT_RELIC_UNIVERSE if r.get_tier() == RelicTier.COMMON
        ]
        self.uncommon_relic_pool = [
            r for r in dts.SILENT_RELIC_UNIVERSE if r.get_tier() == RelicTier.UNCOMMON
        ]
        self.rare_relic_pool = [
            r for r in dts.SILENT_RELIC_UNIVERSE if r.get_tier() == RelicTier.RARE
        ]
        self.shop_relic_pool = [
            r for r in dts.SILENT_RELIC_UNIVERSE if r.get_tier() == RelicTier.SHOP
        ]
        self.boss_relic_pool = [
            r for r in dts.SILENT_RELIC_UNIVERSE if r.get_tier() == RelicTier.BOSS
        ]
        random.shuffle(self.common_relic_pool)
        random.shuffle(self.uncommon_relic_pool)
        random.shuffle(self.rare_relic_pool)
        random.shuffle(self.shop_relic_pool)
        random.shuffle(self.boss_relic_pool)

        # self.player = player
        self.dungeon_transition_setup()
        self.generate_monsters()
        self.initialize_boss()
        self.set_boss(self.boss_list[0])
        self.initialize_event_list()
        self.initialize_shrine_list()
        self.initialize_card_pools()
        if self.floor_num == 0:
            self.ctx.player.initialize_starter_deck()

    def __repr__(self):
        s = (
            f"{self.__class__.__name__}: FL {self.floor_num}{os.linesep}"
            f"{self.ctx.player}{os.linesep}"
            f"{self.get_curr_room()}{os.linesep}"
        )

        request = self.ctx.action_manager.outstanding_request
        if request:
            s += f"{request}{os.linesep}"

        return s

    def update(self) -> bool:
        # TODO complete

        did_something = False
        # Source has a big switch on `screen` here, which I think is akin to handling requests
        if self.ctx.action_manager.outstanding_request:
            if self.ctx.action_manager.outstanding_request.is_waiting_for_response:
                # did_something = True
                logger.debug("Request is waiting for response, exiting update early")
                # TODO is early return correct?
                return False
            else:
                did_something = True
                self.ctx.action_manager.outstanding_request.execute()

        # Some requests can be responded to multiple times. If request execution above decided to leave the request in
        # place, don't call room update, let user continue responding to request.
        if not self.ctx.action_manager.outstanding_request:
            did_something |= self.curr_map_node.room.update()

        return did_something

    @staticmethod
    def manual_init_node(mapp: Map, src: MapCoord, room: Room, dst: MapCoord = None):
        node = mapp[src[1]][src[0]]
        node.room = room
        if dst:
            node.add_edge(MapEdge.from_coords(src, dst))

    # @staticmethod
    def get_random_chest(self):
        roll = self.ctx.treasure_rng.random_from_0_to(99)
        if roll < self.small_chest_chance:
            chest = SmallChest(
                self.ctx,
            )
        elif roll < self.small_chest_chance + self.medium_chest_chance:
            chest = MediumChest(
                self.ctx,
            )
        else:
            chest = LargeChest(
                self.ctx,
            )

        logger.debug(f"Get chest roll {roll} -> {chest}")
        return chest

    # @staticmethod
    def get_reward_cards(self):
        num_cards = 3
        cards_to_return: List[Card] = []

        for r in self.ctx.player.relics:
            num_cards = r.change_number_of_cards_in_reward(num_cards)

        for _ in range(num_cards):
            rarity = self.roll_rarity()
            assert rarity in [CardRarity.RARE, CardRarity.UNCOMMON, CardRarity.COMMON]

            if rarity == CardRarity.COMMON:
                new_randomizer = max(
                    self.card_blizz_max_offset,
                    self.card_blizz_randomizer - self.card_blizz_growth,
                )
                logger.debug(
                    f"Common rarity roll changed CBR: {self.card_blizz_randomizer} -> {new_randomizer}"
                )
                self.card_blizz_randomizer = new_randomizer
            elif rarity == CardRarity.RARE:
                new_randomizer = self.card_blizz_start_offset
                logger.debug(
                    f"Rare rarity roll reset CBR: {self.card_blizz_randomizer} -> {new_randomizer}"
                )
                self.card_blizz_randomizer = new_randomizer

            # TODO prismatic shard
            while True:
                card = self.get_card(rarity)
                # Source checks this with cardID; I think this is equivalent. Type comparison gets really weird with
                # ABC. See https://stackoverflow.com/q/56320056
                ct = card.__name__
                for rc in cards_to_return:
                    rct = rc.__name__
                    if rct == ct:
                        logger.debug(
                            f"Not adding {card} to rewards because a copy is already included"
                        )
                        continue

                assert card
                logger.debug(f"Adding {card} to rewards")
                cards_to_return.append(card)
                break

        # Not sure this is necessary, but source does it
        copied_cards_to_return = []
        for c in cards_to_return:
            copied_cards_to_return.append(c.make_copy(self.ctx))

        for c in copied_cards_to_return:
            # Doing this more verbosely than source
            upgrade_card = False
            if c.rarity == CardRarity.RARE:
                logger.debug(f"Not upgrading reward {c} because it is rare")
            elif not self.ctx.card_rng.random_boolean(self.card_upgraded_chance):
                logger.debug(
                    f"Not upgrading reward {c} because failed {self.card_upgraded_chance:.2f} upgrade roll"
                )
            elif not c.can_upgrade():
                logger.debug(
                    f"Not upgrading reward {c} because it says it's not upgradable"
                )
            else:
                upgrade_card = True

            if upgrade_card:
                c.upgrade()
                logger.debug(f"Upgraded reward {c}")
            else:
                for r in self.ctx.player.relics:
                    was_upgraded = c.upgraded
                    r.on_preview_obtain_card(c)
                    assert not (was_upgraded and not c.upgraded)
                    if c.upgraded != was_upgraded:
                        logger.debug(f"Relic upgraded reward {c}")

        return copied_cards_to_return

    def get_card(self, rarity: CardRarity, rng: Rng = None):
        if not rng:
            rng = self.ctx.card_rng

        if rarity == CardRarity.COMMON:
            c = self.common_card_pool.get_random_card(rng)
        elif rarity == CardRarity.UNCOMMON:
            c = self.uncommon_card_pool.get_random_card(rng)
        elif rarity == CardRarity.RARE:
            c = self.rare_card_pool.get_random_card(rng)
        elif rarity == CardRarity.CURSE:
            c = self.curse_card_pool.get_random_card(rng)
        else:
            # Source returns null
            raise ValueError(rarity)

        return c

    # @staticmethod
    def roll_rarity(self):
        roll = self.ctx.card_rng.random_from_0_to(99)
        modified_roll = roll + self.card_blizz_randomizer
        logger.debug(
            f"Card rarity roll: {roll} + {self.card_blizz_randomizer} = {modified_roll}"
        )
        if self.curr_map_node is None:
            return self.get_card_rarity_fallback(modified_roll)
        return self.get_curr_room().get_card_rarity(modified_roll)

    @staticmethod
    def get_card_rarity_fallback(roll: int):
        rare_rate = 3
        if roll < rare_rate:
            rarity = CardRarity.RARE
        elif roll < 40:
            rarity = CardRarity.UNCOMMON
        else:
            rarity = CardRarity.COMMON

        logger.debug(f"Roll to card rarity: {roll} -> {rarity}")
        return rarity

    # @staticmethod
    def get_monsters(self):
        return self.get_curr_room().monster_group

    # @staticmethod
    def initialize_special_one_time_event_list(self):
        assert len(self.special_one_time_event_list) == 0
        self.special_one_time_event_list = [
            # TODO impl, and this doesn't belong here
            EventName.BIG_FISH,
            # EventName.ACCURSED_BLACKSMITH,
            # EventName.BONFIRE_ELEMENTALS,
            # EventName.DESIGNER,
            # EventName.DUPLICATOR,
            # EventName.FACE_TRADER,
            # EventName.FOUNTAIN_OF_CLEANSING,
            # EventName.KNOWING_SKULL,
            # EventName.LAB,
            # EventName.NLOTH,
            # EventName.SECRET_PORTAL,
            # EventName.THE_JOUST,
            # EventName.WE_MEET_AGAIN,
            # EventName.THE_WOMAN_IN_BLUE,
        ]

    # @classmethod
    def generate_map(self) -> Map:
        mapp = MapGenerator.generate_dungeon(
            MAP_HEIGHT, MAP_WIDTH, MAP_PATH_DENSITY, self.ctx.map_rng
        )

        count = 0
        for row in mapp:
            for node in row:
                if node.has_edges() and node.y != (len(mapp) - 2):
                    count += 1

        room_list = self.generate_room_types(count)
        RoomTypeAssigner.assign_row_as_room_type(self.ctx, mapp[-1], RestRoom)
        RoomTypeAssigner.assign_row_as_room_type(self.ctx, mapp[0], MonsterRoom)
        RoomTypeAssigner.assign_row_as_room_type(self.ctx, mapp[8], TreasureRoom)
        RoomTypeAssigner.distribute_rooms_across_map(
            self.ctx, self.ctx.map_rng, mapp, room_list
        )
        logger.debug(f"Map:{os.linesep}{MapGenerator.to_string(mapp, True)}")
        self.set_emerald_elite(mapp)
        return mapp

    # @staticmethod
    # def on_modify_power():
    #     self.ctx.player.hand.apply_powers()
    #     self.ctx.d.get_curr_room().monster_group.apply_powers()

    # @classmethod
    def return_random_potion(self, limited: bool = False):
        # TODO implement when we have more potions
        return EnergyPotion(self.ctx)

    # @staticmethod
    def return_random_relic(self, tier: RelicTier):
        if tier == RelicTier.COMMON:
            if self.common_relic_pool:
                relic = self.common_relic_pool.pop(0)(self.ctx)
            else:
                relic = self.return_random_relic(RelicTier.UNCOMMON)
        elif tier == RelicTier.UNCOMMON:
            if self.uncommon_relic_pool:
                relic = self.uncommon_relic_pool.pop(0)(self.ctx)
            else:
                relic = self.return_random_relic(RelicTier.RARE)
        elif tier == RelicTier.RARE:
            if self.rare_relic_pool:
                relic = self.rare_relic_pool.pop(0)(self.ctx)
            else:
                relic = Circlet(self.ctx)
                # relic_cls = Circlet
        elif tier == RelicTier.SHOP:
            if self.shop_relic_pool:
                relic = self.shop_relic_pool.pop(0)(self.ctx)
            else:
                relic = self.return_random_relic(RelicTier.UNCOMMON)
        elif tier == RelicTier.BOSS:
            if self.boss_relic_pool:
                relic = self.boss_relic_pool.pop(0)(self.ctx)
            else:
                relic = RedCirclet(self.ctx)
                # relic_cls = RedCirclet
        else:
            relic = Circlet(self.ctx)
            # relic_cls = Circlet

        return relic

    # @classmethod
    def dungeon_transition_setup(self):
        self.act_num += 1
        # Source sets card rng counter here
        EventHelper.reset_probabilities()
        self.event_list.clear()
        self.shrine_list.clear()
        self.monster_list.clear()
        self.elite_monster_list.clear()
        self.boss_list.clear()

        heal_amount = AscensionManager.check_ascension(
            self,
            self.ctx.player.max_health,
            5,
            round(
                0.75
                * float(self.ctx.player.max_health - self.ctx.player.current_health)
            ),
        )
        self.ctx.player.heal(heal_amount)

        if self.floor_num <= 1 and isinstance(self, Exordium):
            if AscensionManager.get_ascension(self) >= 14:
                self.ctx.player.decrease_max_health(
                    self.ctx.player.get_ascension_max_hp_loss()
                )

            if AscensionManager.get_ascension(self) >= 6:
                self.ctx.player.current_health = round(
                    float(self.ctx.player.current_health) * 0.9
                )

            if AscensionManager.get_ascension(self) >= 10:
                self.ctx.player.master_deck.add_to_top(
                    AscendersBane(
                        self.ctx,
                    )
                )

    # @staticmethod
    def get_curr_room(self):
        return self.curr_map_node.room

    # @staticmethod
    def set_curr_map_node(self, new_node: MapRoomNode):
        assert new_node.room
        logger.debug(f"Set curr map node to {new_node}")
        # Source does some souls stuff here
        self.curr_map_node = new_node

    def next_room_transition(self):
        logger.debug(
            f"Transitioning map nodes {self.curr_map_node} -> {self.next_room_node}"
        )
        # This if guards against None at the beginning of Exordium
        if self.next_room_node and self.next_room_node.room:
            self.next_room_node.room.rewards.clear()

        if isinstance(self.get_curr_room(), MonsterRoomElite):
            if len(self.elite_monster_list) > 0:
                logger.debug(
                    f"Removing elite {self.elite_monster_list[0].name} from monster list"
                )
                del self.elite_monster_list[0]
            else:
                self.generate_elites(10)
        elif isinstance(self.get_curr_room(), MonsterRoom):
            # It feels like a mistake in source that MonsterRoomBoss triggers this, but it also probably doesn't matter
            if len(self.monster_list) > 0:
                logger.debug(
                    f"Removing monster {self.monster_list[0].name} from monster list"
                )
                del self.monster_list[0]
            else:
                self.generate_strong_enemies(12)
        # TODO event note for yourself

        self.reset_player()
        self.floor_num += 1

        # TODO seems weird that RNGs get reset here
        self.monster_hp_rng = Rng()
        self.ai_rng = Rng()
        self.shuffle_rng = Rng()
        self.card_random_rng = Rng()
        self.misc_rng = Rng()

        if self.next_room_node:
            for r in self.ctx.player.relics:
                r.on_enter_room(self.next_room_node.room)

        # It's not clear whether this is an error. See source.
        if len(self.ctx.action_manager.actions) > 0:
            logger.warning("Action manager actions was not empty, clearing")
            self.ctx.action_manager.actions.clear()

        if self.next_room_node:
            if isinstance(self.next_room_node.room, EventRoom):
                # See source
                room_result = EventHelper.roll(self.ctx)
                rolled_room = self.generate_room(room_result)
                logger.debug(
                    f"Resolved event room roll {room_result} to room {rolled_room}"
                )
                self.next_room_node.room = rolled_room

            self.set_curr_map_node(self.next_room_node)

        assert self.get_curr_room()

        for r in self.ctx.player.relics:
            r.just_entered_room(self.get_curr_room())

        # Source has some stuff about loading from a save and events here, don't think we need it.

        self.get_curr_room().on_player_entry()
        if isinstance(self.curr_map_node.room, MonsterRoom):
            self.ctx.player.pre_battle_prep()

    # @staticmethod
    def generate_room(self, room_result: RoomResult):
        logger.debug(f"Generating room for {room_result}")
        if room_result == RoomResult.MONSTER:
            room = MonsterRoom(
                self.ctx,
            )
        elif room_result == RoomResult.SHOP:
            room = ShopRoom(
                self.ctx,
            )
        elif room_result == RoomResult.TREASURE:
            room = TreasureRoom(
                self.ctx,
            )
        elif room_result == RoomResult.EVENT:
            room = EventRoom(
                self.ctx,
            )
        else:
            raise ValueError(room_result)
        return room

    # @staticmethod
    def reset_player(self):
        self.ctx.player.hand.clear()
        self.ctx.player.powers.clear()
        self.ctx.player.draw_pile.clear()
        self.ctx.player.discard_pile.clear()
        self.ctx.player.exhaust_pile.clear()
        # TODO limbo
        self.ctx.player.lose_block()
        # TODO stance

    def get_boss(self):
        return MonsterHelper.get_encounter(self.ctx, self.boss_key)

    def get_monster_for_room_creation(self):
        if len(self.monster_list) == 0:
            self.generate_strong_enemies(12)

        return MonsterHelper.get_encounter(self.ctx, self.monster_list[0])

    def get_elite_monster_for_room_creation(self):
        if len(self.elite_monster_list) == 0:
            self.generate_elites(10)

        return MonsterHelper.get_encounter(self.ctx, self.elite_monster_list[0])

    def populate_monster_list(
        self, monster_infos: List[MonsterInfo], num_monsters: int, elites: bool
    ):
        # This impl is a little silly, but it's source
        if elites:
            i = 0
            while i < num_monsters:
                i += 1
                to_add = MonsterInfo.roll(monster_infos)
                if len(self.elite_monster_list) == 0:
                    self.elite_monster_list.append(to_add)
                else:
                    if to_add != self.elite_monster_list[-1]:
                        self.elite_monster_list.append(to_add)
                    else:
                        i -= 1

        else:
            i = 0
            while i < num_monsters:
                i += 1
                to_add = MonsterInfo.roll(monster_infos)
                if len(self.monster_list) == 0:
                    self.monster_list.append(to_add)
                else:
                    if to_add != self.monster_list[-1]:
                        if (
                            len(self.monster_list) > 1
                            and to_add == self.monster_list[-2]
                        ):
                            i -= 1
                        else:
                            self.monster_list.append(to_add)
                    else:
                        i -= 1

    @abstractmethod
    def generate_monsters(self):
        ...

    @abstractmethod
    def generate_weak_enemies(self, count: int):
        ...

    @abstractmethod
    def generate_strong_enemies(self, count: int):
        ...

    @abstractmethod
    def generate_elites(self, count: int):
        ...

    @abstractmethod
    def initialize_boss(self):
        ...

    @abstractmethod
    def initialize_event_list(self):
        ...

    @abstractmethod
    def initialize_shrine_list(self):
        ...

    @final
    def initialize_card_pools(self):
        self.common_card_pool.clear()
        self.uncommon_card_pool.clear()
        self.rare_card_pool.clear()
        self.colorless_card_pool.clear()
        self.curse_card_pool.clear()

        tmp_pool = self.ctx.player.get_card_pool()
        # TODO more robust, colorless
        from .card import Regret
        self.curse_card_pool.add_to_top(
            Regret(
                self.ctx,
            )
        )

        for c in tmp_pool:
            if c.rarity == CardRarity.COMMON:
                self.common_card_pool.add_to_top(c)
            elif c.rarity == CardRarity.UNCOMMON:
                self.uncommon_card_pool.add_to_top(c)
            elif c.rarity == CardRarity.RARE:
                self.rare_card_pool.add_to_top(c)
            elif c.rarity == CardRarity.CURSE:
                self.curse_card_pool.add_to_top(c)
            else:
                raise ValueError(c.rarity)

        self.src_colorless_card_pool = CardGroup(
            self.ctx, CardGroupType.CARD_POOL, self.colorless_card_pool._ordered_cards
        )
        self.src_curse_card_pool = CardGroup(
            self.ctx, CardGroupType.CARD_POOL, self.curse_card_pool._ordered_cards
        )
        self.src_rare_card_pool = CardGroup(
            self.ctx, CardGroupType.CARD_POOL, self.rare_card_pool._ordered_cards
        )
        self.src_uncommon_card_pool = CardGroup(
            self.ctx, CardGroupType.CARD_POOL, self.uncommon_card_pool._ordered_cards
        )
        self.src_common_card_pool = CardGroup(
            self.ctx, CardGroupType.CARD_POOL, self.common_card_pool._ordered_cards
        )

    def set_boss(self, name: EncounterName):
        self.boss_key = name

    # @classmethod
    def generate_room_types(self, available_room_count: int):
        logger.debug(f"Generating rooms with {available_room_count} available")
        shop_count = round(available_room_count * self.shop_room_chance)
        logger.debug(f"Shop: {shop_count}")
        rest_count = round(available_room_count * self.rest_room_chance)
        logger.debug(f"Rest: {rest_count}")
        treasure_count = round(available_room_count * self.treasure_room_chance)
        logger.debug(f"Treasure: {treasure_count}")
        elite_chance = (
            AscensionManager.check_ascension(self, 1.0, 1, 1.6) * self.elite_room_chance
        )
        elite_count = round(available_room_count * elite_chance)
        logger.debug(f"Elite: {elite_count}")
        event_count = round(available_room_count * self.event_room_chance)
        logger.debug(f"Event: {event_count}")
        monster_count = available_room_count - sum(
            [shop_count, rest_count, treasure_count, elite_count, event_count]
        )
        logger.debug(f"Monster: {monster_count}")

        return (
            [
                ShopRoom(
                    self.ctx,
                )
                for _ in range(shop_count)
            ]
            + [
                RestRoom(
                    self.ctx,
                )
                for _ in range(rest_count)
            ]
            + [
                MonsterRoomElite(
                    self.ctx,
                )
                for _ in range(elite_count)
            ]
            + [
                EventRoom(
                    self.ctx,
                )
                for _ in range(event_count)
            ]
        )

    def generate_event(self) -> Event:
        rng = self.ctx.event_rng
        if rng.random_float() < self.shrine_chance:
            if not self.shrine_list and not self.special_one_time_event_list:
                if self.event_list:
                    evn = self.get_event(rng)
                else:
                    # Source returns null here, but that has to cause a NPE in EventRoom#onPlayerEntry
                    raise Exception("no move events")
            else:
                evn = self.get_shrine(rng)
        else:
            evn = self.get_event(rng)
            # Source if's this, but I think it's defensive in case they didn't handle a name to event mapping.
            assert evn is not None
            # if e is None:
            #     return self.get_shrine(rng)

        return EventHelper.get_event(self.ctx, evn)

    def get_event(self, rng: Rng) -> EventName:
        available_events = []

        for evn in self.event_list:
            if evn == EventName.MUSHROOMS or evn == EventName.DEAD_ADVENTURER:
                can_add = self.floor_num > 6
            elif evn == EventName.COLOSSEUM:
                can_add = (
                    self.curr_map_node is not None
                    and self.curr_map_node.y > len(self.mapp) / 2
                )
            elif evn == EventName.THE_MOAI_HEAD:
                can_add = (
                    self.ctx.player.has_relic(GoldenIdol)
                    or self.ctx.player.current_health_proportion <= 0.5
                )
            elif evn == EventName.THE_CLERIC:
                can_add = self.ctx.player.gold >= 35
            elif evn == EventName.BEGGAR:
                can_add = self.ctx.player.gold >= 75
            else:
                can_add = True

            if can_add:
                available_events.append(evn)

        if not available_events:
            return self.get_shrine(rng)

        chosen_event_name = available_events[
            rng.random_from_0_to(len(available_events) - 1)
        ]
        self.event_list.remove(chosen_event_name)
        logger.debug(f"Removed {chosen_event_name} from pool")
        return chosen_event_name

    def get_shrine(self, rng: Rng) -> EventName:
        available_events = copy.copy(self.shrine_list)

        for evn in self.special_one_time_event_list:
            if evn == EventName.NLOTH:
                can_add = isinstance(self, TheCity) and len(self.ctx.player.relics) >= 2
            elif evn == EventName.FACE_TRADER:
                can_add = isinstance(
                    self,
                    (
                        TheCity,
                        Exordium,
                    ),
                )
            elif evn == EventName.THE_JOUST:
                can_add = isinstance(self, (TheCity,)) and self.ctx.player.gold >= 50
            elif evn == EventName.DUPLICATOR:
                can_add = isinstance(
                    self,
                    (
                        TheCity,
                        TheBeyond,
                    ),
                )
            elif evn == EventName.SECRET_PORTAL:
                can_add = isinstance(self, (TheBeyond,))
            elif evn == EventName.DESIGNER:
                can_add = (
                    isinstance(self, (TheCity, TheBeyond))
                    and self.ctx.player.gold >= 75
                )
            elif evn == EventName.KNOWING_SKULL:
                can_add = (
                    isinstance(self, (TheCity,)) and self.ctx.player.current_health > 12
                )
            elif evn == EventName.THE_WOMAN_IN_BLUE:
                can_add = self.ctx.player.gold >= 50
            elif evn == EventName.FOUNTAIN_OF_CLEANSING:
                can_add = self.ctx.player.is_cursed
            else:
                can_add = True

            if can_add:
                available_events.append(evn)

        chosen_event_name = available_events[
            rng.random_from_0_to(len(available_events) - 1)
        ]
        removals = 0
        try:
            self.shrine_list.remove(chosen_event_name)
            removals += 1
        except ValueError:
            pass
        try:
            self.special_one_time_event_list.remove(chosen_event_name)
            removals += 1
        except ValueError:
            pass

        if removals != 1:
            raise Exception("removing event from lists didn't go as expected")
        logger.debug(f"Removed {chosen_event_name} from pool")

        return chosen_event_name

    # @staticmethod
    def set_emerald_elite(self, mapp: Map):
        elite_nodes = []

        for row in mapp:
            for node in row:
                if isinstance(node.room, MonsterRoomElite):
                    elite_nodes.append(node)

        chosen_node = elite_nodes[self.ctx.map_rng.random(0, len(elite_nodes) - 1)]
        chosen_node.has_emerald_key = True
        logger.debug(f"Put emerald key in {chosen_node}")


class SimpleDungeon(Dungeon):
    def __init__(
        self,
        ctx: CCG.Context,
        monster_group_or_supplier: Callable[[CCG.Context], MonsterGroup],
    ):
        super().__init__(ctx)
        neow_node = MapRoomNode(0, -1)
        neow_node.room = DebugNoOpNeowRoom(
            self.ctx,
        )
        self.curr_map_node = neow_node

        monster_group = monster_group_or_supplier(self.ctx)

        def generate_map() -> Map:
            mapp = [
                [MapRoomNode(i, 0) for i in range(MAP_WIDTH)],
                [MapRoomNode(i, 1) for i in range(MAP_WIDTH)],
            ]

            # Ordinary monster room, typical neow successor
            self.manual_init_node(
                mapp, (0, 0), MonsterRoom(self.ctx, monster_group), (0, 1)
            )

            return mapp

        self.mapp = generate_map()

    def generate_monsters(self):
        # self.monster_list = [EncounterName.SMALL_SLIMES]
        pass

    def generate_weak_enemies(self, count: int):
        pass

    def generate_strong_enemies(self, count: int):
        pass

    def generate_elites(self, count: int):
        pass

    def initialize_boss(self):
        self.boss_list = [EncounterName.HEXAGHOST]

    def initialize_event_list(self):
        pass

    def initialize_shrine_list(self):
        pass


class TheCity(Dungeon):
    ...


class TheBeyond(Dungeon):
    ...


class TheEnding(Dungeon):
    ...


class MiniDungeon(Dungeon):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, boss_y=3)
        self.mapp = self.generate_map()
        self.curr_map_node = MapRoomNode(0, -1)
        self.curr_map_node.room = NeowRoom(self.ctx)

    # @classmethod
    def generate_map(self):
        mapp = [
            [MapRoomNode(i, 0) for i in range(MAP_WIDTH)],
            [MapRoomNode(i, 1) for i in range(MAP_WIDTH)],
            [MapRoomNode(i, 2) for i in range(MAP_WIDTH)],
            [MapRoomNode(i, 3) for i in range(MAP_WIDTH)],
            [MapRoomNode(i, 4) for i in range(MAP_WIDTH)],
        ]
        # Ordinary monster room, typical neow successor
        self.manual_init_node(
            mapp,
            (0, 0),
            MonsterRoom(
                self.ctx,
            ),
            (0, 1),
        )
        # Elite with emerald key
        self.manual_init_node(
            mapp,
            (1, 0),
            MonsterRoomElite(
                self.ctx,
            ),
            (0, 1),
        )
        mapp[0][1].has_emerald_key = True
        # Ordinary rest room
        self.manual_init_node(
            mapp,
            (2, 0),
            RestRoom(
                self.ctx,
            ),
            (0, 1),
        )
        # Ordinary treasure room
        self.manual_init_node(
            mapp,
            (3, 0),
            TreasureRoom(
                self.ctx,
            ),
            (0, 1),
        )
        # Ordinary event room
        self.manual_init_node(
            mapp,
            (4, 0),
            EventRoom(
                self.ctx,
            ),
            (0, 1),
        )
        self.manual_init_node(
            mapp,
            (5, 0),
            ShopRoom(
                self.ctx,
            ),
            (0, 1),
        )

        self.manual_init_node(
            mapp,
            (0, 1),
            MonsterRoomElite(
                self.ctx,
            ),
            (0, 2),
        )
        self.manual_init_node(
            mapp,
            (0, 2),
            TreasureRoom(
                self.ctx,
            ),
            (0, 3),
        )
        self.manual_init_node(
            mapp,
            (0, 3),
            MonsterRoomBoss(
                self.ctx,
            ),
        )
        return mapp

    def generate_monsters(self):
        self.monster_list = [EncounterName.SMALL_SLIMES] * 2

    def generate_weak_enemies(self, count: int):
        pass

    def generate_strong_enemies(self, count: int):
        pass

    def generate_elites(self, count: int):
        # Yeah yeah these aren't elites
        self.elite_monster_list = [EncounterName.SMALL_SLIMES] * 2

    def initialize_boss(self):
        self.boss_list = [EncounterName.HEXAGHOST]

    def initialize_event_list(self):
        self.event_list = [EventName.BIG_FISH]

    def initialize_shrine_list(self):
        pass


class Exordium(Dungeon):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.initialize_relic_list()
        self.initialize_special_one_time_event_list()
        self.mapp = self.generate_map()
        self.curr_map_node = MapRoomNode(0, -1)
        self.curr_map_node.room = NeowRoom(
            self.ctx,
        )
        # TODO this should get set by an action from environment somehow?
        # self.next_room_node = MapRoomNode(0, 0)
        # self.next_room_node.room = NeowRoom()

    def generate_monsters(self):
        self.generate_weak_enemies(3)
        self.generate_strong_enemies(12)
        self.generate_elites(10)

    def generate_weak_enemies(self, count: int):
        monsters = [
            MonsterInfo(EncounterName.CULTIST, 2.0),
            MonsterInfo(EncounterName.JAW_WORM, 2.0),
            MonsterInfo(EncounterName.TWO_LOUSE, 2.0),
            MonsterInfo(EncounterName.SMALL_SLIMES, 2.0),
        ]
        # Source normalizes weights here, but we don't have to. See MonsterInfo::roll.
        self.populate_monster_list(monsters, count, False)

    def generate_strong_enemies(self, count: int):
        monsters = [
            MonsterInfo(EncounterName.BLUE_SLAVER, 2.0),
            MonsterInfo(EncounterName.GREMLIN_GANG, 1.0),
            MonsterInfo(EncounterName.LOOTER, 2.0),
            MonsterInfo(EncounterName.LARGE_SLIME, 2.0),
            MonsterInfo(EncounterName.LOTS_OF_SLIMES, 1.0),
            MonsterInfo(EncounterName.EXORDIUM_THUGS, 1.5),
            MonsterInfo(EncounterName.EXORDIUM_WILDLIFE, 1.5),
            MonsterInfo(EncounterName.RED_SLAVER, 1.0),
            MonsterInfo(EncounterName.THREE_LOUSE, 2.0),
            MonsterInfo(EncounterName.TWO_FUNGI_BEASTS, 2.0),
        ]
        self.populate_monster_list(monsters, count, False)

    def generate_elites(self, count: int):
        monsters = [
            MonsterInfo(EncounterName.GREMLIN_NOB, 1.0),
            MonsterInfo(EncounterName.LAGAVULIN, 1.0),
            MonsterInfo(EncounterName.THREE_SENTRIES, 1.0),
        ]
        # Source normalizes weights here, but we don't have to. See MonsterInfo::roll.
        self.populate_monster_list(monsters, count, True)

    def initialize_boss(self):
        bosses = [
            EncounterName.THE_GUARDIAN,
            EncounterName.HEXAGHOST,
            EncounterName.SLIME_BOSS,
        ]
        random.shuffle(bosses)
        self.boss_list = bosses

    def initialize_event_list(self):
        # TODO more
        self.event_list = [
            EventName.BIG_FISH,
            EventName.BIG_FISH,
            EventName.BIG_FISH,
            EventName.BIG_FISH,
            EventName.BIG_FISH,
            EventName.BIG_FISH,
            EventName.BIG_FISH,
            EventName.BIG_FISH,
        ]

    def initialize_shrine_list(self):
        # TODO
        pass

    def initialize_relic_list(self):
        # TODO implement
        # TODO Ensure that we have equivalents to source's relicsToRemoveOnStart. I hit a problem with Player trying to
        # use that static on Dungeon (maybe self?) before it was available.
        pass
