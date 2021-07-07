from __future__ import annotations

import copy
import functools
import logging
import os
import pprint
import random
import uuid
from abc import ABC, ABCMeta, abstractmethod
from collections import deque
from enum import Enum
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    final,
)

import decapitate_the_spire as dts
from decapitate_the_spire.rng import Rng

MAX_HAND_SIZE = 10
MAX_NUM_MONSTERS_IN_GROUP = 5
MAX_CHARACTER_HEALTH = 1000
MAX_CHARACTER_BLOCK = 1000
MAX_POWER_STACKS = 1000
PLAYER_MAX_ENERGY = 1000
RELIC_MIN_INDICATOR = -1000
RELIC_MAX_INDICATOR = 1000
CARD_MAX_DAMAGE = 1000
CARD_MAX_BLOCK = 1000
CARD_MAX_MAGIC_NUMBER = 1000
CARD_MAX_COST = 100
MAX_POTION_SLOTS = 5
# TODO this will break with larger decks
MAX_CARD_GROUP_SIZE = 100
MONSTER_MAX_NUM_MOVES = 10
MAP_HEIGHT = 15
MAP_WIDTH = 7
MAP_PATH_DENSITY = 6

ACTION_0_LEN = 1 + MAX_HAND_SIZE + 2 * MAX_POTION_SLOTS
ACTION_1_LEN = 1 + MAX_NUM_MONSTERS_IN_GROUP
ACTION_1_ALL_FALSE_SLICE = [False] * ACTION_1_LEN
ACTION_1_SINGLE_TRUE = [False] * (ACTION_1_LEN - 1) + [True]

# TODO figure out how to do logging right
logger = logging.getLogger("dts")


def flatten(t: List[CardGroup]) -> List[Card]:
    # https://stackoverflow.com/a/952952
    return [item for sublist in t for item in sublist]


class CombatRewardScreen:
    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self.rewards: List[RewardItem] = []

    def _setup_item_reward(self):
        room = self.ctx.d.get_curr_room()
        self.rewards = room.rewards

        no_event_or_event_allows_card_rewards = (
            room.event is None or not room.event.no_cards_in_rewards
        )
        if no_event_or_event_allows_card_rewards and not isinstance(
            room, (TreasureRoom, RestRoom)
        ):
            card_reward = CardRewardItem(self.ctx)

            # Source if's this
            assert len(card_reward.cards) > 0
            self.rewards.append(card_reward)
            # TODO prayer wheel

    def open(self):
        self.ctx.screen = Screen.COMBAT_REWARD
        self._setup_item_reward()
        rewards_repr = os.linesep.join([r.__repr__() for r in self.rewards])
        logger.debug(f"Generated rewards:{os.linesep}{rewards_repr}")


class Screen(Enum):
    NONE = 0
    COMBAT_REWARD = 1


class GameMode(Enum):
    CHAR_SELECT = 0
    GAMEPLAY = 1
    DUNGEON_TRANSITION = 2


class CCG:
    """CardCrawlGame... the static-est of statics"""

    class Context:
        def __init__(self):
            # noinspection PyTypeChecker
            self.d: Dungeon = None
            self.combat_reward_screen = CombatRewardScreen(self)
            # TODO Source inits this to CHAR_SELECT and calls onEquip on starter relics under that mode
            self.mode = GameMode.CHAR_SELECT

            # This serves the same purpose as source's dungeonTransitionScreen. In source, it starts as the equivalent of False,
            # but I suspect I can get away with initing it True to avoid replicating source's convoluted init.
            self.is_transitioning_dungeon = True
            # I'm patching over all of source's convoluted init with this. Maybe this is good enough?
            # is_very_beginning = True

            # Source sets this as a static on dungeon, but I think we have to put it here because of how python statics work.
            # TODO consolidate this with our dungeon's player
            # noinspection PyTypeChecker
            self.player: Player = None
            self.create_dungeon: Optional[Callable[[Player], Dungeon]] = None
            self.screen = Screen.NONE
            self.action_manager = ActionManager(self)

            self.monster_hp_rng = Rng()
            self.ai_rng = Rng()
            self.shuffle_rng = Rng()
            self.card_rng = Rng()
            self.card_random_rng = Rng()
            self.misc_rng = Rng()
            self.map_rng = Rng()
            self.treasure_rng = Rng()
            self.relic_rng = Rng()
            self.potion_rng = Rng()
            self.monster_rng = Rng()
            self.event_rng = Rng()

            # Various things that source sticks on classes statically
            self.blizzard_potion_mod = 0

        def is_screen_up(self):
            return self.action_manager.outstanding_request is not None

        def reset(self):
            self.d = None
            self.mode = GameMode.CHAR_SELECT
            self.is_transitioning_dungeon = True
            self.player = None
            self.create_dungeon = None
            self.screen = Screen.NONE

        def update(self) -> bool:
            # TODO woefully incomplete

            # This is not source
            # if self.ctx.is_very_beginning:
            #     self.ctx.is_very_beginning = False

            did_something = False

            if self.mode == GameMode.CHAR_SELECT:
                did_something = True
                # Source creates player here, but we'll assume it's given
                for r in self.player.relics:
                    # I guess we hope this doesn't rely on dungeon being created? Does source make the same assumption?
                    r.on_equip()

                self.mode = GameMode.GAMEPLAY

            elif self.mode == GameMode.GAMEPLAY:

                if self.is_transitioning_dungeon:
                    did_something = True
                    # create dungeon, set on CCG
                    # open map screen if next dungeon not exordium
                    self.is_transitioning_dungeon = False
                    # if self.create_dungeon:
                    #     logger.debug('Using provided create dungeon func')
                    #     self.d = self.create_dungeon(self, self.player)
                    #     self.create_dungeon = None
                    # else:
                    #     logger.debug('Using default dungeon')
                    #     self.d = Exordium(self, self.player)
                else:
                    did_something |= self.d.update()

                # TODO check for dungeon beaten (isDungeonBeaten in source)
            else:
                raise NotImplementedError()

            return did_something

        def on_modify_power(self):
            self.player.hand.apply_powers()
            self.d.get_curr_room().monster_group.apply_powers()


class AscensionDependentValue:
    _V = TypeVar("_V")

    def __init__(self, base: _V, asc_value_pairs: List[Tuple[int, _V]]):
        self.base = base
        self.asc_value_pairs = asc_value_pairs

    @classmethod
    def resolve_adv_or_int(cls, adv_or_int: AscensionDependentValueOrInt):
        if isinstance(adv_or_int, cls):
            return adv_or_int.resolve()
        assert isinstance(adv_or_int, int)
        return adv_or_int

    @classmethod
    def of(cls, base: _V):
        return cls(base, [])

    def with_asc(self, ascension_threshold: int, value_if_ge: _V):
        self.asc_value_pairs.append((ascension_threshold, value_if_ge))
        return self

    def resolve(self, override_ascension=None) -> _V:
        def avp_key(a):
            return a[0]

        self.asc_value_pairs.sort(key=avp_key, reverse=True)

        asc = (
            override_ascension
            if override_ascension is not None
            else AscensionManager.get_ascension(self)
        )
        for ascension_threshold, value in self.asc_value_pairs:
            if asc >= ascension_threshold:
                return value

        return self.base


ADV = AscensionDependentValue
AscensionDependentValueOrInt = ADVOrInt = Union[AscensionDependentValue, int]


# class RewardType:
#     CARD = 0
#     GOLD = 1
#     RELIC = 2
#     POTION = 3
#     STOLEN_GOLD = 4
#     EMERALD_KEY = 5
#     SAPPHIRE_KEY = 6


class RewardItem(ABC):
    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self.ignore_reward = False

    @abstractmethod
    def claim_reward(self, action_1: int):
        ...

    def to_mask_slice(self):
        if self.ignore_reward:
            return ACTION_1_ALL_FALSE_SLICE

        return self._to_mask_slice_impl()

    @abstractmethod
    def _to_mask_slice_impl(self):
        ...


class PotionRewardItem(RewardItem):
    def __init__(self, ctx: CCG.Context, potion: Potion):
        super().__init__(ctx)
        self.potion = potion

    def __repr__(self):
        return f"Potion: {self.potion}"

    def claim_reward(self, action_1: int):
        # TODO sozu
        self.ctx.player.obtain_potion(self.potion)
        logger.debug(f"Claimed potion reward: {self.potion}")

    def _to_mask_slice_impl(self):
        if len(self.ctx.player.potions) < self.ctx.player.potion_slots:
            return ACTION_1_SINGLE_TRUE
        else:
            return ACTION_1_ALL_FALSE_SLICE


class CardRewardItem(RewardItem):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.cards = self.ctx.d.get_reward_cards()

    def __repr__(self):
        cards_repr = ", ".join([c.__repr__() for c in self.cards])
        return f"Cards: < {cards_repr} >"

    def _to_mask_slice_impl(self):
        assert len(self.cards) <= 4
        # TODO singing bowl
        # [ pick card 0..3, +2 max hp ]
        return [i < len(self.cards) for i in range(ACTION_1_LEN)]

    def claim_reward(self, action_1: int):
        # TODO busted crown, question card
        assert action_1 < len(self.cards)
        card = self.cards[action_1]
        logger.debug(f"Claimed card reward: {card}")
        self.ctx.player.obtain_card(card)


class GoldRewardItem(RewardItem):
    def __init__(self, ctx: CCG.Context, gold: int):
        super().__init__(ctx)
        self.base_gold = gold
        self.bonus_gold = 0

    def __repr__(self):
        return f"Gold: {self.base_gold} ({self.bonus_gold})"

    @property
    def total_gold(self):
        return self.base_gold + self.bonus_gold

    def increment_gold(self, added_gold: int):
        self.base_gold += added_gold

    def _apply_gold_bonus(self):
        # TODO golden idol
        ...

    def claim_reward(self, action_1: int):
        self.ctx.player.gain_gold(self.total_gold)
        logger.debug(f"Claimed gold reward: {self.total_gold}")

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class StolenGoldRewardItem(GoldRewardItem):
    def __repr__(self):
        return f"Stolen gold: {self.base_gold} ({self.bonus_gold})"


class LinkedRelicItem(RewardItem):
    def __init__(self, ctx: CCG.Context, relic_link: Optional[RelicRewardItem]):
        super().__init__(ctx)
        self.relic_link = relic_link
        # Ensure the linked item knows about self
        if self.relic_link:
            assert self.relic_link.relic_link is None
            self.relic_link.relic_link = self

    def trigger_relic_link(self):
        if self.relic_link:
            assert not self.relic_link.ignore_reward
            self.relic_link.ignore_reward = True
            logger.debug(f"Activated relic link for {self.relic_link}")


class RelicRewardItem(LinkedRelicItem):
    def __init__(
        self, ctx: CCG.Context, relic: Relic, relic_link: RelicRewardItem = None
    ):
        super().__init__(ctx, relic_link)
        self.relic = relic

    def __repr__(self):
        return f"Relic: {self.relic}"

    def claim_reward(self, action_1: int):
        assert not self.ignore_reward
        self.relic.instant_obtain(self.ctx.player, True)
        self.trigger_relic_link()

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class EmeraldKeyRewardItem(RewardItem):
    def __repr__(self):
        return "Emerald Key"

    def claim_reward(self, action_1: int):
        logger.debug("Claimed emerald key")
        self.ctx.player.obtain_emerald_key()

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class SapphireKeyRewardItem(LinkedRelicItem):
    def __repr__(self):
        return "Sapphire Key"

    def claim_reward(self, action_1: int):
        logger.debug("Claimed sapphire key")
        assert not self.ignore_reward
        self.ctx.player.obtain_sapphire_key()
        self.trigger_relic_link()

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class ProceedButton:
    @classmethod
    def on_click(cls, ctx: CCG.Context):
        """Source doesn't have this method; this is a shortened version of what happens when source's
        ProceedButton#update detects a click."""
        curr_room = ctx.d.get_curr_room()

        if isinstance(curr_room, MonsterRoomBoss):
            if isinstance(ctx.d, (TheBeyond, TheEnding)):
                # TODO implement routing for double boss, door/heart
                raise NotImplementedError()

        if ctx.screen == Screen.COMBAT_REWARD and not isinstance(
            curr_room, TreasureRoomBoss
        ):
            if isinstance(curr_room, MonsterRoomBoss):
                cls.go_to_treasure_room(ctx)
            elif isinstance(curr_room, EventRoom):
                # TODO check for specific events, see source
                raise NotImplementedError()

        elif isinstance(curr_room, TreasureRoomBoss):
            # TODO go to next dungeon
            raise NotImplementedError()

        elif not isinstance(curr_room, MonsterRoomBoss):
            # Source opens map screen here. Should be equivalent to setting map request.
            if ctx.d.curr_map_node.y < 0:
                logger.debug("Current node y < 0, using first path choice request")
                ctx.action_manager.outstanding_request = FirstPathChoiceRequest(
                    ctx, [n.has_edges() for n in ctx.d.mapp[0]]
                )
            elif ctx.d.curr_map_node.y + 1 >= ctx.d.boss_y:
                logger.debug(
                    "Current node just before boss, using boss path choice request"
                )
                ctx.action_manager.outstanding_request = BossPathChoiceRequest(ctx)
            else:
                logger.debug("Using ordinary path choice request")
                ctx.action_manager.outstanding_request = PathChoiceRequest(
                    ctx,
                    ctx.d.curr_map_node.left_successor_edge(),
                    ctx.d.curr_map_node.center_successor_edge(),
                    ctx.d.curr_map_node.right_successor_edge(),
                )

        # No clue if this is correct.
        ctx.screen = Screen.NONE

    @classmethod
    def go_to_treasure_room(cls, ctx: CCG.Context):
        node = MapRoomNode(-1, 15)
        node.room = TreasureRoomBoss(ctx)
        ctx.d.next_room_node = node
        # Source does this with nextRoomTransitionStart, but I think this is equivalent enough for us.
        ctx.d.next_room_transition()


class RoomPhase(Enum):
    COMBAT = 0
    EVENT = 1
    COMPLETE = 2
    INCOMPLETE = 3


class Room(ABC):
    room_symbol = None

    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self.monster_group: Optional[MonsterGroup] = None
        self.rewards: List[RewardItem] = []
        self.event: Optional[Event] = None
        self._phase: Optional[RoomPhase] = None
        self.base_rare_card_chance = 3
        self.base_uncommon_card_chance = 37
        self.rare_card_chance = self.base_rare_card_chance
        self.uncommon_card_chance = self.base_uncommon_card_chance
        self.is_battle_over = False
        self.cannot_lose = False
        self.reward_allowed = True
        self.skip_monster_turn = False
        # This is like AbstractRoom.waitTimer
        self.is_entering_combat = False
        self.mugged = False
        self.smoked = False

    def __repr__(self) -> str:
        return self.__class__.__name__

    def update(self) -> bool:  # noqa: C901
        did_something = False
        assert self.phase
        if self.phase == RoomPhase.EVENT:
            # Source calls event updateDialog
            # ...
            raise NotImplementedError()
        elif self.phase == RoomPhase.COMBAT:
            self.ctx.d.get_curr_room().monster_group.update()

            if not self.is_entering_combat:
                # Ordinary combat, not start, not end

                # if not self.ctx.action_manager.outstanding_request:
                # Source if's this, but I don't think it can happen since we handle these in Dungeon update
                assert not self.ctx.action_manager.outstanding_request
                did_something = self.ctx.action_manager.update()
                if (
                    not self.monster_group.are_monsters_basically_dead()
                    and self.ctx.player.current_health > 0
                ):
                    self.ctx.player.update_input()

                    # Not sure this goes here
                    if (
                        not did_something
                        and self.ctx.action_manager.phase
                        == ActionManager.Phase.WAITING_ON_USER
                        and not self.ctx.player.is_ending_turn
                    ):
                        # See if this happens
                        assert not self.ctx.player.end_turn_queued
                        logger.debug("Asking for user combat input")
                        self.ctx.action_manager.outstanding_request = (
                            CombatActionRequest(self.ctx)
                        )

                if self.ctx.player.is_ending_turn:
                    self.end_turn()
                    did_something = True
            else:
                if (
                    self.ctx.action_manager.current_action is None
                    and len(self.ctx.action_manager.actions) == 0
                ):
                    self.is_entering_combat = False
                else:
                    did_something = self.ctx.action_manager.update()

                if not self.is_entering_combat:
                    # This triggers on entering combat; don't let the predicate fool you.
                    logger.debug("Start combat")

                    self.ctx.action_manager.turn_has_ended = True
                    self.ctx.action_manager.add_to_bottom(
                        GainEnergyAndEnableControlsAction(
                            self.ctx, self.ctx.player.energy_manager.energy_master
                        )
                    )
                    self.ctx.player.apply_start_of_combat_pre_draw_logic()
                    self.ctx.action_manager.add_to_bottom(
                        DrawCardAction(self.ctx, self.ctx.player.game_hand_size)
                    )
                    self.ctx.player.apply_start_of_combat_logic()

                    self.skip_monster_turn = False
                    self.ctx.player.apply_start_of_turn_relics()
                    self.ctx.player.apply_start_of_turn_post_draw_relics()
                    self.ctx.player.apply_start_of_turn_cards()
                    self.ctx.player.apply_start_of_turn_powers()
                    # TODO orbs
                    self.ctx.action_manager.use_next_combat_actions()
                    did_something = True

            if self.is_battle_over and len(self.ctx.action_manager.actions) == 0:
                # End battle
                self.skip_monster_turn = False
                self.phase = RoomPhase.COMPLETE

                logger.debug(
                    f"Room says battle is over, changing state to {self.phase}"
                )

                if isinstance(self, MonsterRoomBoss):
                    base_gold = 100 + self.ctx.misc_rng.random(-5, 5)
                    gold = AscensionManager.check_ascension(
                        self, base_gold, 13, round(base_gold * 0.75)
                    )
                    self.add_gold_to_rewards(gold)
                elif isinstance(self, MonsterRoomElite):
                    self.add_gold_to_rewards(self.ctx.treasure_rng.random(25, 35))
                elif (
                    isinstance(self, MonsterRoom)
                    and not self.monster_group.have_monsters_escaped()
                ):
                    self.add_gold_to_rewards(self.ctx.treasure_rng.random(10, 20))

                # Handle dropping relics and potions
                if not isinstance(self, MonsterRoomBoss) or not isinstance(
                    self.ctx.d, (TheBeyond, TheEnding)
                ):
                    self.drop_reward()
                    self.add_potion_to_rewards()

                if self.reward_allowed:
                    if self.mugged:
                        logger.debug("Mugged")
                    elif self.smoked:
                        logger.debug("Smoked")
                    # Source has different calls to open based on smoked, mugged, but I'm not sure it matters.
                    self.ctx.combat_reward_screen.open()
                    # TODO If this is how combat rewards end up working, the screen obj is overkill
                    self.ctx.action_manager.outstanding_request = CombatRewardRequest(
                        self.ctx, self.ctx.combat_reward_screen.rewards
                    )

        elif self.phase == RoomPhase.COMPLETE:
            if not self.ctx.is_screen_up():
                logger.debug(
                    f"Room complete, emulating ProceedButton click from: {self.ctx.d.curr_map_node}"
                )
                ProceedButton.on_click(self.ctx)
                did_something = True

        return did_something

    def end_turn(self):
        self.ctx.player.apply_end_of_turn_triggers()
        self.ctx.action_manager.add_to_bottom(ClearCardQueueAction(self.ctx))
        self.ctx.action_manager.add_to_bottom(DiscardAtEndOfTurnAction(self.ctx))

        for c in flatten(
            [
                self.ctx.player.draw_pile,
                self.ctx.player.discard_pile,
                self.ctx.player.hand,
                self.ctx.player.draw_pile,
            ]
        ):
            c.reset_attributes()

        # hoveredCard

        self.ctx.action_manager.add_to_bottom(UnnamedRoomEndTurnAction(self.ctx))
        self.ctx.player.is_ending_turn = False

    def apply_end_of_turn_relics(self):
        for r in self.ctx.player.relics:
            r.on_player_end_turn()
        # blight

    def apply_end_of_turn_pre_card_powers(self):
        for p in self.ctx.player.powers:
            p.at_end_of_turn_pre_end_turn_cards(True)

    @property
    def phase(self):
        return self._phase

    @phase.setter
    def phase(self, new_phase):
        # logger.debug(f'Set phase to {new_phase}')
        self._phase = new_phase

    def drop_reward(self):
        ...

    def add_stolen_gold_to_rewards(self, amount: int):
        existing_stolen_gold_reward = next(
            (rew for rew in self.rewards if isinstance(rew, StolenGoldRewardItem)), None
        )
        if existing_stolen_gold_reward:
            existing_stolen_gold_reward.increment_gold(amount)
        else:
            self.rewards.append(StolenGoldRewardItem(self.ctx, amount))

    def add_potion_to_rewards(self):
        chance = 0
        if isinstance(self, (MonsterRoomElite, EventRoom)) or (
            isinstance(self, MonsterRoom)
            and not self.monster_group.have_monsters_escaped()
        ):
            chance = 40 + self.ctx.blizzard_potion_mod

        # TODO White Beast Statue
        if len(self.rewards) >= 4:
            chance = 0

        roll = self.ctx.potion_rng.random_from_0_to(99)
        logger.debug(f"Potion drop chance: {chance} vs roll {roll}")
        if roll >= chance:
            self.ctx.blizzard_potion_mod += 10
        else:
            potion = self.ctx.d.return_random_potion()
            self.ctx.blizzard_potion_mod -= 10
            logger.debug(f"Dropping potion {potion}")
            self.rewards.append(PotionRewardItem(self.ctx, potion))

    def add_relic_to_rewards(self, tier: RelicTier):
        relic = self.ctx.d.return_random_relic(tier)
        logger.debug(f"Add relic to reward: {tier} -> {relic}")
        self.rewards.append(RelicRewardItem(self.ctx, relic))

    def add_gold_to_rewards(self, gold: int):
        logger.debug(f"Add gold to reward: {gold}")
        # Strict type check here because StolenGoldRewardItem inherits from GoldRewardItem
        existing_gold_reward = next(
            (ri for ri in self.rewards if type(ri) == GoldRewardItem), None
        )
        if existing_gold_reward:
            # noinspection PyUnresolvedReferences
            existing_gold_reward.increment_gold(gold)
        else:
            self.rewards.append(GoldRewardItem(self.ctx, gold))

    def add_sapphire_key(self, linked_reward: RelicRewardItem):
        logger.debug(f"Add sapphire key to rewards, linked to {linked_reward}")
        self.rewards.append(SapphireKeyRewardItem(self.ctx, linked_reward))

    def end_battle(self):
        logger.debug("Enter")
        # Setting this triggers end of battle logic in AbstractRoom#update
        self.is_battle_over = True
        # TODO meat on the bone

        self.ctx.player.on_victory()
        self.ctx.action_manager.clear()
        # There's more in source, but it doesn't seem relevant

    @abstractmethod
    def on_player_entry(self):
        ...

    def get_card_rarity(self, roll: int, use_alternation: bool = True):
        self.rare_card_chance = self.base_rare_card_chance
        self.uncommon_card_chance = self.base_uncommon_card_chance
        if use_alternation:
            self.alter_card_rarity_probabilities()

        if roll < self.rare_card_chance:
            rarity = CardRarity.RARE
        elif roll >= (self.rare_card_chance + self.uncommon_card_chance):
            rarity = CardRarity.COMMON
        else:
            rarity = CardRarity.UNCOMMON

        logger.debug(
            f"Roll to card rarity: {roll} vs "
            f"{self.rare_card_chance}/{self.rare_card_chance + self.uncommon_card_chance} -> {rarity}"
        )
        return rarity

    def alter_card_rarity_probabilities(self):
        for r in self.ctx.player.relics:
            self.rare_card_chance = r.change_rare_card_reward_chance(
                self.rare_card_chance
            )

        for r in self.ctx.player.relics:
            self.uncommon_card_chance = r.change_uncommon_card_reward_chance(
                self.uncommon_card_chance
            )


class EmptyRoom(Room):
    def on_player_entry(self):
        ...


class MonsterRoom(Room):
    room_symbol = "M"

    def __init__(self, ctx: CCG.Context, monster_group: MonsterGroup = None):
        super().__init__(ctx)
        self.monster_group: MonsterGroup = monster_group
        self.phase = RoomPhase.COMBAT

    def __repr__(self):
        s = f"{self.__class__.__name__} {self.phase.name}"
        if self.phase == RoomPhase.COMBAT:
            s += f"{os.linesep}{self.monster_group}"
        return s

    def on_player_entry(self):
        if self.monster_group is None:
            self.monster_group = self.ctx.d.get_monster_for_room_creation()
        self.monster_group.initialize()

        self.is_entering_combat = True


class MonsterRoomElite(MonsterRoom):
    room_symbol = "E"

    def __init__(self, ctx: CCG.Context, monster_group: MonsterGroup = None):
        self.base_rare_card_chance = 10
        self.base_uncommon_card_chance = 40
        super().__init__(ctx, monster_group)

    def apply_emerald_elite_buff(self):
        # TODO implement
        ...

    def drop_reward(self):
        tier = self._return_random_relic_tier()
        self.add_relic_to_rewards(tier)
        # TODO black star

        if (
            not self.ctx.player.has_emerald_key
            and len(self.rewards) > 0
            and self.ctx.d.curr_map_node.has_emerald_key
        ):
            self.rewards.append(EmeraldKeyRewardItem(self.ctx))

    def on_player_entry(self):
        if self.monster_group is None:
            self.monster_group = self.ctx.d.get_elite_monster_for_room_creation()
            self.monster_group.initialize()

        self.is_entering_combat = True

    def _return_random_relic_tier(self):
        roll = self.ctx.relic_rng.random_from_0_to(99)

        if roll < 50:
            tier = RelicTier.COMMON
        elif roll > 82:
            tier = RelicTier.RARE
        else:
            tier = RelicTier.UNCOMMON

        logger.debug(f"Relic tier roll: {roll} -> {tier}")
        return tier


class MonsterRoomBoss(MonsterRoom):
    room_symbol = "B"

    def on_player_entry(self):
        self.monster_group = self.ctx.d.get_boss()
        assert self.monster_group
        del self.ctx.d.boss_list[0]
        self.monster_group.initialize()

        self.is_entering_combat = True

    def get_card_rarity(self, roll: int, use_alternation: bool = True):
        return CardRarity.RARE


class EventRoom(Room):
    room_symbol = "?"

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.phase = RoomPhase.EVENT
        self.event = None

    def on_player_entry(self):
        self.event = self.ctx.d.generate_event()
        self.event.on_enter_room()


class ShopRoom(Room):
    room_symbol = "$"

    def __init__(self, ctx: CCG.Context):
        self.base_rare_card_chance = 9
        self.base_uncommon_card_chance = 37
        super().__init__(ctx)
        # TODO impl
        self.merchant = None
        self.phase = RoomPhase.COMPLETE

    def on_player_entry(self):
        pass


class TreasureRoom(Room):
    room_symbol = "T"

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.phase = RoomPhase.COMPLETE

    def on_player_entry(self):
        chest = self.ctx.d.get_random_chest()
        chest.open()
        self.ctx.action_manager.outstanding_request = CombatRewardRequest(
            self.ctx, self.rewards
        )


class TreasureRoomBoss(Room):
    room_symbol = "X"

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)

    def on_player_entry(self):
        chest = BossChest(self.ctx)
        chest.open()
        self.ctx.action_manager.outstanding_request = BossChestRequest(
            self.ctx, [RelicRewardItem(self.ctx, r) for r in chest.relics]
        )


class NeowRoom(Room):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.phase = RoomPhase.EVENT
        self.event = NeowEvent(ctx)
        self.event.on_enter_room()

    def on_player_entry(self):
        raise Exception("Source never calls this")


class DebugNoOpNeowRoom(Room):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.phase = RoomPhase.EVENT
        self.event = DebugNoOpNeowEvent(ctx)
        self.event.on_enter_room()

    def on_player_entry(self):
        raise Exception("Source never calls this")


class RestRoom(Room):
    room_symbol = "R"

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.phase = RoomPhase.INCOMPLETE
        self.options: List[CampfireOption] = []

    def on_player_entry(self):
        for r in self.ctx.player.relics:
            r.on_enter_rest_room()

        # Source does this in CampfireUI::initializeButtons
        self.options.append(
            RestOption(
                self.ctx,
            )
        )
        self.options.append(
            SmithOption(self.ctx, self.ctx.player.master_deck.has_upgradable_cards())
        )
        for r in self.ctx.player.relics:
            r.add_campfire_option(self.options)
        # TODO other options

        for op in self.options:
            op.usable = all(
                (r.can_use_campfire_option(op) for r in self.ctx.player.relics)
            )

        if not self.ctx.player.has_ruby_key:
            self.options.append(
                RecallOption(
                    self.ctx,
                )
            )

        cannot_proceed = all((not op.usable for op in self.options))
        if cannot_proceed:
            self.phase = RoomPhase.COMPLETE
        else:
            self.ctx.action_manager.outstanding_request = CampfireRequest(
                self.ctx, self.options
            )

    def get_card_rarity(self, roll: int, use_alternation: bool = True):
        # Source has funky overloads for this method. This may be wrong.
        if use_alternation:
            logger.warning(f"Ignoring {use_alternation=}")
        return super().get_card_rarity(roll, False)


class CampfireOption(ABC):
    def __init__(self, ctx: CCG.Context, usable: bool = True):
        self.ctx = ctx
        self.usable = usable

    def __repr__(self):
        unusable_repr = "" if self.usable else " (N/A)"
        return f"{self.__class__.__name__}{unusable_repr}"

    @abstractmethod
    def use_option(self):
        ...


class RestOption(CampfireOption):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, True)
        # TODO coffee dripper
        # TODO regal pillow, dream catcher
        # Source double calculates this in RestOption ctor and CampfireSleepEffect::update
        self.heal_amount = int(0.3 * self.ctx.player.max_health)

    def __repr__(self):
        return f"Heal for {self.heal_amount}"

    def use_option(self):
        logger.debug(f"Resting for {self.heal_amount}")
        self.ctx.player.heal(self.heal_amount)

        for r in self.ctx.player.relics:
            r.on_rest()

        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE
        self.ctx.action_manager.outstanding_request = None


class SmithOption(CampfireOption):
    def use_option(self):
        logger.debug("Smithing")
        for r in self.ctx.player.relics:
            r.on_smith()

        self.ctx.action_manager.outstanding_request = None
        # Definitely not sure this belongs here
        # self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE
        self.ctx.action_manager.outstanding_request = GridSelectRequest(
            self.ctx, self.ctx.player.master_deck.get_upgradable_cards()
        )


class RecallOption(CampfireOption):
    # def __init__(self, active: bool):
    #     super().__init__(active)

    def use_option(self):
        # TODO Is it as simple as this?
        logger.debug("Player recalled, got ruby key")
        self.ctx.player.has_ruby_key = True
        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE
        self.ctx.action_manager.outstanding_request = None


class Event(ABC):
    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self.no_cards_in_rewards = False

    @abstractmethod
    def button_effect(self, num: int):
        ...

    @abstractmethod
    def on_enter_room(self):
        ...

    @staticmethod
    def enter_combat(ctx: CCG.Context):
        # This is used by events that can start combat, like Dead Adventurer
        logger.debug("Event starting combat")
        ctx.d.get_curr_room().phase = RoomPhase.COMBAT
        ctx.d.get_curr_room().monster_group.initialize()
        ctx.d.get_curr_room().is_entering_combat = True
        ctx.player.pre_battle_prep()


class DebugThrowOnEnterEvent(Event):
    def button_effect(self, num: int):
        pass

    def on_enter_room(self):
        raise NotImplementedError()


class SimpleChoiceEvent(Event, metaclass=ABCMeta):
    num_choices_if_always_same = None

    def __init__(self, ctx: CCG.Context, num_choices: int = None):
        super().__init__(ctx)
        assert bool(self.num_choices_if_always_same) != bool(num_choices)
        self.num_choices = (
            num_choices if num_choices is not None else self.num_choices_if_always_same
        )

    @final
    def button_effect(self, num: int):
        logger.debug(
            f"For simple event {self.__class__.__name__} picked {num} / {self.num_choices}"
        )
        assert num < self.num_choices
        self.button_effect_impl(num)

    @abstractmethod
    def button_effect_impl(self, num: int):
        ...

    def on_enter_room(self):
        self.ctx.action_manager.outstanding_request = SimpleChoiceEventRequest(
            self.ctx, self
        )


class NeowEvent(SimpleChoiceEvent):
    num_choices_if_always_same = 2

    def button_effect_impl(self, num: int):
        logger.debug(f"Player chose neow reward {num}")
        assert self.ctx.d.get_curr_room().event is self
        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE


class DebugNoOpNeowEvent(SimpleChoiceEvent):
    num_choices_if_always_same = 1

    def button_effect_impl(self, num: int):
        logger.debug(f"Player chose neow reward {num}")
        assert self.ctx.d.get_curr_room().event is self
        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE

    def on_enter_room(self):
        r = SimpleChoiceEventRequest(self.ctx, self)
        self.ctx.action_manager.outstanding_request = r
        # This is wonky. :shrug:
        r.set_response(ActionGenerator.pick_simple_combat_reward(0))


class BigFishEvent(SimpleChoiceEvent):
    num_choices_if_always_same = 3

    def button_effect_impl(self, num: int):
        # TODO impl
        pass


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


Map = List[List[MapRoomNode]]
MapCoord = Tuple[int, int]
ActionCoord = Tuple[int, int]
ActionCoordConsumer = Callable[[ActionCoord], None]
ActionMaskSlices = List[List[bool]]


class ActionMask:
    def __init__(
        self,
        play_card_slices: ActionMaskSlices,
        end_turn_slice: ActionMaskSlices = None,
        use_potion_slices: ActionMaskSlices = None,
        discard_potion_slices: ActionMaskSlices = None,
    ):
        self.play_card_slices = play_card_slices

        self.end_turn_slice = (
            end_turn_slice if end_turn_slice is not None else [ACTION_1_ALL_FALSE_SLICE]
        )

        if use_potion_slices is None:
            self.use_potion_slices = [
                ACTION_1_ALL_FALSE_SLICE for _ in range(MAX_POTION_SLOTS)
            ]
        else:
            self.use_potion_slices = use_potion_slices

        if discard_potion_slices is None:
            self.discard_potion_slices = [
                ACTION_1_ALL_FALSE_SLICE for _ in range(MAX_POTION_SLOTS)
            ]
        else:
            self.discard_potion_slices = discard_potion_slices

        assert (
            len(self.end_turn_slice) == 1
            and len(self.end_turn_slice[0]) == ACTION_1_LEN
        )
        assert len(self.play_card_slices) == MAX_HAND_SIZE and all(
            (
                len(self.play_card_slices[i]) == ACTION_1_LEN
                for i in range(MAX_HAND_SIZE)
            )
        )

    def to_raw(self) -> List[List[bool]]:
        return (
            self.end_turn_slice
            + self.play_card_slices
            + self.use_potion_slices
            + self.discard_potion_slices
        )


class AllFalseActionMask(ActionMask):
    def __init__(self):
        play_card_slices = [ACTION_1_ALL_FALSE_SLICE] * MAX_HAND_SIZE
        super().__init__(play_card_slices)


class ActionDispatcher:
    @staticmethod
    def dispatch(
        action: ActionCoord,
        end_turn_handler: ActionCoordConsumer,
        play_card_handler: ActionCoordConsumer,
        use_potion_handler: ActionCoordConsumer,
        discard_potion_handler: ActionCoordConsumer,
    ):

        # target_index = action[1] if action[1] < MAX_NUM_MONSTERS_IN_GROUP else None

        action_dim_0 = action[0]
        if action_dim_0 < ActionGenerator.region_sizes[0]:
            # assert target_index is None
            end_turn_handler((action_dim_0, action[1]))
            return
        action_dim_0 -= ActionGenerator.region_sizes[0]

        if action_dim_0 < ActionGenerator.region_sizes[1]:
            play_card_handler((action_dim_0, action[1]))
            return
        action_dim_0 -= ActionGenerator.region_sizes[1]

        if action_dim_0 < ActionGenerator.region_sizes[2]:
            use_potion_handler((action_dim_0, action[1]))
            return
        action_dim_0 -= ActionGenerator.region_sizes[2]

        if action_dim_0 < ActionGenerator.region_sizes[2]:
            # assert target_index is None
            discard_potion_handler((action_dim_0, action[1]))
            return

        raise ValueError(action)


class ActionGenerator:
    region_sizes = [1, MAX_HAND_SIZE, MAX_POTION_SLOTS, MAX_POTION_SLOTS]

    @classmethod
    def _resolve(cls, region_index, action_within_region):
        return sum(cls.region_sizes[0:region_index]) + action_within_region

    @classmethod
    def end_turn(cls):
        return cls._resolve(0, 0), MAX_NUM_MONSTERS_IN_GROUP

    @classmethod
    def done_picking_discards(cls):
        return cls.end_turn()

    @classmethod
    def play_card(cls, card_index: int, target_index: Optional[int]):
        return (
            cls._resolve(1, card_index),
            MAX_NUM_MONSTERS_IN_GROUP if target_index is None else target_index,
        )

    @classmethod
    def play_first_card_of_type(
        cls, cg: CardGroup, card_type: Type[Card], target_index: Optional[int]
    ):
        # Find first instance of card type
        card_index = next((i for i, c in enumerate(cg) if isinstance(c, card_type)))
        return cls.play_card(card_index, target_index)

    @classmethod
    def pick_discard_from_hand(cls, card_index: int):
        return cls.play_card(card_index, None)

    @classmethod
    def use_potion(cls, potion_index: int, target_index: Optional[int]):
        return (
            cls._resolve(2, potion_index),
            MAX_NUM_MONSTERS_IN_GROUP if target_index is None else target_index,
        )

    @classmethod
    def discard_potion(cls, potion_index: int):
        return cls._resolve(3, potion_index), MAX_NUM_MONSTERS_IN_GROUP

    @classmethod
    def pick_neow_reward(cls, b: bool):
        return cls.play_card(1 if b else 0, None)

    @classmethod
    def pick_first_path(cls, path_index: int):
        return cls.play_card(path_index, None)

    @classmethod
    def pick_first_path_mini_dungeon_elite(cls):
        return cls.play_card(1, None)

    @classmethod
    def pick_first_path_mini_dungeon_rest(cls):
        return cls.play_card(2, None)

    @classmethod
    def pick_first_path_mini_dungeon_treasure(cls):
        return cls.play_card(3, None)

    @classmethod
    def pick_first_path_mini_dungeon_event(cls):
        return cls.play_card(4, None)

    @classmethod
    def pick_first_path_mini_dungeon_shop(cls):
        return cls.play_card(5, None)

    @classmethod
    def pick_any_valid_path(cls, request: PathChoiceRequest):
        if request.left_available:
            i = 0
        elif request.center_available:
            i = 1
        elif request.right_available:
            i = 2
        else:
            raise Exception()
        return cls.play_card(i, None)

    @classmethod
    def pick_simple_combat_reward(cls, reward_index: int):
        return cls.play_card(reward_index, None)

    @classmethod
    def pick_specific_combat_reward_type(
        cls, rewards: List[RewardItem], reward_type: Type[RewardItem]
    ):
        reward_i, _ = next(
            (i, rew) for i, rew in enumerate(rewards) if isinstance(rew, reward_type)
        )
        return cls.pick_simple_combat_reward(reward_i)

    @classmethod
    def pick_card_combat_reward(cls, reward_index: int, card_index: int):
        return cls.play_card(reward_index, card_index)

    @classmethod
    def end_combat_reward(cls):
        return cls.end_turn()

    @classmethod
    def proceed_to_boss(cls):
        return cls.end_turn()

    @classmethod
    def pick_specific_campfire_option(
        cls, options: List[CampfireOption], option_type: Type[CampfireOption]
    ):
        op_i = next(i for i, op in enumerate(options) if isinstance(op, option_type))
        return cls.play_card(op_i, None)

    @classmethod
    def pick_grid_select_index(cls, i: int):
        action = GridSelectRequest.translate_index_to_action(i)
        return cls.play_card(action[0], action[1])

    @classmethod
    def pick_simple_event_choice(cls, i: int):
        return cls.play_card(i, None)

    @classmethod
    def end_treasure_room(cls):
        return cls.end_turn()

    @classmethod
    def go_to_boss(cls):
        return cls.end_turn()

    @classmethod
    def pick_boss_relic(cls, relic_index: int):
        return cls.play_card(relic_index, None)


class PlayerRequest(ABC):
    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self._action_response: Optional[ActionCoord] = None

    def __repr__(self):
        return f"{self.__class__.__name__}"

    def clear_response(self):
        logger.debug(f"Cleared response for {self}")
        self._action_response = None

    def set_response(self, action: ActionCoord):
        logger.debug(f"Recorded response {action} for {self}")
        self._action_response = action

    @property
    def is_waiting_for_response(self) -> bool:
        return self._action_response is None

    @final
    # def execute(self, action: ActionCoord):
    def execute(self):
        assert self._action_response is not None
        ActionDispatcher.dispatch(
            self._action_response,
            self.handle_end_turn_action,
            self.handle_play_card_action,
            self.handle_use_potion_action,
            self.handle_destroy_potion_action,
        )

    def handle_end_turn_action(self, action: ActionCoord):
        raise Exception()

    def handle_play_card_action(self, action: ActionCoord):
        raise Exception()

    def handle_use_potion_action(self, action: ActionCoord):
        raise Exception()

    def handle_destroy_potion_action(self, action: ActionCoord):
        raise Exception()

    @abstractmethod
    def generate_action_mask(self) -> ActionMask:
        ...

    def throwing_handler(self, _):
        raise Exception()

    @classmethod
    def with_optional_target_index(cls, handler: Callable[[int, Optional[int]], None]):
        def safing_wrapper(action: ActionCoord):
            safe_action_1 = action[1] if action[1] < MAX_NUM_MONSTERS_IN_GROUP else None
            handler(action[0], safe_action_1)

        return safing_wrapper

    @classmethod
    def with_no_target_index(cls, handler: Callable[[int], None]):
        def safing_wrapper(action: ActionCoord):
            safe_action_1 = action[1] if action[1] < MAX_NUM_MONSTERS_IN_GROUP else None
            assert safe_action_1 is None
            handler(action[0])

        return safing_wrapper


class Game:
    def __init__(
        self,
        create_player: Callable[[CCG.Context], Player],
        create_dungeon: Callable[[CCG.Context], Dungeon],
        relics: Callable[[CCG.Context], List[Relic]] = None,
    ):
        self.logger = logging.getLogger("dts.Game")
        self.step_has_been_called = False
        self.ctx = CCG.Context()
        # CCG.ctx = self.ctx

        player = create_player(self.ctx)
        self.ctx.player = player
        d = create_dungeon(self.ctx)
        self.ctx.d = d
        # self.ctx.create_dungeon = create_dungeon
        # self.id = uuid.uuid4()

        if relics:
            for r in relics(self.ctx):
                # TODO This probably breaks when we do multi room.
                r.instant_obtain(player, True)

        self.game_over_and_won = None

        # If we model "game start" as going here, I think we look at CardCrawlGame#update, specifically the logic
        # around setting CardCrawlGame#mode from CHAR_SELECT to GAMEPLAY.

        # Is it right to call this now?
        while self.ctx.update():
            ...

        # May not be correct to call this here. The initial nrt call comes from AbstractDungeon#updateFading, via
        # AbstractDungeon#fadeOut, via AbstractDungeon#nextRoomTransitionStart. nrts is called from several spots, like
        # DungeonMap (for going to boss), MapRoomNode (when a room on dungeon map is clicked), and the various "go to X
        # room" methods in ProceedButton.
        # self.dungeon = CCG.ctx.d
        self.history = []

    def __repr__(self):
        if self.game_over_and_won is None:
            room = self.ctx.d.get_curr_room()
            if isinstance(room, MonsterRoom):
                monsters = os.linesep.join([m.__repr__() for m in room.monster_group])
            else:
                monsters = ""

            return f"{self.ctx.player}{os.linesep}{monsters}"
        elif self.game_over_and_won:
            return "Game over: win"
        else:
            return "Game over: loss"

    def step(self, action: ActionCoord) -> Tuple[float, bool, dict]:
        self.step_has_been_called = True
        reward = 0.0
        is_terminal = False
        info = {}

        # Give a reward per floor climbed
        # start_floor = self.ctx.d.floor_num
        # start_total_monster_health = None
        # # start_monster_health_proportion = None
        # if self.ctx.d.get_curr_room().phase == RoomPhase.COMBAT:
        #     start_total_monster_health = sum([m.current_health for m in self.ctx.d.get_curr_room().monster_group])
        #     m = self.ctx.d.get_curr_room().monster_group[0]
        #     # start_monster_health_proportion = m.current_health / m.max_health
        start_player_health = self.ctx.player.current_health

        # Ensure action is valid
        if not self.is_action_valid(action):
            # reward, is_terminal, info = self._pinch(action)
            # logger.debug(f'Rewarding {reward} for illegal move, now {reward}')
            # assert False
            self.history.append((action, "invalid"))
            return self._pinch(action)
        else:
            # reward += 0.001
            # Only set response if action is valid, right?
            if self.ctx.action_manager.outstanding_request:
                self.ctx.action_manager.outstanding_request.set_response(action)

            logger.debug("Before dungeon update")
            while self.ctx.update() and not self.ctx.player.is_dead:
                ...
            logger.debug(f"After dungeon update:{os.linesep}{self}")

            # assert CCG.d is self.ctx.d
            # assert CCG.player is self.ctx.player
            if self.ctx.player.is_dead:
                logger.debug("Player is dead, returning loss")
                self.history.append(
                    (action, self.ctx.action_manager.outstanding_request)
                )
                return self._loss()
            elif isinstance(
                self.ctx.action_manager.outstanding_request, BossChestRequest
            ):
                logger.debug("Boss beat, returning win")
                self.history.append(
                    (action, self.ctx.action_manager.outstanding_request)
                )
                return self._win()
            else:
                if self.ctx.action_manager.outstanding_request is None:
                    self.history.append(
                        (action, self.ctx.action_manager.outstanding_request)
                    )
                    print(self.ctx.d)
                    assert False

            # if self.ctx.d.floor_num > start_floor:
            #     # Do it like this for floor skips like secret portal?
            #     amount = self.ctx.d.floor_num - start_floor
            #     reward += amount
            #     logger.debug(f'Rewarding {amount} for floor increment, now {reward}')
            # if self.ctx.d.get_curr_room().phase == RoomPhase.COMBAT and start_total_monster_health is not None:
            #     if sum([m.current_health for m in self.ctx.d.get_curr_room().monster_group]) - start_total_monster_health < 0:
            #         amount = 1
            #         reward += amount
            #         logger.debug(f'Rewarding {amount} for monster damage, now {reward}')
            player_health_change = self.ctx.player.current_health - start_player_health
            # health_change_reward_multiplier = .005
            health_change_reward_multiplier = 1
            reward += player_health_change * health_change_reward_multiplier

        self.history.append((action, self.ctx.action_manager.outstanding_request))
        return reward, is_terminal, info

    def _win(self):
        self.logger.debug("Game over: WIN")
        self.game_over_and_won = True
        return 1.0, True, {"win": True}

    def _loss(self):
        self.logger.debug("Game over: LOSS")
        self.game_over_and_won = False
        return -1.0, True, {"win": False}

    def _pinch(self, action):
        self.logger.debug(f"Pinching for illegal move: {action}")
        return -0.001, False, {"illegal": True}
        # return -1.0, True, {'illegal': True}

    def generate_action_mask(self) -> List[List[bool]]:
        # Action dim 0: [end turn, play card 0..n, use potion 0..n]
        # Action dim 1: [target 0..n, no target]

        request = self.ctx.action_manager.outstanding_request
        if not request:
            assert self.game_over or not self.step_has_been_called
            return AllFalseActionMask().to_raw()

        action_mask = request.generate_action_mask()
        return action_mask.to_raw()

    def is_action_valid(self, action: ActionCoord) -> bool:
        mask = self.generate_action_mask()
        return mask[action[0]][action[1]]

    @property
    def game_over(self):
        return self.game_over_and_won is not None


# Source appears to only use this once, to check for DAMAGE. Original is more expressive.
class ActionType(Enum):
    ANY_OTHER = 0
    DAMAGE = 1


class Action(ABC):
    def __init__(
        self,
        ctx: CCG.Context,
        amount: Optional[int] = None,
        action_type: ActionType = ActionType.ANY_OTHER,
    ):
        self.ctx = ctx
        self.action_type: ActionType = action_type
        self.amount: Optional[int] = amount

    def __repr__(self):
        amount_repr = "" if self.amount is None else f" {self.amount}"
        return f"{self.__class__.__name__}{amount_repr}"

    @abstractmethod
    def act(self):
        ...


class TargetCharacterAction(Action, metaclass=ABCMeta):
    def __init__(self, ctx: CCG.Context, target: Character, amount: int = None):
        super().__init__(ctx, amount)
        self.target: Character = target


class TargetMonsterAction(Action, metaclass=ABCMeta):
    def __init__(self, ctx: CCG.Context, target: Monster, amount: int = None):
        super().__init__(ctx, amount)
        self.target: Monster = target


class UnnamedRoomEndTurnAction(Action):
    """This corresponds to an anonymous action defined in AbstractRoom#endTurn"""

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)

    def act(self):
        self.ctx.action_manager.add_to_bottom(EndTurnAction(self.ctx))
        # WaitAction, cosmetic
        if not self.ctx.d.get_curr_room().skip_monster_turn:
            self.ctx.action_manager.add_to_bottom(
                MonsterStartTurnAction(
                    self.ctx, self.ctx.d.get_curr_room().monster_group
                )
            )

        self.ctx.action_manager.monster_attacks_queued = False


class EndTurnAction(Action):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)

    def act(self):
        self.ctx.action_manager.end_turn()
        # EndTurnEffect appears cosmetic


class NewQueueCardAction(Action):
    def __init__(
        self,
        ctx: CCG.Context,
        card: Card = None,
        immediate_card: bool = False,
        autoplay_card: bool = False,
    ):
        super().__init__(ctx)
        self.card = card

    def act(self):
        # There's more to this action, but I'm just implementing what I need for now
        if not self.card:
            # I think source calls a CardQueueItem with null card an "end turn card". See
            # NewQueueCardAction::queueContainsEndTurnCard
            if not self._queue_contains_end_turn_card():
                self.ctx.action_manager.card_queue.appendleft(
                    CardQueueItem(None, None, 0)
                )
        else:
            raise NotImplementedError()

    def _queue_contains_end_turn_card(self):
        return any((cqi.card is None for cqi in self.ctx.action_manager.card_queue))


class ExhaustSpecificCardAction(Action):
    def __init__(self, ctx: CCG.Context, target_card: Card, card_group: CardGroup):
        super().__init__(ctx)
        self.target_card = target_card
        self.card_group = card_group

    def act(self):
        self.card_group.move_to_exhaust_pile(self.target_card)
        self.target_card.exhaust_on_use_once = False
        self.target_card.free_to_play_once = False


class UseCardAction(Action):
    def __init__(self, ctx: CCG.Context, card: Card, target: Character = None):
        # TODO lots missing here: rebound
        super().__init__(ctx)
        self.target = target
        self.target_card = card
        self.exhaust_card = card.exhaust or card.exhaust_on_use_once

        for p in self.ctx.player.powers:
            if not card.dont_trigger_on_use_card:
                p.on_use_card(card, self)

        for r in self.ctx.player.relics:
            if not card.dont_trigger_on_use_card:
                r.on_use_card(card, self)

        for c in flatten(
            [
                self.ctx.player.hand,
                self.ctx.player.discard_pile,
                self.ctx.player.draw_pile,
            ]
        ):
            if not card.dont_trigger_on_use_card:
                c.trigger_on_card_played(card)

        for m in self.ctx.d.get_curr_room().monster_group:
            for p in m.powers:
                if not card.dont_trigger_on_use_card:
                    p.on_use_card(card, self)

    def act(self):
        for p in self.ctx.player.powers:
            if not self.target_card.dont_trigger_on_use_card:
                p.on_after_use_card(self.target_card, self)

        for m in self.ctx.d.get_curr_room().monster_group:
            for p in m.powers:
                if not self.target_card.dont_trigger_on_use_card:
                    p.on_after_use_card(self.target_card, self)

        self.target_card.free_to_play_once = False
        self.target_card.is_in_autoplay = False
        # TODO purge on use

        if self.target_card.card_type == CardType.POWER:
            # Does this ever get called? Assert and let's see.
            # assert False
            # noinspection PyUnreachableCode
            self.ctx.player.hand.empower(self.target_card)
            self.ctx.player.hand.apply_powers()
            self.ctx.player.card_in_use = None
            return

        self.ctx.player.card_in_use = None
        # TODO strange spoon

        if self.exhaust_card:
            self.ctx.player.hand.move_to_exhaust_pile(self.target_card)
        else:
            self.ctx.player.hand.move_to_discard_pile(self.target_card)

        self.target_card.exhaust_on_use_once = False
        self.target_card.dont_trigger_on_use_card = False
        self.ctx.action_manager.add_to_bottom(HandCheckAction(self.ctx))

    def __repr__(self):
        return f"Use card {self.target_card}"


class GainBlockAction(TargetCharacterAction):
    def __init__(self, ctx: CCG.Context, target: Character, amount: int):
        super().__init__(ctx, target, amount)

    def __repr__(self):
        return f"+Block {self.amount}"

    def act(self):
        self.target.add_block(self.amount)


class DamageAction(TargetCharacterAction):
    def __init__(
        self,
        ctx: CCG.Context,
        target: Character,
        damage_info: DamageInfo,
        source: Character,
        steal_gold_amount: int = 0,
    ):
        super().__init__(ctx, target)
        self.source = source
        self.damage_info = damage_info
        self.steal_gold_amount = steal_gold_amount

    def __repr__(self):
        return f"{self.target.name} takes damage: {self.damage_info}"

    def act(self):
        if (
            self._should_cancel_action()
            and self.damage_info.damage_type == DamageType.THORNS
        ):
            logger.debug(f"Canceling {self}")
        elif self.damage_info.damage_type == DamageType.THORNS and (
            self.damage_info.owner.is_dying or self.damage_info.owner.half_dead
        ):
            logger.debug(f"Canceling {self}")
        else:
            if self.steal_gold_amount != 0:
                self._steal_gold()

            self.target.damage(self.damage_info)

            if self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
                self.ctx.action_manager.clear_post_combat_actions()

    def _steal_gold(self):
        if self.target.gold != 0:
            if self.target.gold < self.steal_gold_amount:
                self.steal_gold_amount = self.target.gold

            logger.debug(f"Stealing {self.steal_gold_amount} from {self.target.name}")
            self.target.gold -= self.steal_gold_amount

    def _should_cancel_action(self):
        # Source if's this
        assert self.target is not None
        return self.source.is_dying or self.target.is_dead_or_escaped()


class DrawCardAction(Action):
    def __init__(self, ctx: CCG.Context, amount: int, end_turn_draw: bool = False):
        super().__init__(ctx, amount)
        # It's weird that this is in init, but that's how source does it. Also, the action is weird, read its comments.
        if end_turn_draw:
            self.ctx.action_manager.add_to_top(PlayerTurnAction(self.ctx))

    def __repr__(self):
        return f"Draw {self.amount}"

    def act(self):
        draw_pile_len = len(self.ctx.player.draw_pile)
        if draw_pile_len + len(self.ctx.player.discard_pile) == 0:
            ...
        elif len(self.ctx.player.hand) >= MAX_HAND_SIZE:
            ...
        else:
            # Check for overdrawing into hand
            hand_size_if_full_draw_occurs = self.amount + len(self.ctx.player.hand)
            if hand_size_if_full_draw_occurs > MAX_HAND_SIZE:
                self.amount += MAX_HAND_SIZE - hand_size_if_full_draw_occurs

            # If we're asking for more cards than there are in draw pile, split this action into "draw what's in draw
            # pile", "shuffle discard", "draw the rest requested, if needed".
            if self.amount > draw_pile_len:
                tmp = self.amount - draw_pile_len
                self.ctx.action_manager.add_to_top(DrawCardAction(self.ctx, tmp))
                self.ctx.action_manager.add_to_top(EmptyDeckShuffleAction(self.ctx))
                if draw_pile_len != 0:
                    self.ctx.action_manager.add_to_top(
                        DrawCardAction(self.ctx, draw_pile_len)
                    )
                # If we're decomposing this action, stop here
                return

            # If we get here, then draw pile can satisfy the requested draw. Do it.
            for _ in range(self.amount):
                self.ctx.player.draw()


class EmptyDeckShuffleAction(Action):
    def __repr__(self):
        return "Shuffle discard into draw"

    def act(self):
        assert len(self.ctx.player.draw_pile) == 0
        self.ctx.player.discard_pile.shuffle()

        # Figure out if draw pile needs shuffling if this assert isn't true
        assert len(self.ctx.player.draw_pile) == 0

        # Source code uses "souls" here, which I think are graphics? But they also affect the game?
        # Move all discard to draw
        for _ in range(len(self.ctx.player.discard_pile)):
            card = self.ctx.player.discard_pile.pop_top_card()
            self.ctx.player.draw_pile.add_to_top(card)


class ClearCardQueueAction(Action):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)

    def act(self):
        # Source exhausts cards in the card queue and limbo here. Not sure we need it.
        q = self.ctx.action_manager.card_queue
        # Does this happen?
        # assert len(q) == 0
        logger.debug(f"Clearing {len(q)} cards from card queue")
        q.clear()


class DiscardAtEndOfTurnAction(Action):
    def __repr__(self):
        return "Discard hand at end of turn"

    def act(self):
        # Source does this with limbo
        cards_to_keep = []
        for card in self.ctx.player.hand:
            # card = self.ctx.player.hand.pop_top_card()
            if card.self_retain or card.retain:
                cards_to_keep.append(card)
            # else:
            #     self.ctx.player.discard_pile.add_to_top(card)
        for c in cards_to_keep:
            self.ctx.player.hand.remove_card(c)

        self.ctx.action_manager.add_to_top(
            RestoreRetainedCardsAction(self.ctx, cards_to_keep)
        )
        # TODO runic pyramid, equilibrium
        # Source wraps this adding of DiscardAction with this commented for. It's harmless, but seems like a bug.
        # for _ in range(len(self.ctx.player.hand)):
        self.ctx.action_manager.add_to_top(
            DiscardAction(self.ctx, True, len(self.ctx.player.hand), True)
        )

        # Iterate over hand in random order
        for c in sorted(self.ctx.player.hand, key=lambda _: random.random()):
            c.trigger_on_end_of_player_turn()


class RestoreRetainedCardsAction(Action):
    def __init__(self, ctx: CCG.Context, cards: List[Card]):
        super().__init__(ctx)
        self.cards = cards

    def __repr__(self):
        return f"Restore {len(self.cards)} retained cards to hand"

    def act(self):
        for c in self.cards:
            logger.debug(f"Retaining {c}")
            assert c.retain or c.self_retain
            c.on_retained()
            self.ctx.player.hand.add_to_top(c)
            c.retain = False
        # TODO refreshHandLayout


class MonsterStartTurnAction(Action):
    def __init__(self, ctx: CCG.Context, monster_group: MonsterGroup):
        super().__init__(ctx)
        self.monster_group = monster_group

    def act(self):
        self.monster_group.apply_pre_turn_logic()


class ApplyPowerAction(Action):
    def __init__(
        self,
        ctx: CCG.Context,
        target: Character,
        source: Optional[Character],
        power: Power,
    ):
        super().__init__(ctx, power.amount)
        self.target = target
        self.source = source
        self.power_to_apply = power

    def __repr__(self):
        return f"Apply {self.power_to_apply} to {self.target.name}"

    def act(self):
        matching_power = next(
            (p for p in self.target.powers if isinstance(p, type(self.power_to_apply))),
            None,
        )
        if matching_power:
            matching_power.stack_power(self.amount)
        else:
            self.target.powers.append(self.power_to_apply)
            # Source has a powers sort here
            self.power_to_apply.on_initial_application()

        self.ctx.on_modify_power()


class PowerOrPowerTypeAction(Action):
    def __init__(
        self,
        ctx: CCG.Context,
        target: Character,
        power_or_power_type: Union[Power, Type[Power]],
        amount: Optional[int] = None,
    ):
        super().__init__(ctx, amount)
        self.target: Character = target
        self.power_or_power_type: Union[Power, Type[Power]] = power_or_power_type

    @final
    def act(self):
        # Find the power instance if it wasn't specified
        if isinstance(self.power_or_power_type, Power):
            power = self.power_or_power_type
        else:
            power = next(
                p for p in self.target.powers if isinstance(p, self.power_or_power_type)
            )
        self._act_impl(power)

    def _act_impl(self, power: Power):
        ...


class ReducePowerAction(PowerOrPowerTypeAction):
    def __init__(
        self,
        ctx: CCG.Context,
        target,
        power_or_power_type: Union[Power, Type[Power]],
        amount,
    ):
        super().__init__(ctx, target, power_or_power_type, amount)

    def _act_impl(self, power: Power):
        if self.amount < power.amount:
            power.reduce_power(self.amount)
            self.ctx.on_modify_power()
        else:
            self.ctx.action_manager.add_to_top(
                RemoveSpecificPowerAction(
                    self.ctx, self.target, self.power_or_power_type
                )
            )


class RemoveSpecificPowerAction(PowerOrPowerTypeAction):
    def __init__(
        self, ctx: CCG.Context, target, power_or_power_type: Union[Power, Type[Power]]
    ):
        super().__init__(ctx, target, power_or_power_type)

    def _act_impl(self, power: Power):
        if not self.target.is_dead_or_escaped():
            logger.debug(f"Removing power {power}")
            power.on_remove()
            self.target.powers.remove(power)
            self.ctx.on_modify_power()


class MakeTempCardInDiscardAction(Action):
    def __init__(
        self, ctx: CCG.Context, card: Card, amount: int, same_uuid: bool = False
    ):
        super().__init__(ctx, amount)
        # Source enforces this assert through constructor arch
        assert not same_uuid or amount == 1
        self.card: Card = card
        self.same_uuid: bool = same_uuid
        # TODO master reality

    def act(self):
        # Source has an if on this condition, not sure why. Asserting in case it matters.
        assert self.amount < 6
        logger.debug(f"Adding temp copies of {self.card}, {self.amount} to discard")
        for _ in range(self.amount):
            self.ctx.player.discard_pile.add_to_top(self.make_new_card())

    def make_new_card(self):
        return (
            self.card.make_same_instance_of()
            if self.same_uuid
            else self.card.make_stat_equivalent_copy()
        )


class MakeTempCardInHandAction(Action):
    def __init__(
        self, ctx: CCG.Context, card: Card, amount: int, same_uuid: bool = False
    ):
        super().__init__(ctx, amount)
        # Source enforces this assert through constructor arch
        assert not same_uuid or amount == 1
        self.card: Card = card
        self.same_uuid: bool = same_uuid
        # TODO master reality

    def act(self):
        if self.amount > 0:
            discard_amount = max(
                0, self.amount + len(self.ctx.player.hand) - MAX_HAND_SIZE
            )
            hand_amount = self.amount - discard_amount
            logger.debug(
                f"Adding temp copies of {self.card}, {hand_amount} to hand, {discard_amount} to discard"
            )
            for _ in range(hand_amount):
                self.add_to_hand(self.make_new_card())

            for _ in range(discard_amount):
                # TODO master reality
                self.ctx.player.discard_pile.add_to_top(self.make_new_card())

    def make_new_card(self):
        return (
            self.card.make_same_instance_of()
            if self.same_uuid
            else self.card.make_stat_equivalent_copy()
        )

    def add_to_hand(self, card: Card):
        # This is basically ShowCardAndAddToHandEffect
        # TODO master reality, corruption
        self.ctx.player.hand.add_to_top(card)
        card.trigger_when_copied()
        self.ctx.player.hand.refresh_hand_layout()
        self.ctx.player.hand.apply_powers()
        self.ctx.player.on_card_draw_or_discard()


class RollMoveAction(TargetMonsterAction):
    def __init__(self, ctx: CCG.Context, target: Monster):
        super().__init__(ctx, target)

    def act(self):
        self.target.roll_move()


# Source calls this PlayerTurnEffect and handles it through effect queue. But, it actually does stuff, which conflicts
# with the usual "effects are graphics" concept I thought held.
class PlayerTurnAction(Action):
    def act(self):
        self.ctx.player.energy_manager.recharge()

        for r in self.ctx.player.relics:
            r.on_energy_recharge()

        for p in self.ctx.player.powers:
            p.on_energy_recharge()


class GainEnergyAction(Action):
    # Probably complete: AbstractCCG.d.actionManager.updateEnergyGain
    def __init__(self, ctx: CCG.Context, energy_gain: int):
        super().__init__(ctx, energy_gain)

    def act(self):
        self.ctx.player.gain_energy(self.amount)

        for c in self.ctx.player.hand:
            c.trigger_on_gain_energy(self.amount, True)


# This is what source named it, but we don't do anything with controls. It *is* different from GainEnergyAction.
class GainEnergyAndEnableControlsAction(Action):
    # Probably complete: AbstractCCG.d.actionManager.updateEnergyGain
    def __init__(self, ctx: CCG.Context, energy_gain: int):
        super().__init__(ctx, energy_gain)

    def act(self):
        self.ctx.player.gain_energy(self.amount)

        for c in self.ctx.player.hand:
            c.trigger_on_gain_energy(self.amount, False)

        for r in self.ctx.player.relics:
            r.on_energy_recharge()

        for p in self.ctx.player.powers:
            p.on_energy_recharge()

        self.ctx.action_manager.turn_has_ended = False


class DiscardAction(Action):
    def __init__(
        self,
        ctx: CCG.Context,
        is_random: bool,
        amount: Optional[int] = None,
        end_turn: bool = False,
        from_gambling: bool = False,
    ):
        super().__init__(ctx, amount)
        self.is_random = is_random
        self.end_turn = end_turn
        self.from_gambling = from_gambling

    def act(self):
        # Not sure why, but source checks this.
        if self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
            logger.warning("Weird condition hit, maybe investigate")
            return

        hand = self.ctx.player.hand
        # If this action wants to discard more than is in hand, short circuit and discard hand.
        if self.amount is not None and self.amount >= len(hand):
            logger.debug(
                f"Requested discard amount {self.amount} is "
                f"at least as much as in hand {len(hand)}, discarding hand"
            )
            for _ in range(len(hand)):
                c = hand.get_top_card()
                hand.move_to_discard_pile(c)

                if not self.end_turn:
                    c.trigger_on_manual_discard()

                self.ctx.action_manager.increment_discard(self.end_turn)

            hand.apply_powers()
            return

        if not self.is_random:
            if self.amount is None:
                num_cards = None
                any_number = True
                can_pick_zero = True
            else:
                # Source does this in an if, but I think it's guaranteed by an earlier if.
                assert len(hand) > self.amount

                num_cards = self.amount
                any_number = False
                can_pick_zero = False

            hand.apply_powers()
            dr = DiscardRequest(
                self.ctx,
                num_cards=num_cards,
                any_number=any_number,
                can_pick_zero=can_pick_zero,
                end_turn=self.end_turn,
                from_gambling=self.from_gambling,
            )
            logger.debug(f"Setting request: {dr}")
            self.ctx.action_manager.outstanding_request = dr
        else:
            # Random discard
            logger.debug(f"Discarding {self.amount} cards randomly")
            assert self.amount is not None
            for _ in range(self.amount):
                c = hand.get_random_card(self.ctx.card_random_rng)
                hand.move_to_discard_pile(c)
                c.trigger_on_manual_discard()
                self.ctx.action_manager.increment_discard(self.end_turn)


class HandCheckAction(Action):
    def act(self):
        self.ctx.player.hand.apply_powers()


class ObtainPotionAction(Action):
    def __init__(self, ctx: CCG.Context, potion: Potion):
        super().__init__(ctx)
        self.potion: Potion = potion

    def act(self):
        # TODO sozu
        self.ctx.player.obtain_potion(self.potion)


class DamageAllEnemiesAction(Action):
    def __init__(
        self,
        ctx: CCG.Context,
        damages: List[int],
        damage_type: DamageType,
        source: Character,
    ):
        super().__init__(ctx)
        self.damages = damages
        self.damage_type = damage_type
        self.source = source

    def act(self):
        for p in self.ctx.player.powers:
            p.on_damage_all_enemies(self.damages)

        assert len(self.damages) == len(self.ctx.d.get_curr_room().monster_group)
        for i, m in enumerate(self.ctx.d.get_curr_room().monster_group):
            if not m.is_dead_or_escaped():
                m.damage(DamageInfo(self.source, self.damages[i], self.damage_type))


class GamblingChipAction(Action):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)

    def act(self):
        self.ctx.action_manager.add_to_top(DiscardAction(self.ctx, is_random=False))


class GainEnergyIfDiscardAction(Action):
    def __init__(self, ctx: CCG.Context, amount: int):
        super().__init__(ctx, amount)

    def act(self):
        if self.ctx.action_manager.total_discarded_this_turn > 0:
            self.ctx.player.gain_energy(self.amount)
            for c in self.ctx.player.hand:
                c.trigger_on_gain_energy(self.amount, True)


class LoseHPAction(TargetCharacterAction):
    def __init__(
        self, ctx: CCG.Context, target: Character, source: Character, amount: int
    ):
        super().__init__(ctx, target, amount)
        self.source = source

    def act(self):
        self.target.damage(DamageInfo(self.source, self.amount, DamageType.HP_LOSS))
        if self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
            self.ctx.action_manager.clear_post_combat_actions()


class SpawnMonsterAction(TargetMonsterAction):
    def __init__(self, ctx: CCG.Context, target: Monster, is_minion: bool):
        super().__init__(ctx, target)
        self.is_minion = is_minion

    def act(self):
        for r in self.ctx.player.relics:
            r.on_spawn_monster(self.target)

        self.target.initialize()
        self.target.apply_powers()
        # Source uses geometry to determine position here. This might be wrong.
        self.ctx.d.get_curr_room().monster_group.add_monster(self.target)

        if self.is_minion:
            self.ctx.action_manager.add_to_top(
                ApplyPowerAction(
                    self.ctx,
                    self.target,
                    self.target,
                    MinionPower(self.ctx, self.target),
                )
            )


class SuicideAction(TargetMonsterAction):
    def __init__(self, ctx: CCG.Context, target: Monster, trigger_relics: bool = True):
        super().__init__(ctx, target)
        self.trigger_relics = trigger_relics

    def act(self):
        logger.debug(f"Suiciding: {self.target.name}")
        self.target.gold = 0
        self.target.current_health = 0
        self.target.die(self.trigger_relics)


class SkewerAction(TargetMonsterAction):
    def __init__(
        self,
        ctx: CCG.Context,
        target: Monster,
        damage: int,
        free_to_play_once: bool,
        damage_type_for_turn: DamageType,
        energy_on_use: int,
    ):
        super().__init__(ctx, target, damage)
        self.free_to_play_once = free_to_play_once
        self.damage_type_for_turn = damage_type_for_turn
        self.energy_on_use = energy_on_use

    def act(self):
        effective_energy = self.ctx.player.energy_manager.player_current_energy
        if self.energy_on_use != -1:
            effective_energy = self.energy_on_use
        # TODO chemical x

        if effective_energy > 0:
            for _ in range(effective_energy):
                self.ctx.action_manager.add_to_bottom(
                    DamageAction(
                        self.ctx,
                        self.target,
                        DamageInfo(
                            self.ctx.player, self.amount, self.damage_type_for_turn
                        ),
                        self.ctx.player,
                    )
                )

            if not self.free_to_play_once:
                self.ctx.player.energy_manager.use(
                    self.ctx.player.energy_manager.player_current_energy
                )


class ModifyDamageAction(Action):
    def __init__(self, ctx: CCG.Context, card_uuid: uuid.UUID, amount: int):
        super().__init__(ctx, amount)
        self.card_uuid = card_uuid

    def act(self):
        for c in GetAllInBattleInstances.get(self.card_uuid, self.ctx.player):
            new_value = max(0, c.base_damage + self.amount)
            logger.debug(
                f"Modifying base damage of {c}: {c.base_damage} -> {new_value}"
            )
            c.base_damage = new_value


class PoisonLoseHpAction(TargetCharacterAction):
    def __init__(
        self, ctx: CCG.Context, target: Character, source: Character, amount: int
    ):
        super().__init__(ctx, target, amount)
        self.source = source

    def act(self):
        # Source checks room phase
        if self.target.current_health > 0:
            self.target.damage(DamageInfo(self.source, self.amount, DamageType.HP_LOSS))

        p = self.target.get_power(PoisonPower)
        new_amount = p.amount - 1
        logger.debug(
            f"Reducing poison amount on {self.target.name} {p.amount} -> {new_amount}"
        )
        p.amount = new_amount
        assert p.amount >= 0
        if p.amount == 0:
            logger.debug(f"Removing 0 stack power: {p}")
            self.target.powers.remove(p)

        if self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
            self.ctx.action_manager.clear_post_combat_actions()


class BaneAction(TargetMonsterAction):
    def __init__(self, ctx: CCG.Context, target: Monster, damage_info: DamageInfo):
        super().__init__(ctx, target)
        self.damage_info = damage_info

    def act(self):
        if self.target.has_power(PoisonPower) and self.target.current_health > 0:
            # Seems weird, but source
            if (
                self.damage_info.damage_type == DamageType.THORNS
                and self.damage_info.owner.is_dying
            ):
                return

            self.target.damage(self.damage_info)

            if self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
                self.ctx.action_manager.clear_post_combat_actions()


class CannotLoseAction(Action):
    def act(self):
        self.ctx.d.get_curr_room().cannot_lose = True


class CanLoseAction(Action):
    def act(self):
        self.ctx.d.get_curr_room().cannot_lose = False


class SetMoveAction(TargetMonsterAction):
    def __init__(self, ctx: CCG.Context, target: Monster, move_name: MoveName):
        super().__init__(ctx, target)
        self.move_name = move_name

    def act(self):
        logger.debug(f"Overriding {self.target.name} next move to {self.move_name}")
        self.target.next_move_name = self.move_name


class GainBlockRandomMonsterAction(Action):
    def __init__(self, ctx: CCG.Context, amount: int, source: Character):
        super().__init__(ctx, amount)
        self.source = source

    def act(self):
        def is_valid(m: Monster):
            return (
                m is not self.source
                and m.next_move.get_intent() != Intent.ESCAPE
                and not m.is_dying
            )

        valid_monsters = [
            m for m in self.ctx.d.get_curr_room().monster_group if is_valid(m)
        ]

        if len(valid_monsters) > 0:
            target = valid_monsters[
                self.ctx.ai_rng.random_from_0_to(len(valid_monsters) - 1)
            ]
        else:
            target = self.source

        target.add_block(self.amount)


class AddStolenGoldToMonsterAction(TargetCharacterAction):
    """Source does this with an anonymous action"""

    def __init__(
        self, ctx: CCG.Context, target: Character, amount: int, source: Looter
    ):
        super().__init__(ctx, target, amount)
        self.source = source

    def act(self):
        assert isinstance(self.target, Player)
        self.source.stolen_gold += min(self.source.gold_amount, self.target.gold)


class EscapeAction(TargetMonsterAction):
    def __init__(self, ctx: CCG.Context, target: Monster):
        super().__init__(ctx, target, None)

    def act(self):
        self.target.escape()


class LoseBlockAction(TargetCharacterAction):
    def __init__(self, ctx: CCG.Context, target: Character, amount: int):
        super().__init__(ctx, target, amount)

    def act(self):
        if self.target.current_block != 0:
            self.target.lose_block(self.amount)


class BurnIncreaseAction(Action):
    def act(self):
        # Source does this with ShowCardAndAddToDiscardEffect
        burn = Burn(self.ctx)
        burn.upgrade()
        self.ctx.action_manager.add_to_bottom(
            MakeTempCardInDiscardAction(self.ctx, burn, 3)
        )
        for c in flatten([self.ctx.player.discard_pile, self.ctx.player.draw_pile]):
            if isinstance(c, Burn):
                c.upgrade()


class NewActionsHere:
    ...


class DamageType(Enum):
    NORMAL = 0
    THORNS = 1
    HP_LOSS = 2


class DamageInfo:
    def __init__(
        self, source: Character, base: int, damage_type: DamageType = DamageType.NORMAL
    ):
        self.damage_type: DamageType = damage_type
        self.owner: Character = source
        self.base: int = base
        self.output: int = base

    def __repr__(self):
        return f"{self.output} {self.damage_type.name} damage from {self.owner.name}"

    def apply_powers(self, owner: Character, target: Character):
        running_output = float(self.base)

        # Source has an if here, but I think it's just for stance handling.
        for p in owner.powers:
            running_output = p.at_damage_give(running_output, self.damage_type)

        for p in target.powers:
            running_output = p.at_damage_receive(running_output, self.damage_type)

        for p in owner.powers:
            running_output = p.at_damage_final_give(running_output, self.damage_type)

        for p in target.powers:
            running_output = p.at_damage_final_receive(running_output, self.damage_type)

        self.output = max(0, int(running_output))

    def apply_enemy_powers_only(self, target: Character):
        # This method is slightly different from apply_powers... it might be bugged. I'll stick to source's impl.
        self.output = self.base
        running_output = float(self.output)

        for p in target.powers:
            running_output = p.at_damage_receive(self.output, self.damage_type)

        for p in target.powers:
            running_output = p.at_damage_final_receive(self.output, self.damage_type)

        self.output = max(0, int(running_output))


class Move(ABC):
    def __init__(self, ctx: CCG.Context, owner: Monster):
        self.ctx = ctx
        self.owner = owner

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}: {self.to_enemy_move_info()}"

    @abstractmethod
    def get_intent(self):
        ...

    def act(self, owner: Monster):
        self._act_impl(owner)

    @abstractmethod
    def _act_impl(self, owner: Monster):
        # TODO remove owner param
        ...

    def apply_powers(self):
        ...

    @final
    def to_enemy_move_info(self) -> EnemyMoveInfo:
        # Shouldn't be an issue to set -1 as next move. It's only used by legacy Monster to branch in take_turn.
        return EnemyMoveInfo(
            -1, self.get_intent(), self.get_base_damage(), self.get_multiplier()
        )

    def get_base_damage(self) -> Optional[int]:
        return None

    def get_multiplier(self) -> Optional[int]:
        return None

    def add_to_top(self, action: Action):
        self.ctx.action_manager.add_to_top(action)

    def add_to_bottom(self, action: Action):
        self.ctx.action_manager.add_to_bottom(action)


class DamageMove(Move, metaclass=ABCMeta):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        damage: AscensionDependentValueOrInt,
        multiplier: int = None,
        steal_gold_amount: int = 0,
    ):
        super().__init__(ctx, owner)
        resolved_damage = AscensionDependentValue.resolve_adv_or_int(damage)
        # TODO damage types other than NORMAL
        self.damage_info = DamageInfo(owner, resolved_damage)
        self.multiplier = multiplier
        self.steal_gold_amount = steal_gold_amount

    def _act_impl(self, owner: Monster):
        resolved_multiplier = 1 if self.multiplier is None else self.multiplier
        for _ in range(resolved_multiplier):
            self.add_to_bottom(
                DamageAction(
                    self.ctx,
                    self.ctx.player,
                    self.damage_info,
                    self.owner,
                    self.steal_gold_amount,
                )
            )

    def apply_powers(self):
        self.damage_info.apply_powers(self.owner, self.ctx.player)

    def get_base_damage(self) -> Optional[int]:
        return self.damage_info.base

    def get_multiplier(self) -> Optional[int]:
        return self.multiplier


class AttackMove(DamageMove):
    @final
    def get_intent(self):
        return Intent.ATTACK


class AttackDefendMove(DamageMove):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        damage: AscensionDependentValueOrInt,
        block: int,
    ):
        super().__init__(ctx, owner, damage)
        self.block = block

    @final
    def get_intent(self):
        return Intent.ATTACK_DEFEND

    def _act_impl(self, owner: Monster):
        super()._act_impl(owner)
        self.add_to_bottom(GainBlockAction(self.ctx, owner, self.block))


class BuffMove(Move):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        power_supplier: Callable[[Monster], Iterable[Power]],
    ):
        super().__init__(ctx, owner)
        self.power_supplier = power_supplier

    def get_intent(self):
        return Intent.BUFF

    def _act_impl(self, owner: Monster):
        for p in self.power_supplier(owner):
            self.add_to_bottom(ApplyPowerAction(self.ctx, owner, owner, p))


class DebuffMove(Move):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        power_supplier: Callable[[Player], Iterable[Power]],
    ):
        super().__init__(ctx, owner)
        self.power_supplier = power_supplier

    def get_intent(self):
        return Intent.DEBUFF

    def _act_impl(self, owner: Monster):
        for p in self.power_supplier(self.ctx.player):
            self.add_to_bottom(ApplyPowerAction(self.ctx, self.ctx.player, owner, p))


class AttackDebuffMove(DamageMove):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        power_supplier: Callable[[Player], Iterable[Power]],
        damage: AscensionDependentValueOrInt,
        multiplier: int = None,
    ):
        super().__init__(ctx, owner, damage, multiplier)
        self.power_supplier = power_supplier

    def get_intent(self):
        return Intent.ATTACK_DEBUFF

    def _act_impl(self, owner: Monster):
        super()._act_impl(owner)
        for p in self.power_supplier(self.ctx.player):
            self.add_to_bottom(ApplyPowerAction(self.ctx, self.ctx.player, owner, p))


class DefendBuffMove(BuffMove):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        power_supplier: Callable[[Monster], Iterable[Power]],
        block: AscensionDependentValueOrInt,
    ):
        super().__init__(ctx, owner, power_supplier)
        self.block = block

    def get_intent(self):
        return Intent.DEFEND_BUFF

    def _act_impl(self, owner: Monster):
        super()._act_impl(owner)
        block = AscensionDependentValue.resolve_adv_or_int(self.block)
        self.add_to_bottom(GainBlockAction(self.ctx, owner, block))


class DefendMove(Move):
    def __init__(
        self, ctx: CCG.Context, owner: Monster, block: AscensionDependentValueOrInt
    ):
        super().__init__(ctx, owner)
        self.block = block

    def get_intent(self):
        return Intent.DEFEND

    def _act_impl(self, owner: Monster):
        block = AscensionDependentValue.resolve_adv_or_int(self.block)
        self.add_to_bottom(GainBlockAction(self.ctx, owner, block))


class AttackTrashDiscardMove(DamageMove):
    """Moves that both attack and create a status card get lumped into the attack/debuff intent, which doesn't fit terribly nicely into my type structure."""

    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        damage: AscensionDependentValueOrInt,
        card: Card,
        amount: int,
    ):
        super().__init__(ctx, owner, damage)
        self.card = card
        self.amount = amount

    def get_intent(self):
        return Intent.ATTACK_DEBUFF

    def _act_impl(self, owner: Monster):
        super()._act_impl(owner)
        self.add_to_bottom(
            MakeTempCardInDiscardAction(self.ctx, self.card, self.amount)
        )


class TrashDiscardMove(Move):
    def __init__(self, ctx: CCG.Context, owner: Monster, card: Card, amount: int):
        super().__init__(ctx, owner)
        self.card = card
        self.amount = amount

    def get_intent(self):
        return Intent.DEBUFF

    def _act_impl(self, owner: Monster):
        self.add_to_bottom(
            MakeTempCardInDiscardAction(self.ctx, self.card, self.amount)
        )


class SplitDifferentMove(Move):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        spawn_funcs: List[Callable[[int], Monster]],
        is_minion=False,
    ):
        super().__init__(ctx, owner)
        self.spawn_funcs = spawn_funcs
        self.is_minion = is_minion

    def get_intent(self):
        return Intent.UNKNOWN

    def _act_impl(self, owner: Monster):
        self.add_to_bottom(CannotLoseAction(self.ctx))
        self.add_to_bottom(SuicideAction(self.ctx, self.owner, trigger_relics=False))
        hp = self.owner.current_health
        for f in self.spawn_funcs:
            m = f(hp)
            self.add_to_bottom(
                SpawnMonsterAction(self.ctx, m, is_minion=self.is_minion)
            )
        self.add_to_bottom(CanLoseAction(self.ctx))


class SplitMove(SplitDifferentMove):
    def __init__(
        self,
        ctx: CCG.Context,
        owner: Monster,
        num_to_spawn: int,
        spawn_func: Callable[[int], Monster],
        is_minion=False,
    ):
        super().__init__(ctx, owner, [spawn_func] * num_to_spawn, is_minion)


class EscapeMove(Move):
    def __init__(self, ctx: CCG.Context, owner: Monster, set_mugged: bool):
        super().__init__(ctx, owner)
        self.set_mugged = set_mugged

    def get_intent(self):
        return Intent.ESCAPE

    def _act_impl(self, owner: Monster):
        if self.set_mugged:
            self.ctx.d.get_curr_room().mugged = True
        self.add_to_bottom(EscapeAction(self.ctx, self.owner))


class NoOpMove(Move):
    def __init__(self, ctx: CCG.Context, owner: Monster, intent: Intent):
        super().__init__(ctx, owner)
        self.intent = intent

    def get_intent(self):
        return self.intent

    def _act_impl(self, owner: Monster):
        pass


class Character(ABC):
    def __init__(self, ctx: CCG.Context, name: str, max_health: int):
        self.ctx = ctx
        self.name: str = name
        self.max_health: int = max_health
        self.current_health: int = max_health
        self.current_block: int = 0
        self.powers: List[Power] = []
        # TODO Is this only for animation? If so, remove it?
        self.is_dying: bool = False
        self.half_dead: bool = False
        self.is_escaping: bool = False
        self.is_dead: bool = False
        self.is_bloodied: bool = False
        self.gold: int = 0

    def __repr__(self):
        powers_repr = (
            f'\t{"POWERS":12s}: {", ".join([p.__repr__() for p in self.powers])}'
        )
        return f"{self.name:24s}: HEALTH {self.current_health:3d} B {self.current_block:3d}{os.linesep}{powers_repr}"

    @abstractmethod
    def update(self):
        """This isn't 'update' in the same 'gets called in an event loop and has timers' sense as in source. I'm
        going to try putting death detection here, see if anything else naturally fits."""
        ...

    def add_to_top(self, action: Action):
        self.ctx.action_manager.add_to_top(action)

    def add_to_bottom(self, action: Action):
        self.ctx.action_manager.add_to_bottom(action)

    def decrease_max_health(self, amount):
        assert amount >= 0

        new_max_health = max(1, self.max_health - amount)
        logger.debug(
            f"{self.name} losing {amount} max health: {self.max_health} -> {new_max_health}"
        )

        self.current_health = min(self.current_health, self.max_health)

    @abstractmethod
    def damage(self, damage_info: DamageInfo):
        ...

    def heal(self, amount: int):
        if not self.is_dying:
            if self.is_player():
                assert isinstance(self, Player)
                for r in self.relics:
                    amount = r.on_player_heal(amount)

            for p in self.powers:
                amount = p.on_heal(amount)

            new_health = min(self.max_health, self.current_health + amount)
            logger.debug(
                f"{self.name} healed {amount}: {self.current_health} -> {new_health}"
            )
            self.current_health = new_health

            if self.is_bloodied and self.current_health > (
                float(self.max_health) / 2.0
            ):
                self.is_bloodied = False
                logger.debug(f"{self.name} no longer bloodied")

                for r in self.ctx.player.relics:
                    # Wouldn't this trigger on monster heals? Does this method only get called on players? Let's assert
                    # and see.
                    assert self.is_player()
                    r.on_not_bloodied()

    def decrement_block(self, damage_info: DamageInfo, damage_amount: int) -> int:
        # Probably complete
        if damage_info.damage_type != DamageType.HP_LOSS and self.current_block > 0:
            if damage_amount >= self.current_block:
                damage_amount -= self.current_block

                self.lose_block()
                self.broke_block()
            else:
                self.lose_block(damage_amount)
                damage_amount = 0

        return damage_amount

    def add_block(self, block_amount: int):
        running_block = float(block_amount)

        if self is self.ctx.player:
            for r in self.ctx.player.relics:
                running_block = r.on_player_gained_block(running_block)

            if running_block > 0.0:
                for p in self.powers:
                    p.on_gained_block(running_block)

        for m in self.ctx.d.get_curr_room().monster_group:
            for p in m.powers:
                running_block = p.on_player_gained_block(running_block)

        gained_block = int(running_block)
        self.current_block = min(999, self.current_block + gained_block)
        logger.debug(
            f"{self.name} gains {gained_block} block, now {self.current_block}"
        )

    def lose_block(self, amount: Optional[int] = None):
        if amount is None:
            self.current_block = 0
        else:
            self.current_block -= amount

        self.current_block = max(0, self.current_block)
        logger.debug(
            f'{self.name} loses {"all" if amount is None else amount} block, now {self.current_block}'
        )

    def broke_block(self):
        ...

    def is_dead_or_escaped(self) -> bool:
        if not self.is_dying and not self.half_dead:
            if self.is_escaping:
                return True
            return False
        return True

    def apply_start_of_turn_powers(self):
        for p in self.powers:
            p.at_start_of_turn()

    def apply_turn_powers(self):
        for p in self.powers:
            p.during_turn()

    def apply_start_of_turn_post_draw_powers(self):
        for p in self.powers:
            p.at_start_of_turn_post_draw()

    def apply_end_of_turn_triggers(self):
        # Complete
        for p in self.powers:
            if not self.is_player():
                p.at_end_of_turn_pre_end_turn_cards(False)
            p.at_end_of_turn(self.is_player())

    def get_power(self, power_type: Type[Power]) -> Power:
        matching_powers = [p for p in self.powers if isinstance(p, power_type)]
        if len(matching_powers) != 1:
            raise ValueError()
        return matching_powers[0]

    def has_power(self, power_type: Type[Power]) -> bool:
        matching_powers = [p for p in self.powers if isinstance(p, power_type)]
        if len(matching_powers) > 1:
            raise ValueError()
        return len(matching_powers) == 1

    @abstractmethod
    def is_player(self):
        ...


class EnergyManager:
    def __init__(self, energy_master: int):
        self.energy_master: int = energy_master
        self.energy_per_turn = 0
        self.player_current_energy = 0

    def __repr__(self):
        return (
            f"{self.player_current_energy}/{self.energy_per_turn}/{self.energy_master}"
        )

    def prep(self):
        self.energy_per_turn = self.energy_master
        self.player_current_energy = 0

    def recharge(self):
        """This is the per turn energy refresh mechanism"""
        # TODO ice cream, conserve
        logger.debug(
            f"Player energy recharged {self.player_current_energy} -> {self.energy_per_turn}"
        )
        self.player_current_energy = self.energy_per_turn

    # In source this belongs to EnergyPanel
    def use(self, e: int):
        self.player_current_energy -= e
        assert self.player_current_energy >= 0
        logger.debug(f"Player lost {e} energy, now {self.player_current_energy}")

    # This is our version of EnergyPanel.addEnergy.
    def add_energy(self, e: int):
        self.player_current_energy += e
        logger.debug(f"Player added {e} energy, now {self.player_current_energy}")


class Player(Character):
    def __init__(
        self,
        ctx: CCG.Context,
        max_health: int,
        energy_master: int,
        initial_potions_f: Callable[[CCG.Context], List[Potion]] = None,
    ):
        super().__init__(ctx, "Player", max_health)
        self.energy_manager = EnergyManager(energy_master)
        self.master_deck: CardGroup = CardGroup(self.ctx, CardGroupType.MASTER_DECK)
        self.draw_pile = CardGroup(self.ctx, CardGroupType.DRAW_PILE)
        self.hand = CardGroup(self.ctx, CardGroupType.HAND)
        self.discard_pile = CardGroup(self.ctx, CardGroupType.DISCARD_PILE)
        self.exhaust_pile = CardGroup(self.ctx, CardGroupType.EXHAUST_PILE)
        self.relics: List[Relic] = []
        self.potion_slots: int = 3
        initial_potions = initial_potions_f(self.ctx) if initial_potions_f else None
        assert initial_potions is None or len(initial_potions) <= self.potion_slots
        self.potions: List[Potion] = [] if initial_potions is None else initial_potions
        # TODO magic number
        self.master_hand_size: int = 5
        self.game_hand_size: int = self.master_hand_size
        self.card_in_use: Optional[Card] = None
        self.has_emerald_key = False
        self.has_sapphire_key = False
        self.has_ruby_key = False
        self.end_turn_queued = False
        self.is_ending_turn = False

        self.initialize_starter_relics()

    def __repr__(self):
        room = self.ctx.d.get_curr_room()
        if not room or room.phase == RoomPhase.COMBAT:
            piles = [self.draw_pile, self.hand, self.discard_pile, self.exhaust_pile]
        else:
            piles = [self.master_deck]

        energy_repr = f'\t{"ENERGY":12s}: {self.energy_manager}' + os.linesep
        relics_repr = (
            f'\t{"RELICS":12s}: {", ".join([r.__repr__() for r in self.relics])}'
            + os.linesep
        )
        potions_repr = (
            f'\t{"POTIONS":12s}: {", ".join([p.__repr__() for p in self.potions])}'
            + os.linesep
        )
        piles_repr = os.linesep.join([f"\t{cg}" for cg in piles])

        return f"{super().__repr__()}{os.linesep}{energy_repr}{relics_repr}{potions_repr}{piles_repr}"

    @abstractmethod
    def get_card_pool(self) -> List[Card]:
        ...

    def update_input(self):
        # Source does a lot of UI stuff here, but also a smidge of end turn logic.
        if (
            self.end_turn_queued
            and len(self.ctx.action_manager.card_queue) == 0
            and not self.ctx.action_manager.has_control
        ):
            self.end_turn_queued = False
            self.is_ending_turn = True

    def update(self):
        # Does death detection belong here?
        raise NotImplementedError()

    def obtain_emerald_key(self):
        logger.debug("Obtained emerald key")
        assert not self.has_emerald_key
        self.has_emerald_key = True

    def obtain_sapphire_key(self):
        logger.debug("Obtained sapphire key")
        assert not self.has_sapphire_key
        self.has_sapphire_key = True

    def obtain_ruby_key(self):
        logger.debug("Obtained ruby key")
        assert not self.has_ruby_key
        self.has_ruby_key = True

    def obtain_card(self, card: Card):
        # This does the work of FastCardObtainEffect, which is another effect that actually does something.
        for r in self.relics:
            r.on_obtain_card(card)

        # Source does this through souls
        self.master_deck.add_to_top(card)

        for r in self.relics:
            r.on_master_deck_change()

    @property
    def is_cursed(self):
        def is_cursed_card(c: Card):
            return c.card_type == CardType.CURSE and not isinstance(
                c, (AscendersBane, CurseOfTheBell, Necronomicurse)
            )

        return any((is_cursed_card(c) for c in self.master_deck))

    def has_relic(self, relic_type: Type[Relic]):
        return any((isinstance(r, relic_type) for r in self.relics))

    @property
    def current_health_proportion(self):
        return self.current_health / self.max_health

    @classmethod
    @abstractmethod
    def get_ascension_max_hp_loss(cls):
        ...

    def is_player(self):
        return True

    def damage(self, damage_info: DamageInfo):  # noqa: C901
        damage_amount = damage_info.output
        damage_amount = max(0, damage_amount)

        # TODO intangible

        damage_amount = self.decrement_block(damage_info, damage_amount)

        if damage_info.owner == self:
            for r in self.relics:
                damage_amount = r.on_attack_to_change_damage(damage_info, damage_amount)

        if damage_info.owner:
            for p in damage_info.owner.powers:
                damage_amount = p.on_attack_to_change_damage(damage_info, damage_amount)

        for r in self.relics:
            damage_amount = r.on_attacked_to_change_damage(damage_info, damage_amount)

        for p in self.powers:
            damage_amount = p.on_attacked_to_change_damage(damage_info, damage_amount)

        if damage_info.owner == self:
            for r in self.relics:
                r.on_attack(damage_info, damage_amount, self)

        if damage_info.owner:
            for p in damage_info.owner.powers:
                p.on_attack(damage_info, damage_amount, self)

            for p in self.powers:
                damage_amount = p.on_attacked(damage_info, damage_amount)

            for r in self.relics:
                damage_amount = r.on_attacked(damage_info, damage_amount)

        for r in self.relics:
            damage_amount = r.on_lose_hp_last(damage_amount)

        # TODO lastDamageTaken

        if damage_amount > 0:
            for p in self.powers:
                damage_amount = p.on_lose_hp(damage_amount)

            for r in self.relics:
                r.on_lose_hp(damage_amount)

            for p in self.powers:
                p.was_hp_lost(damage_info, damage_amount)

            for r in self.relics:
                r.was_hp_lost(damage_amount)

            if damage_info.owner:
                for p in damage_info.owner.powers:
                    p.on_inflict_damage(damage_info, damage_amount, self)

            self.current_health -= damage_amount
            logger.debug(
                f"Player health reduced by {damage_amount} -> {self.current_health}"
            )

            # Source also checks if room phase is combat here.
            if damage_amount > 0:
                self._update_cards_on_damage()

            self.current_health = max(0, self.current_health)

            if (
                float(self.current_health) < float(self.max_health) / 2.0
                and not self.is_bloodied
            ):
                self.is_bloodied = True

                for r in self.relics:
                    r.on_bloodied()

            if self.current_health < 1:
                logger.debug("Player health < 1")
                # TODO all the life saving relics, potions
                self.is_dead = True
                # These calls probably aren't needed, but they're in source.
                self.current_health = 0
                if self.current_block > 0:
                    self.lose_block()

    def initialize_starter_relics(self):
        logger.debug("Granting starter relics")
        SnakeRing(self.ctx).instant_obtain(self, False)
        # Don't set this here. We have creation order issues that source doesn't. See dungeon relic init.
        # self.ctx.d.relics_to_remove_on_start.append(SnakeRing)

    def pre_battle_prep(self):
        # TODO Incomplete, lots of reset happens here.
        # TODO slavers collar
        self.is_bloodied = self.current_health <= (self.max_health // 2)
        self.end_turn_queued = False
        self.game_hand_size = self.master_hand_size
        self.card_in_use = None
        self.draw_pile.initialize_deck(self.master_deck)
        self.hand.clear()
        self.discard_pile.clear()
        self.exhaust_pile.clear()
        self.energy_manager.prep()
        self.powers.clear()
        self.is_ending_turn = False
        self.ctx.d.get_curr_room().monster_group.use_pre_battle_action()
        if self.ctx.d.curr_map_node.has_emerald_key:
            room = self.ctx.d.get_curr_room()
            assert isinstance(room, MonsterRoomElite)
            room.apply_emerald_elite_buff()

        self.apply_pre_combat_logic()

    # Complete
    def apply_start_of_combat_pre_draw_logic(self):
        for r in self.relics:
            r.at_battle_start_pre_draw()

    def apply_start_of_combat_logic(self):
        for r in self.relics:
            r.at_battle_start()
        # blights

    def use_card(self, card_queue_item: CardQueueItem):
        # TODO more to implement here

        card = card_queue_item.card

        card.calculate_card_damage(card_queue_item.monster)

        if (
            card.cost == -1
            and self.ctx.player.energy_manager.player_current_energy
            < card_queue_item.energy_on_use
            and not card.ignore_energy_on_use
        ):
            card.energy_on_use = self.ctx.player.energy_manager.player_current_energy

        if card.cost == -1 and card.is_in_autoplay:
            card.free_to_play_once = True

        card.use(card_queue_item.monster)
        self.ctx.action_manager.add_to_bottom(
            UseCardAction(self.ctx, card, card_queue_item.monster)
        )

        if not card.dont_trigger_on_use_card:
            self.hand.trigger_on_other_card_played(card)

        self.hand.remove_card(card)
        self.card_in_use = card
        if (
            card.cost_for_turn > 0
            and not card.free_to_play()
            and not card.is_in_autoplay
        ):
            # TODO corruption
            self.energy_manager.use(card.cost_for_turn)

    def draw(self):
        drawn_card = self.draw_pile.pop_top_card()
        self.hand.add_to_top(drawn_card)
        self.on_card_draw_or_discard()

    def get_total_card_count(self) -> int:
        """Returns the sum of lengths of hand, discard, draw, exhaust piles."""
        return sum(
            [
                len(self.hand),
                len(self.discard_pile),
                len(self.draw_pile),
                len(self.exhaust_pile),
            ]
        )

    def on_card_draw_or_discard(self):
        for power in self.powers:
            power.on_draw_or_discard()
        # TODO relic proc
        self.hand.apply_powers()

    def gain_energy(self, energy_gain: int):
        self.energy_manager.add_energy(energy_gain)

    def apply_start_of_turn_relics(self):
        # Probably complete: if
        # TODO stance
        for r in self.relics:
            r.at_turn_start()
        # TODO blights

    def apply_start_of_turn_post_draw_relics(self):
        # Probably complete: if
        for r in self.relics:
            r.at_turn_start_post_draw()

    def apply_start_of_turn_cards(self):
        # Complete
        for c in flatten([self.draw_pile, self.hand, self.discard_pile]):
            c.at_turn_start()

    def _update_cards_on_damage(self):
        # Source checks room phase is combat here.
        for c in flatten([self.hand, self.discard_pile, self.draw_pile]):
            c.took_damage()

    def obtain_potion(self, potion: Potion):
        # TODO keep potions in slots stable?
        if len(self.potions) < self.potion_slots:
            self.potions.append(potion)
            logger.debug(f"Obtained potion: {potion}")
        else:
            logger.warning("Tried to obtain potion with no empty slot")
            assert False

    def update_cards_on_discard(self):
        for c in flatten([self.hand, self.discard_pile, self.draw_pile]):
            c.did_discard()

    def apply_start_of_turn_pre_draw_cards(self):
        for c in self.hand:
            assert c is not None
            c.at_turn_start_pre_draw()

    @abstractmethod
    def get_starting_deck(self) -> List[Card]:
        ...

    def initialize_starter_deck(self):
        cards = self.get_starting_deck()
        # Ensure all cards have unique ID
        assert len(set([c.uuid for c in cards])) == len(cards)
        # Ensure all cards are unique objects
        for i in range(len(cards)):
            for j in range(len(cards)):
                if i != j:
                    assert cards[i] is not cards[j]

        for c in cards:
            # Source differs
            self.master_deck.add_to_top(c)

    def on_victory(self):
        if not self.is_dying:
            for r in self.ctx.player.relics:
                r.on_victory()

            for p in self.ctx.player.powers:
                p.on_victory()

    def gain_gold(self, amount: int):
        # TODO ectoplasm
        assert amount >= 0
        new_gold = self.gold + amount
        logger.debug(f"{self.name} gained gold: {self.gold} + {amount} = {new_gold}")
        self.gold = new_gold

        for r in self.relics:
            r.on_gain_gold()

    def apply_pre_combat_logic(self):
        for r in self.relics:
            r.at_pre_battle()


class Monster(Character):
    enqueue_roll_move_after_acting = True

    def __init__(
        self,
        ctx: CCG.Context,
        max_health_min: ADVOrInt,
        max_health_max: ADVOrInt,
        moves: Dict[MoveName, Move],
        move_overrides: List[Optional[MoveName]] = None,
        move_rng_overrides: Iterable[Optional[int]] = None,
    ):
        resolved_max_health_min = ADV.resolve_adv_or_int(max_health_min)
        resolved_max_health_max = ADV.resolve_adv_or_int(max_health_max)

        assert resolved_max_health_min <= resolved_max_health_max
        max_health = random.randrange(
            resolved_max_health_min, resolved_max_health_max + 1
        )

        super().__init__(ctx, self.__class__.__name__, max_health)
        self.intent_damage: Optional[int] = None
        self.move_history: List[MoveName] = []
        self.move_overrides = move_overrides
        self.move_overrides_index = 0
        self.move_rng_overrides = (
            deque(move_rng_overrides) if move_rng_overrides else None
        )
        # Forbid mixing override types
        if bool(self.move_overrides) and bool(self.move_rng_overrides):
            raise Exception()
        self.escaped = False

        self.names_to_moves = moves
        self._is_first_move = True
        self.next_move_name = MoveName.INVALID
        self._turns_taken = 0

    def __repr__(self):
        dead_repr = "DEAD" if self.is_dead else "D̶E̶A̶D̶"
        escaped_repr = "ESCAPED" if self.escaped else "E̶S̶C̶A̶P̶E̶D̶"
        liveness_repr = f'\t{"LIVENESS":12s}: {dead_repr} {escaped_repr}' + os.linesep
        intent_repr = f'\t{"INTENT":12s}: {self.next_move_name.name}: {self.next_move}'

        return f"{super().__repr__()}{os.linesep}{liveness_repr}{intent_repr}"

    @property
    def next_move(self) -> Optional[Move]:
        if self.next_move_name == MoveName.INVALID:
            return None
        return self.names_to_moves[self.next_move_name]

    @property
    def move_info(self) -> Optional[EnemyMoveInfo]:
        if self.next_move:
            return self.next_move.to_enemy_move_info()
        return None

    def update(self):
        # updateDeathAnimation
        room = self.ctx.d.get_curr_room()
        if self.is_dying:
            self.is_dead = True
            logger.debug(f"{self.name} is_dying -> is_dead")
            if (
                self.ctx.d.get_monsters().are_monsters_dead()
                and not room.is_battle_over
                and not room.cannot_lose
            ):
                logger.debug("All monsters dead, ending battle")
                room.end_battle()

            self.powers.clear()

        # updateEscapeAnimation
        if self.is_escaping:
            self.escaped = True
            logger.debug(f"{self.name} is_escaping -> escaped")
            if (
                room.monster_group.are_monsters_dead()
                and not room.is_battle_over
                and not room.cannot_lose
            ):
                logger.debug("All monsters dead, ending battle")
                room.end_battle()

    def initialize(self):
        # Source calls this method init
        self.roll_move()

    def is_player(self):
        return False

    @final
    def take_turn(self):
        next_move = self.names_to_moves[self.next_move_name]
        next_move.act(self)

        # This isn't how source handles move history, but I think this is more robust.
        self.move_history.append(self.next_move_name)

        if self.enqueue_roll_move_after_acting:
            self.add_to_bottom(RollMoveAction(self.ctx, self))
        else:
            logger.debug(f"Not enqueueing roll move for {self.name}")

        self._turns_taken += 1

    def create_intent(self):
        # I'm not sure we need to implement this.
        ...

    def damage(self, damage_info: DamageInfo):
        # TODO intangible

        damage_amount = damage_info.output
        if self.is_dying or self.is_escaping:
            return

        damage_amount = max(0, damage_amount)
        damage_amount = self.decrement_block(damage_info, damage_amount)

        if damage_info.owner == self.ctx.player:
            for r in self.ctx.player.relics:
                damage_amount = r.on_attack_to_change_damage(damage_info, damage_amount)

        if damage_info.owner:
            for p in damage_info.owner.powers:
                damage_amount = p.on_attack_to_change_damage(damage_info, damage_amount)

        for p in self.powers:
            damage_amount = p.on_attacked_to_change_damage(damage_info, damage_amount)

        if damage_info.owner == self.ctx.player:
            for r in self.ctx.player.relics:
                r.on_attack(damage_info, damage_amount, self)

        for p in self.powers:
            p.was_hp_lost(damage_info, damage_amount)

        if damage_info.owner:
            for p in damage_info.owner.powers:
                p.on_attack(damage_info, damage_amount, self)

        for p in self.powers:
            damage_amount = p.on_attacked(damage_info, damage_amount)

        # TODO lastDamageTaken

        if damage_amount > 0:
            self.current_health = max(0, self.current_health - damage_amount)

        if self.current_health <= 0:
            self.die()
            if self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
                self.ctx.action_manager.clean_card_queue()

            if self.current_block > 0:
                self.lose_block()

    def die(self, trigger_relics: bool = None):
        # Probably complete
        trigger_relics = trigger_relics if trigger_relics is not None else True
        logger.debug(f"Die: {self.name}")

        # It would seem weird to call this without health being 0, so assert and see if it ever happens.
        assert self.current_health <= 0

        if not self.is_dying:
            self.is_dying = True
            if self.current_health <= 0 and trigger_relics:
                for p in self.powers:
                    p.on_death()

            if trigger_relics:
                for r in self.ctx.player.relics:
                    r.on_monster_death(self)

            # Source does something with limbo cards here

            self.current_health = max(0, self.current_health)

    def add_roll_move_action_to_bottom(self):
        self.add_to_bottom(RollMoveAction(self.ctx, self))

    def broke_block(self):
        for r in self.ctx.player.relics:
            r.on_block_broken(self)

    @final
    def get_move(self, num: int):
        if self.move_rng_overrides and len(self.move_rng_overrides) > 0:
            rng_override = self.move_rng_overrides.popleft()
            if rng_override is None:
                logger.debug("RNG override present, but not triggered this turn")
            else:
                num = rng_override
                logger.warning(f"Overriding {self.name} next move RNG to {num}")

        if (
            self.move_overrides is not None
            and self.move_overrides_index < len(self.move_overrides)
            and self.move_overrides[self.move_overrides_index] is not None
        ):
            logger.info("Move override active!")
            next_move_name = self.move_overrides[self.move_overrides_index]
        else:
            next_move_name = self._get_move_impl(
                num, self._is_first_move, self.ctx.ai_rng, self._turns_taken
            )
        self.move_overrides_index += 1

        self.next_move_name = next_move_name
        logger.debug(f"{self.name} chose next move {self.next_move_name}")
        assert self.next_move_name in self.names_to_moves.keys()
        # This might get in a wrong state if move gets rolled multiple times per turn.
        self._is_first_move = False
        # self.move_history.append(self.next_move_name)

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        assert len(self.names_to_moves) > 0
        if len(self.names_to_moves) == 1:
            # If there's only one move, don't force subclasses to implement this method
            for name in self.names_to_moves.keys():
                return name
        else:
            raise NotImplementedError()

    def roll_move(self):
        num = self.ctx.ai_rng.random_from_0_to(99)
        logger.debug(f"{self.name} rolled {num} for move")
        self.get_move(num)

    def apply_powers(self):
        for move in self.names_to_moves.values():
            move.apply_powers()

        # These two predicates might mean the same thing; source might use -1 as sentinel to mean "None".
        if self.move_info.base_damage is not None and self.move_info.base_damage > -1:
            self._calculate_damage(self.move_info.base_damage)

    def _calculate_damage(self, damage: int):
        running_damage = float(damage)

        for power in self.powers:
            running_damage = power.at_damage_give(running_damage, DamageType.NORMAL)

        # TODO incomplete

        self.intent_damage = max(0, int(running_damage))

    def last_move(self, move_name: MoveName):
        assert move_name in self.names_to_moves.keys()
        return len(self.move_history) >= 1 and move_name == self.move_history[-1]

    def last_two_moves(self, move_name: MoveName):
        assert move_name in self.names_to_moves.keys()
        return (
            len(self.move_history) >= 2
            and move_name == self.move_history[-1]
            and move_name == self.move_history[-2]
        )

    def use_pre_battle_action(self):
        ...

    def on_boss_victory_logic(self):
        ...

    def use_universal_pre_battle_action(self):
        pass

    def escape(self):
        self.is_escaping = True


class AcidSlimeS(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        tackle_damage = ADV.of(3).with_asc(2, 4)
        moves = {
            MoveName.LICK: DebuffMove(
                ctx, self, lambda pl: [WeakPower(ctx, pl, 1, True)]
            ),
            MoveName.TACKLE: AttackMove(ctx, self, tackle_damage),
        }
        super().__init__(
            ctx,
            ADV.of(8).with_asc(7, 9),
            ADV.of(12).with_asc(7, 13),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        # Source is weird here. I'm basing this on the wiki description.
        if is_first_move:
            if AscensionManager.get_ascension(self) >= 17:
                mn = MoveName.LICK
            else:
                if ai_rng.random_boolean():
                    mn = MoveName.LICK
                else:
                    mn = MoveName.TACKLE
        elif self.last_move(MoveName.LICK):
            mn = MoveName.TACKLE
        else:
            mn = MoveName.LICK

        return mn


class AcidSlimeM(Monster):
    def __init__(
        self, ctx: CCG.Context, override_max_health: int = None, *args, **kwargs
    ):
        tackle_damage = ADV.of(10).with_asc(2, 12)
        corrosive_spit_damage = ADV.of(7).with_asc(2, 8)
        moves = {
            MoveName.LICK: DebuffMove(
                ctx, self, lambda pl: [WeakPower(ctx, pl, 1, True)]
            ),
            MoveName.TACKLE: AttackMove(ctx, self, tackle_damage),
            MoveName.CORROSIVE_SPIT: AttackTrashDiscardMove(
                ctx, self, corrosive_spit_damage, Slimed(ctx), 1
            ),
        }
        max_health_min = (
            ADV.of(65).with_asc(7, 68)
            if override_max_health is None
            else override_max_health
        )
        max_health_max = (
            ADV.of(69).with_asc(7, 72)
            if override_max_health is None
            else override_max_health
        )
        super().__init__(ctx, max_health_min, max_health_max, moves, *args, **kwargs)

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if AscensionManager.get_ascension(self) >= 17:
            if num < 40:
                if self.last_two_moves(MoveName.CORROSIVE_SPIT):
                    if ai_rng.random_boolean():
                        mn = MoveName.TACKLE
                    else:
                        mn = MoveName.LICK
                else:
                    mn = MoveName.CORROSIVE_SPIT
            elif num < 80:
                if self.last_two_moves(MoveName.TACKLE):
                    if ai_rng.random_boolean():
                        mn = MoveName.CORROSIVE_SPIT
                    else:
                        mn = MoveName.LICK
                else:
                    mn = MoveName.TACKLE
            elif self.last_move(MoveName.LICK):
                if ai_rng.random_boolean(0.4):
                    mn = MoveName.CORROSIVE_SPIT
                else:
                    mn = MoveName.TACKLE
            else:
                mn = MoveName.LICK
        elif num < 30:
            if self.last_two_moves(MoveName.CORROSIVE_SPIT):
                if ai_rng.random_boolean():
                    mn = MoveName.TACKLE
                else:
                    mn = MoveName.LICK
            else:
                mn = MoveName.CORROSIVE_SPIT
        elif num < 70:
            if self.last_move(MoveName.TACKLE):
                if ai_rng.random_boolean(0.4):
                    mn = MoveName.CORROSIVE_SPIT
                else:
                    mn = MoveName.LICK
            else:
                mn = MoveName.TACKLE
        elif self.last_two_moves(MoveName.LICK):
            if ai_rng.random_boolean(0.4):
                mn = MoveName.CORROSIVE_SPIT
            else:
                mn = MoveName.TACKLE
        else:
            mn = MoveName.LICK

        return mn


class AcidSlimeL(Monster):
    def __init__(
        self, ctx: CCG.Context, override_max_health: int = None, *args, **kwargs
    ):
        tackle_damage = ADV.of(16).with_asc(2, 18)
        corrosive_spit_damage = ADV.of(11).with_asc(2, 12)
        moves = {
            MoveName.LICK: DebuffMove(
                ctx, self, lambda pl: [WeakPower(ctx, pl, 2, True)]
            ),
            MoveName.TACKLE: AttackMove(ctx, self, tackle_damage),
            MoveName.CORROSIVE_SPIT: AttackTrashDiscardMove(
                ctx,
                self,
                corrosive_spit_damage,
                Slimed(
                    ctx,
                ),
                2,
            ),
            MoveName.SPLIT: SplitMove(
                ctx, self, 2, lambda health: AcidSlimeM(ctx, health)
            ),
        }
        max_health_min = (
            ADV.of(65).with_asc(7, 68)
            if override_max_health is None
            else override_max_health
        )
        max_health_max = (
            ADV.of(69).with_asc(7, 72)
            if override_max_health is None
            else override_max_health
        )
        super().__init__(ctx, max_health_min, max_health_max, moves, *args, **kwargs)
        self.powers.append(SplitPower(self.ctx, self))
        self.split_triggered = False

    def damage(self, damage_info: DamageInfo):
        super().damage(damage_info)
        if (
            not self.is_dying
            and self.current_health <= (self.max_health // 2)
            and self.next_move_name != MoveName.SPLIT
            and not self.split_triggered
        ):
            self.split_triggered = True
            logger.debug("Split triggered, setting move to split")
            # Seems redundant, but source both sets move directly here and enqueues a set action.
            self.next_move_name = MoveName.SPLIT
            self.create_intent()
            self.add_to_bottom(SetMoveAction(self.ctx, self, MoveName.SPLIT))

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)
        if not any(
            (isinstance(a, SpawnMonsterAction) for a in self.ctx.action_manager.actions)
        ):
            if (
                self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead()
                and isinstance(self.ctx.d.get_curr_room(), MonsterRoomBoss)
            ):
                self.on_boss_victory_logic()

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if AscensionManager.get_ascension(self) >= 17:
            if num < 40:
                if self.last_two_moves(MoveName.CORROSIVE_SPIT):
                    if ai_rng.random_boolean(0.6):
                        mn = MoveName.TACKLE
                    else:
                        mn = MoveName.LICK
                else:
                    mn = MoveName.CORROSIVE_SPIT
            elif num < 70:
                if self.last_two_moves(MoveName.TACKLE):
                    if ai_rng.random_boolean(0.6):
                        mn = MoveName.CORROSIVE_SPIT
                    else:
                        mn = MoveName.LICK
                else:
                    mn = MoveName.TACKLE
            elif self.last_move(MoveName.LICK):
                if ai_rng.random_boolean(0.4):
                    mn = MoveName.CORROSIVE_SPIT
                else:
                    mn = MoveName.TACKLE
            else:
                mn = MoveName.LICK
        elif num < 30:
            if self.last_two_moves(MoveName.CORROSIVE_SPIT):
                if ai_rng.random_boolean():
                    mn = MoveName.TACKLE
                else:
                    mn = MoveName.LICK
            else:
                mn = MoveName.CORROSIVE_SPIT
        elif num < 70:
            if self.last_move(MoveName.TACKLE):
                if ai_rng.random_boolean(0.4):
                    mn = MoveName.CORROSIVE_SPIT
                else:
                    mn = MoveName.LICK
            else:
                mn = MoveName.TACKLE
        elif self.last_two_moves(MoveName.LICK):
            if ai_rng.random_boolean(0.4):
                mn = MoveName.CORROSIVE_SPIT
            else:
                mn = MoveName.TACKLE
        else:
            mn = MoveName.LICK

        return mn


class SpikeSlimeS(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        moves = {
            MoveName.TACKLE: AttackMove(ctx, self, ADV.of(5).with_asc(2, 6)),
        }
        super().__init__(
            ctx,
            ADV.of(10).with_asc(7, 11),
            ADV.of(14).with_asc(7, 15),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        return MoveName.TACKLE


class SpikeSlimeM(Monster):
    def __init__(
        self, ctx: CCG.Context, override_max_health: int = None, *args, **kwargs
    ):
        flame_tackle_damage = ADV.of(8).with_asc(2, 10)
        moves = {
            MoveName.LICK: DebuffMove(
                ctx, self, lambda pl: [FrailPower(ctx, pl, 1, True)]
            ),
            MoveName.FLAME_TACKLE: AttackTrashDiscardMove(
                ctx,
                self,
                flame_tackle_damage,
                Slimed(
                    ctx,
                ),
                1,
            ),
        }
        max_health_min = (
            ADV.of(28).with_asc(7, 29)
            if override_max_health is None
            else override_max_health
        )
        max_health_max = (
            ADV.of(32).with_asc(7, 34)
            if override_max_health is None
            else override_max_health
        )
        super().__init__(ctx, max_health_min, max_health_max, moves, *args, **kwargs)

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if AscensionManager.get_ascension(self) >= 17:
            if num < 30:
                if self.last_two_moves(MoveName.FLAME_TACKLE):
                    mn = MoveName.LICK
                else:
                    mn = MoveName.FLAME_TACKLE
            elif self.last_move(MoveName.LICK):
                mn = MoveName.FLAME_TACKLE
            else:
                mn = MoveName.LICK
        elif num < 30:
            if self.last_two_moves(MoveName.FLAME_TACKLE):
                mn = MoveName.LICK
            else:
                mn = MoveName.FLAME_TACKLE
        elif self.last_two_moves(MoveName.LICK):
            mn = MoveName.FLAME_TACKLE
        else:
            mn = MoveName.LICK

        return mn

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)
        if (
            self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead()
            and isinstance(self.ctx.d.get_curr_room(), MonsterRoomBoss)
        ):
            self.on_boss_victory_logic()


class SpikeSlimeL(Monster):
    def __init__(
        self, ctx: CCG.Context, override_max_health: int = None, *args, **kwargs
    ):
        tackle_damage = ADV.of(16).with_asc(2, 18)
        frail_amount = ADV.of(2).with_asc(17, 3).resolve()
        moves = {
            MoveName.LICK: DebuffMove(
                ctx, self, lambda pl: [FrailPower(ctx, pl, frail_amount, True)]
            ),
            MoveName.FLAME_TACKLE: AttackTrashDiscardMove(
                ctx,
                self,
                tackle_damage,
                Slimed(
                    ctx,
                ),
                2,
            ),
            MoveName.SPLIT: SplitMove(
                ctx, self, 2, lambda health: SpikeSlimeM(ctx, health)
            ),
        }
        max_health_min = (
            ADV.of(64).with_asc(7, 67)
            if override_max_health is None
            else override_max_health
        )
        max_health_max = (
            ADV.of(70).with_asc(7, 73)
            if override_max_health is None
            else override_max_health
        )
        super().__init__(ctx, max_health_min, max_health_max, moves, *args, **kwargs)
        self.powers.append(SplitPower(self.ctx, self))
        self.split_triggered = False

    def damage(self, damage_info: DamageInfo):
        super().damage(damage_info)
        if (
            not self.is_dying
            and self.current_health <= (self.max_health // 2)
            and self.next_move_name != MoveName.SPLIT
            and not self.split_triggered
        ):
            logger.debug("Split triggered, setting move to split")
            self.split_triggered = True
            # Seems redundant, but source both sets move directly here and enqueues a set action.
            self.next_move_name = MoveName.SPLIT
            self.create_intent()
            self.add_to_bottom(SetMoveAction(self.ctx, self, MoveName.SPLIT))

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)
        if not any(
            (isinstance(a, SpawnMonsterAction) for a in self.ctx.action_manager.actions)
        ):
            if (
                self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead()
                and isinstance(self.ctx.d.get_curr_room(), MonsterRoomBoss)
            ):
                self.on_boss_victory_logic()

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if AscensionManager.get_ascension(self) >= 17:
            if num < 30:
                if self.last_two_moves(MoveName.FLAME_TACKLE):
                    mn = MoveName.LICK
                else:
                    mn = MoveName.FLAME_TACKLE
            elif self.last_move(MoveName.LICK):
                mn = MoveName.FLAME_TACKLE
            else:
                mn = MoveName.LICK
        elif num < 30:
            if self.last_two_moves(MoveName.FLAME_TACKLE):
                mn = MoveName.LICK
            else:
                mn = MoveName.FLAME_TACKLE
        elif self.last_two_moves(MoveName.LICK):
            mn = MoveName.FLAME_TACKLE
        else:
            mn = MoveName.LICK

        return mn


class MoveName(Enum):
    INVALID = 0
    INCANTATION = 1
    DARK_STRIKE = 2
    THRASH = 3
    CHOMP = 4
    BELLOW = 5
    LICK = 6
    TACKLE = 7
    CORROSIVE_SPIT = 8
    FLAME_TACKLE = 9
    SMOKE_BOMB = 10
    SNAKE_STRIKE = 11
    SUMMON = 12
    BIG_BITE = 13
    STAB = 14
    EXPLODE = 15
    BITE = 16
    GROW = 17
    SPLIT = 18
    SMASH = 19
    PROTECT = 20
    SHIELD_BASH = 21
    PUNCTURE = 22
    SCRATCH = 23
    CHARGING = 24
    ULTIMATE_BLAST = 25
    ATTACK = 26
    SIPHON_SOUL = 27
    STUNNED = 28
    SLEEP = 29
    MUG = 30
    LUNGE = 31
    ESCAPE = 32
    SPIT_WEB = 33
    BEAM = 34
    BOLT = 35
    RAKE = 36
    SCRAPE = 37
    ENTANGLE = 38
    GOOP_SPRAY = 39
    PREPARING = 40
    SLAM = 41
    CHARGING_UP = 42
    FIERCE_BASH = 43
    VENT_STEAM = 44
    WHIRLWIND = 45
    DEFENSIVE_MODE = 46
    ROLL_ATTACK = 47
    TWIN_SLAM = 48
    RUSH = 49
    SKULL_BASH = 50
    ACTIVATE = 51
    SEAR = 52
    INFLAME = 53
    INFERNO = 54
    DIVIDER = 55


class Cultist(Monster):
    def __init__(
        self,
        ctx: CCG.Context,
        move_overrides: Iterable[Optional[int]] = None,
        move_rng_overrides: Iterable[Optional[int]] = None,
    ):
        moves = {
            MoveName.INCANTATION: BuffMove(
                ctx,
                self,
                lambda m: [
                    RitualPower(
                        ctx,
                        m,
                        AscensionDependentValue.of(3)
                        .with_asc(2, 4)
                        .with_asc(17, 5)
                        .resolve(),
                        False,
                    )
                ],
            ),
            MoveName.DARK_STRIKE: AttackMove(ctx, self, 6),
        }
        super().__init__(
            ctx,
            ADV.of(48).with_asc(7, 50),
            ADV.of(54).with_asc(7, 56),
            moves,
            move_overrides,
            move_rng_overrides,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if is_first_move:
            return MoveName.INCANTATION
        else:
            return MoveName.DARK_STRIKE


class JawWorm(Monster):
    def __init__(self, ctx: CCG.Context, hard_mode=False):
        self.bellow_strength = (
            AscensionDependentValue.of(3).with_asc(2, 4).with_asc(17, 5).resolve()
        )
        self.bellow_block = AscensionDependentValue.of(6).with_asc(17, 9).resolve()
        moves = {
            MoveName.CHOMP: AttackMove(
                ctx, self, AscensionDependentValue.of(11).with_asc(2, 12)
            ),
            MoveName.THRASH: AttackDefendMove(ctx, self, 7, 5),
            MoveName.BELLOW: DefendBuffMove(
                ctx,
                self,
                lambda m: [StrengthPower(ctx, m, self.bellow_strength)],
                self.bellow_block,
            ),
        }
        super().__init__(
            ctx, ADV.of(40).with_asc(7, 42), ADV.of(44).with_asc(7, 46), moves
        )
        self.hard_mode = hard_mode

    def use_pre_battle_action(self):
        if self.hard_mode:
            self.add_to_bottom(
                ApplyPowerAction(
                    self.ctx,
                    self,
                    self,
                    StrengthPower(self.ctx, self, self.bellow_strength),
                )
            )
            self.add_to_bottom(GainBlockAction(self.ctx, self, self.bellow_block))

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.CHOMP
        else:
            if num < 25:
                if self.last_move(MoveName.CHOMP):
                    if ai_rng.random_boolean(0.5625):
                        mn = MoveName.BELLOW
                    else:
                        mn = MoveName.THRASH
                else:
                    mn = MoveName.CHOMP
            elif num < 55:
                if self.last_two_moves(MoveName.THRASH):
                    if ai_rng.random_boolean(0.357):
                        mn = MoveName.CHOMP
                    else:
                        mn = MoveName.BELLOW
                else:
                    mn = MoveName.THRASH
            elif self.last_move(MoveName.BELLOW):
                if ai_rng.random_boolean(0.416):
                    mn = MoveName.CHOMP
                else:
                    mn = MoveName.THRASH
            else:
                mn = MoveName.BELLOW

        return mn


class AlwaysAttackMonster(Monster):
    def __init__(self, ctx: CCG.Context, max_health, damage_amount, *args, **kwargs):
        moves = {
            MoveName.TACKLE: AttackMove(ctx, self, damage_amount),
        }
        super().__init__(ctx, max_health, max_health, moves, *args, **kwargs)


class SimpleMonster(Monster):
    def __init__(self, ctx: CCG.Context, max_health: int, attack_amount, block_amount):
        moves = {
            MoveName.TACKLE: AttackMove(ctx, self, attack_amount),
            MoveName.SMOKE_BOMB: DefendMove(ctx, self, block_amount),
        }
        super().__init__(ctx, max_health, max_health, moves)

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.TACKLE
        elif self.last_move(MoveName.TACKLE):
            mn = MoveName.SMOKE_BOMB
        else:
            mn = MoveName.TACKLE

        return mn


class AlwaysWeakenMonster(Monster):
    def __init__(self, ctx: CCG.Context, max_health):
        moves = {
            MoveName.LICK: DebuffMove(
                ctx, self, lambda pl: [WeakPower(ctx, pl, 2, True)]
            )
        }
        super().__init__(ctx, max_health, max_health, moves)


class Reptomancer(Monster):
    max_num_daggers = 4

    class SpawnDaggersMove(Move):
        # This class is gross, but eh.
        def __init__(
            self, ctx: CCG.Context, owner: Reptomancer, daggers_per_spawn: ADVOrInt
        ):
            super().__init__(ctx, owner)
            self.owning_reptomancer = owner
            # self.daggers: List[Optional[Monster]] = [None] * Reptomancer.max_num_daggers
            self.daggers_per_spawn = ADV.resolve_adv_or_int(daggers_per_spawn)

        def get_intent(self):
            return Intent.UNKNOWN

        def _act_impl(self, owner: Monster):
            assert len(self.owning_reptomancer.daggers) == Reptomancer.max_num_daggers
            daggers_spawned = 0
            for i in range(Reptomancer.max_num_daggers):
                if daggers_spawned >= self.daggers_per_spawn:
                    break

                if (
                    self.owning_reptomancer.daggers[i] is None
                    or self.owning_reptomancer.daggers[i].is_dead_or_escaped()
                ):
                    dagger_to_spawn = SnakeDagger(
                        self.ctx,
                    )
                    self.owning_reptomancer.daggers[i] = dagger_to_spawn
                    self.ctx.action_manager.add_to_bottom(
                        SpawnMonsterAction(self.ctx, dagger_to_spawn, True)
                    )
                    daggers_spawned += 1

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        self.daggers: List[Optional[Monster]] = [None] * self.max_num_daggers
        daggers_per_spawn = ADV.of(1).with_asc(18, 2)
        snake_strike_damage = ADV.of(13).with_asc(3, 16)
        snake_strike_multiplier = 2
        big_bite_damage = ADV.of(30).with_asc(3, 34)
        moves = {
            MoveName.SUMMON: self.SpawnDaggersMove(ctx, self, daggers_per_spawn),
            MoveName.SNAKE_STRIKE: AttackDebuffMove(
                ctx,
                self,
                lambda pl: [WeakPower(ctx, pl, 1, True)],
                snake_strike_damage,
                snake_strike_multiplier,
            ),
            MoveName.BIG_BITE: AttackMove(ctx, self, big_bite_damage),
        }
        super().__init__(
            ctx,
            AscensionManager.check_ascension(self, 180, 8, 190),
            AscensionManager.check_ascension(self, 190, 8, 200),
            moves,
            *args,
            **kwargs,
        )

    def use_pre_battle_action(self):
        for m in self.ctx.d.get_curr_room().monster_group:
            if m.name != self.name:
                self.ctx.action_manager.add_to_bottom(
                    ApplyPowerAction(self.ctx, m, m, MinionPower(self.ctx, self))
                )

            if isinstance(m, SnakeDagger):
                if self.ctx.d.get_curr_room().monster_group.index_of(
                    m
                ) > self.ctx.d.get_curr_room().monster_group.index_of(m):
                    self.daggers[0] = m
                else:
                    self.daggers[1] = m

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)

        for m in self.ctx.d.get_curr_room().monster_group:
            if not m.is_dead and not m.is_dying:
                self.ctx.action_manager.add_to_top(SuicideAction(self.ctx, m))

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.SUMMON
        else:
            if num < 33:
                if not self.last_move(MoveName.SNAKE_STRIKE):
                    mn = MoveName.SNAKE_STRIKE
                else:
                    mn = self._get_move_impl(
                        ai_rng.random(33, 99), is_first_move, ai_rng, 0
                    )
            elif num < 66:
                if not self.last_two_moves(MoveName.SUMMON):
                    if self.can_spawn():
                        mn = MoveName.SUMMON
                    else:
                        mn = MoveName.SNAKE_STRIKE
                else:
                    mn = MoveName.SNAKE_STRIKE
            elif not self.last_move(MoveName.BIG_BITE):
                mn = MoveName.BIG_BITE
            else:
                mn = self._get_move_impl(
                    ai_rng.random_from_0_to(65), is_first_move, ai_rng, 0
                )

        return mn

    def can_spawn(self):
        # Stupid hack, this breaks when Reptomancer is created outside a game.
        if self.ctx.d.get_curr_room().monster_group is None:
            return True

        return (
            sum(
                [
                    1 if m is not self and not m.is_dying else 0
                    for m in self.ctx.d.get_curr_room().monster_group.monsters
                ]
            )
            <= 3
        )


class SnakeDagger(Monster):
    class ExplodeMove(DamageMove):
        def get_intent(self):
            return Intent.ATTACK

        def _act_impl(self, owner: Monster):
            super()._act_impl(owner)
            self.add_to_bottom(
                LoseHPAction(
                    self.ctx, self.owner, self.owner, self.owner.current_health
                )
            )

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        moves = {
            MoveName.STAB: AttackTrashDiscardMove(
                ctx,
                self,
                9,
                Wound(
                    ctx,
                ),
                1,
            ),
            MoveName.EXPLODE: self.ExplodeMove(ctx, self, 25),
        }
        super().__init__(ctx, 20, 25, moves, *args, **kwargs)

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.STAB
        else:
            mn = MoveName.EXPLODE
        return mn


class LouseDefensive(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        bite_damage = (
            ctx.monster_hp_rng.random(5, 7) + ADV.of(0).with_asc(2, 1).resolve()
        )
        moves = {
            MoveName.BITE: AttackMove(ctx, self, bite_damage),
            MoveName.SPIT_WEB: DebuffMove(
                ctx, self, lambda pl: [WeakPower(ctx, pl, 2, is_source_monster=True)]
            ),
        }
        super().__init__(
            ctx,
            ADV.of(11).with_asc(7, 12),
            ADV.of(17).with_asc(7, 18),
            moves,
            *args,
            **kwargs,
        )

    def use_pre_battle_action(self):
        min_amount = ADV.of(3).with_asc(7, 4).with_asc(17, 9).resolve()
        max_amount = ADV.of(7).with_asc(7, 8).with_asc(17, 12).resolve()
        amount = self.ctx.monster_hp_rng.random(min_amount, max_amount)
        self.add_to_bottom(
            ApplyPowerAction(self.ctx, self, self, CurlUpPower(self.ctx, self, amount))
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if AscensionManager.get_ascension(self) >= 17:
            if num < 25:
                if self.last_move(MoveName.SPIT_WEB):
                    mn = MoveName.BITE
                else:
                    mn = MoveName.SPIT_WEB
            elif self.last_two_moves(MoveName.BITE):
                mn = MoveName.SPIT_WEB
            else:
                mn = MoveName.BITE
        else:
            if num < 25:
                if self.last_two_moves(MoveName.SPIT_WEB):
                    mn = MoveName.BITE
                else:
                    mn = MoveName.SPIT_WEB
            elif self.last_two_moves(MoveName.BITE):
                mn = MoveName.SPIT_WEB
            else:
                mn = MoveName.BITE

        return mn


class LouseNormal(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        bite_damage = (
            ctx.monster_hp_rng.random(5, 7) + ADV.of(0).with_asc(2, 1).resolve()
        )
        strength_gain = ADV.of(3).with_asc(17, 4).resolve()
        moves = {
            MoveName.BITE: AttackMove(ctx, self, bite_damage),
            MoveName.GROW: BuffMove(
                ctx, self, lambda m: [StrengthPower(ctx, m, strength_gain)]
            ),
        }
        super().__init__(
            ctx,
            ADV.of(10).with_asc(7, 11),
            ADV.of(15).with_asc(7, 16),
            moves,
            *args,
            **kwargs,
        )

    def use_pre_battle_action(self):
        min_amount = ADV.of(3).with_asc(7, 4).with_asc(17, 9).resolve()
        max_amount = ADV.of(7).with_asc(7, 8).with_asc(17, 9).resolve()
        amount = self.ctx.monster_hp_rng.random(min_amount, max_amount)
        self.add_to_bottom(
            ApplyPowerAction(self.ctx, self, self, CurlUpPower(self.ctx, self, amount))
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if AscensionManager.get_ascension(self) >= 17:
            if num < 25:
                if self.last_move(MoveName.GROW):
                    mn = MoveName.BITE
                else:
                    mn = MoveName.GROW
            elif self.last_two_moves(MoveName.BITE):
                mn = MoveName.GROW
            else:
                mn = MoveName.BITE
        else:
            if num < 25:
                if self.last_two_moves(MoveName.GROW):
                    mn = MoveName.BITE
                else:
                    mn = MoveName.GROW
            elif self.last_two_moves(MoveName.BITE):
                mn = MoveName.GROW
            else:
                mn = MoveName.BITE

        return mn


class FungiBeast(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        bite_damage = 6
        strength_gain = ADV.of(3).with_asc(2, 4).with_asc(17, 5).resolve()
        moves = {
            MoveName.BITE: AttackMove(ctx, self, bite_damage),
            MoveName.GROW: BuffMove(
                ctx, self, lambda m: [StrengthPower(ctx, m, strength_gain)]
            ),
        }
        super().__init__(ctx, ADV.of(22).with_asc(7, 24), 28, moves, *args, **kwargs)

    def use_pre_battle_action(self):
        self.add_to_bottom(
            ApplyPowerAction(self.ctx, self, self, SporeCloudPower(self.ctx, self, 2))
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if num < 60:
            if self.last_two_moves(MoveName.BITE):
                mn = MoveName.GROW
            else:
                mn = MoveName.BITE
        elif self.last_move(MoveName.GROW):
            mn = MoveName.BITE
        else:
            mn = MoveName.GROW

        return mn


class GremlinFat(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        smash_damage = ADV.of(4).with_asc(2, 5)

        def gen_debuffs(pl: Player):
            powers = [WeakPower(ctx, pl, 1, True)]
            if AscensionManager.get_ascension(self) >= 17:
                powers.append(FrailPower(ctx, pl, 1, True))
            return powers

        moves = {
            MoveName.SMASH: AttackDebuffMove(ctx, self, gen_debuffs, smash_damage),
        }
        super().__init__(
            ctx,
            ADV.of(13).with_asc(7, 14),
            ADV.of(17).with_asc(7, 18),
            moves,
            *args,
            **kwargs,
        )


class GremlinTsundere(Monster):
    """aka Shield Gremlin"""

    enqueue_roll_move_after_acting = False

    class ProtectMove(Move):
        def get_intent(self):
            return Intent.DEFEND

        def _act_impl(self, owner: Monster):
            block = ADV.of(7).with_asc(7, 8).with_asc(17, 11).resolve()
            self.add_to_bottom(
                GainBlockRandomMonsterAction(self.ctx, block, self.owner)
            )

            alive_count = sum(
                [
                    1
                    for m in self.ctx.d.get_curr_room().monster_group
                    if not m.is_dying and not m.is_escaping
                ]
            )

            # Ignore escapeNext?
            if alive_count > 1:
                # TODO This probably doesn't get to move history
                self.owner.next_move_name = MoveName.PROTECT
            else:
                self.owner.next_move_name = MoveName.SHIELD_BASH

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        damage = ADV.of(6).with_asc(2, 8)
        moves = {
            MoveName.SHIELD_BASH: AttackMove(ctx, self, damage),
            MoveName.PROTECT: self.ProtectMove(ctx, self),
        }
        super().__init__(
            ctx,
            ADV.of(12).with_asc(7, 13),
            ADV.of(15).with_asc(7, 17),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        # Source doesn't enqueue a RollMoveAction, so this only sets first move.
        assert is_first_move
        return MoveName.PROTECT


class GremlinThief(Monster):
    """aka Sneaky Gremlin"""

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        damage = ADV.of(9).with_asc(2, 10)
        moves = {
            MoveName.PUNCTURE: AttackMove(ctx, self, damage),
        }
        super().__init__(
            ctx,
            ADV.of(10).with_asc(7, 11),
            ADV.of(14).with_asc(7, 15),
            moves,
            *args,
            **kwargs,
        )


class GremlinWarrior(Monster):
    """aka Mad Gremlin"""

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        damage = ADV.of(4).with_asc(2, 5)
        self.angry_amount = ADV.of(1).with_asc(17, 2).resolve()
        moves = {
            MoveName.SCRATCH: AttackMove(ctx, self, damage),
        }
        super().__init__(
            ctx,
            ADV.of(20).with_asc(7, 24),
            ADV.of(21).with_asc(7, 25),
            moves,
            *args,
            **kwargs,
        )

    def use_pre_battle_action(self):
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx, self, self, AngryPower(self.ctx, self, self.angry_amount)
            )
        )


class GremlinWizard(Monster):
    class ChargingMove(Move):
        def get_intent(self):
            return Intent.UNKNOWN

        def _act_impl(self, owner: Monster):
            assert isinstance(self.owner, GremlinWizard)
            assert self.owner.current_charge < 3
            self.owner.current_charge += 1

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        damage = ADV.of(25).with_asc(2, 30)
        self.current_charge = 1
        moves = {
            MoveName.ULTIMATE_BLAST: AttackMove(ctx, self, damage),
            MoveName.CHARGING: self.ChargingMove(ctx, self),
        }
        super().__init__(
            ctx,
            ADV.of(21).with_asc(7, 22),
            ADV.of(25).with_asc(7, 26),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        if self.current_charge >= 3:
            # This isn't quite how source does it, but I think it's equivalent and easier.
            logger.debug(f"Resetting charge for {self.name} to 0")
            self.current_charge = 0
            mn = MoveName.ULTIMATE_BLAST
        else:
            mn = MoveName.CHARGING
        return mn


class Lagavulin(Monster):
    class StunnedMove(Move):
        def get_intent(self):
            return Intent.STUN

        def _act_impl(self, owner: Monster):
            logger.debug(f"{self.owner.name} is stunned")

    class SleepMove(Move):
        def get_intent(self):
            return Intent.SLEEP

        def _act_impl(self, owner: Monster):
            assert isinstance(self.owner, Lagavulin)
            self.owner.idle_count += 1
            if self.owner.idle_count >= 3:
                logger.debug(f"{self.owner.name} idled awake")
                self.owner.is_out_triggered = True
                self.owner.is_out = True
            else:
                logger.debug(f"{self.owner.name} sleeping")

    def __init__(self, ctx: CCG.Context, asleep: bool = True, *args, **kwargs):
        damage = ADV.of(18).with_asc(3, 20)
        siphon_amount = ADV.of(-1).with_asc(18, -2).resolve()
        moves = {
            MoveName.ATTACK: AttackMove(ctx, self, damage),
            MoveName.SIPHON_SOUL: DebuffMove(
                ctx,
                self,
                lambda pl: [
                    StrengthPower(ctx, ctx.player, siphon_amount),
                    DexterityPower(ctx, ctx.player, siphon_amount),
                ],
            ),
            MoveName.STUNNED: self.StunnedMove(ctx, self),
            MoveName.SLEEP: self.SleepMove(ctx, self),
        }
        super().__init__(
            ctx,
            ADV.of(109).with_asc(8, 112),
            ADV.of(111).with_asc(8, 115),
            moves,
            *args,
            **kwargs,
        )
        self.asleep = asleep
        self.is_out_triggered = self.is_out = not asleep
        self.idle_count = 0

    def use_pre_battle_action(self):
        if self.asleep:
            self.add_to_bottom(GainBlockAction(self.ctx, self, 8))
            self.add_to_bottom(
                ApplyPowerAction(
                    self.ctx, self, self, MetallicizePower(self.ctx, self, 8)
                )
            )
        else:
            self.next_move_name = MoveName.SIPHON_SOUL

    def damage(self, damage_info: DamageInfo):
        previous_health = self.current_health
        super().damage(damage_info)

        if self.current_health != previous_health and not self.is_out_triggered:
            self.is_out_triggered = True
            self.next_move_name = MoveName.STUNNED
            self.is_out = True

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken
    ) -> MoveName:
        # I implemented this a bit differently than source, but I think it's equivalent.
        if self.is_out:
            if self.last_two_moves(MoveName.ATTACK):
                mn = MoveName.SIPHON_SOUL
            else:
                mn = MoveName.ATTACK
        else:
            mn = MoveName.SLEEP
        return mn


class Looter(Monster):
    class StealGoldAndAttackMove(AttackMove):
        def _act_impl(self, owner: Monster):
            assert isinstance(self.owner, Looter)
            self.add_to_bottom(
                AddStolenGoldToMonsterAction(
                    self.ctx, self.ctx.player, self.steal_gold_amount, self.owner
                )
            )
            super()._act_impl(owner)

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        mug_damage = ADV.of(10).with_asc(2, 11)
        lunge_damage = ADV.of(12).with_asc(2, 14)
        self.gold_amount = ADV.of(15).with_asc(17, 20).resolve()
        self.stolen_gold = 0
        moves = {
            MoveName.MUG: self.StealGoldAndAttackMove(
                ctx, self, mug_damage, steal_gold_amount=self.gold_amount
            ),
            MoveName.LUNGE: self.StealGoldAndAttackMove(
                ctx, self, lunge_damage, steal_gold_amount=self.gold_amount
            ),
            MoveName.SMOKE_BOMB: DefendMove(ctx, self, 6),
            MoveName.ESCAPE: EscapeMove(ctx, self, set_mugged=True),
        }
        super().__init__(
            ctx,
            ADV.of(44).with_asc(7, 48),
            ADV.of(46).with_asc(7, 50),
            moves,
            *args,
            **kwargs,
        )

    def use_pre_battle_action(self):
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx, self, self, ThieveryPower(self.ctx, self, self.gold_amount)
            )
        )

    def die(self, trigger_relics: bool = None):
        if self.stolen_gold > 0:
            self.ctx.d.get_curr_room().add_stolen_gold_to_rewards(self.stolen_gold)
        super().die(trigger_relics)

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        # This isn't how source does it, which probably led to a bug where this method was called after escape.
        if turns_taken < 2:
            mn = MoveName.MUG
        elif turns_taken < 3:
            if ai_rng.random_boolean():
                mn = MoveName.LUNGE
            else:
                mn = MoveName.SMOKE_BOMB
        elif self.last_move(MoveName.SMOKE_BOMB):
            mn = MoveName.ESCAPE
        elif self.last_move(MoveName.LUNGE):
            mn = MoveName.SMOKE_BOMB
        elif self.last_move(MoveName.ESCAPE):
            # I _think_ source gets around this issue (get move on escaped monster) by only calling get move for the
            # first move, then setting next move explicitly in takeTurn. If that's right, we'll probably have to bandaid
            # other escaping monsters, too.
            assert self.escaped
            logger.debug("Ignoring get move because last move was escape")
            mn = MoveName.ESCAPE
        else:
            raise Exception("how did you get here")
        return mn


class Sentry(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        beam_damage = ADV.of(9).with_asc(3, 10)
        dazed_amount = ADV.of(2).with_asc(18, 3).resolve()
        moves = {
            MoveName.BEAM: TrashDiscardMove(ctx, self, Dazed(ctx), dazed_amount),
            MoveName.BOLT: AttackMove(ctx, self, beam_damage),
        }
        super().__init__(
            ctx,
            ADV.of(38).with_asc(8, 39),
            ADV.of(42).with_asc(8, 45),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        if is_first_move:
            if self.ctx.d.get_curr_room().monster_group.index_of(self) % 2 == 0:
                mn = MoveName.BOLT
            else:
                mn = MoveName.BEAM
        else:
            if self.last_move(MoveName.BEAM):
                mn = MoveName.BOLT
            else:
                mn = MoveName.BEAM
        return mn


class SlaverBlue(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        stab_damage = ADV.of(12).with_asc(2, 13)
        rake_damage = ADV.of(7).with_asc(2, 8)
        weak_amount = ADV.of(1).with_asc(17, 2).resolve()
        moves = {
            MoveName.STAB: AttackMove(ctx, self, stab_damage),
            MoveName.RAKE: AttackDebuffMove(
                ctx,
                self,
                lambda pl: [WeakPower(ctx, pl, weak_amount, True)],
                rake_damage,
            ),
        }
        super().__init__(
            ctx,
            ADV.of(46).with_asc(7, 48),
            ADV.of(50).with_asc(7, 52),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        if num >= 40 and not self.last_two_moves(MoveName.STAB):
            mn = MoveName.STAB
        elif AscensionManager.get_ascension(self) >= 17:
            if not self.last_move(MoveName.RAKE):
                mn = MoveName.RAKE
            else:
                mn = MoveName.STAB
        elif not self.last_two_moves(MoveName.RAKE):
            mn = MoveName.RAKE
        else:
            mn = MoveName.STAB
        return mn


class SlaverRed(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        stab_damage = ADV.of(13).with_asc(2, 14)
        scrape_damage = ADV.of(8).with_asc(2, 9)
        vulnerable_amount = ADV.of(1).with_asc(17, 2).resolve()
        moves = {
            MoveName.STAB: AttackMove(ctx, self, stab_damage),
            MoveName.SCRAPE: AttackDebuffMove(
                ctx,
                self,
                lambda pl: [VulnerablePower(ctx, pl, vulnerable_amount, True)],
                scrape_damage,
            ),
            MoveName.ENTANGLE: DebuffMove(
                ctx, self, lambda pl: [EntangledPower(ctx, pl, None)]
            ),
        }
        super().__init__(
            ctx,
            ADV.of(46).with_asc(7, 48),
            ADV.of(50).with_asc(7, 52),
            moves,
            *args,
            **kwargs,
        )
        self.used_entangle = False

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.STAB
        elif num >= 75 and not self.used_entangle:
            mn = MoveName.ENTANGLE
        elif (
            num >= 55 and self.used_entangle and not self.last_two_moves(MoveName.STAB)
        ):
            mn = MoveName.STAB
        elif AscensionManager.get_ascension(self) >= 17:
            if not self.last_move(MoveName.SCRAPE):
                mn = MoveName.SCRAPE
            else:
                mn = MoveName.STAB
        elif not self.last_two_moves(MoveName.SCRAPE):
            mn = MoveName.SCRAPE
        else:
            mn = MoveName.STAB
        return mn


class SlimeBoss(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        slam_damage = ADV.of(35).with_asc(4, 38)
        slimed_count = ADV.of(3).with_asc(19, 5).resolve()
        moves = {
            MoveName.GOOP_SPRAY: TrashDiscardMove(
                ctx,
                self,
                Slimed(
                    ctx,
                ),
                slimed_count,
            ),
            MoveName.PREPARING: NoOpMove(ctx, self, Intent.UNKNOWN),
            MoveName.SLAM: AttackMove(ctx, self, slam_damage),
            MoveName.SPLIT: SplitDifferentMove(
                ctx,
                self,
                [lambda hp: SpikeSlimeL(ctx, hp), lambda hp: AcidSlimeL(ctx, hp)],
            ),
        }
        health = ADV.of(140).with_asc(9, 150)
        super().__init__(ctx, health, health, moves, *args, **kwargs)
        self.powers.append(SplitPower(self.ctx, self))

    def damage(self, damage_info: DamageInfo):
        super().damage(damage_info)
        if (
            not self.is_dying
            and self.current_health <= (self.max_health // 2)
            and self.next_move_name != MoveName.SPLIT
        ):
            logger.debug("Split triggered, setting move to split")
            # Seems redundant, but source both sets move directly here and enqueues a set action.
            self.next_move_name = MoveName.SPLIT
            self.create_intent()
            self.add_to_bottom(SetMoveAction(self.ctx, self, MoveName.SPLIT))

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)
        if not any(
            (isinstance(a, SpawnMonsterAction) for a in self.ctx.action_manager.actions)
        ):
            if self.current_health <= 0:
                self.on_boss_victory_logic()

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        i = turns_taken % 3
        if i == 0:
            mn = MoveName.GOOP_SPRAY
        elif i == 1:
            mn = MoveName.PREPARING
        elif i == 2:
            mn = MoveName.SLAM
        else:
            raise Exception()
        return mn


class TheGuardian(Monster):
    class GoDefensiveAction(Action):
        def __init__(self, ctx: CCG.Context, owner: TheGuardian):
            super().__init__(ctx)
            self.owner = owner

        def act(self):
            self.ctx.action_manager.add_to_bottom(
                RemoveSpecificPowerAction(self.ctx, self.owner, ModeShiftPower)
            )
            self.ctx.action_manager.add_to_bottom(
                GainBlockAction(self.ctx, self.owner, 20)
            )
            self.owner.damage_threshold += 10
            self.owner.next_move_name = MoveName.DEFENSIVE_MODE
            self.owner.is_open = False
            self.owner.close_up_triggered = False

    class GoOffensiveAction(Action):
        def __init__(self, ctx: CCG.Context, owner: TheGuardian):
            super().__init__(ctx)
            self.owner = owner

        def act(self):
            self.ctx.action_manager.add_to_bottom(
                ApplyPowerAction(
                    self.ctx,
                    self.owner,
                    self.owner,
                    ModeShiftPower(self.ctx, self.owner, self.owner.damage_threshold),
                )
            )
            self.ctx.action_manager.add_to_bottom(
                TheGuardian.ResetDamageTakenAction(self.ctx, self.owner)
            )
            if self.owner.current_block != 0:
                self.ctx.action_manager.add_to_bottom(
                    LoseBlockAction(self.ctx, self.owner, self.owner.current_block)
                )
            self.owner.is_open = True

    class ResetDamageTakenAction(Action):
        def __init__(self, ctx: CCG.Context, owner: TheGuardian):
            super().__init__(ctx)
            self.owner = owner

        def act(self):
            self.owner.damage_taken = 0

    class TwinSlamMove(AttackMove):

        # noinspection PyFinal
        def get_intent(self):
            return Intent.ATTACK_BUFF

        def _act_impl(self, owner: Monster):
            assert isinstance(self.owner, TheGuardian)
            self.add_to_bottom(TheGuardian.GoOffensiveAction(self.ctx, self.owner))
            super()._act_impl(owner)
            self.add_to_bottom(
                RemoveSpecificPowerAction(self.ctx, self.owner, SharpHidePower)
            )

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        bash_damage = ADV.of(32).with_asc(4, 36)
        sharp_hide_amount = ADV.of(3).with_asc(19, 4).resolve()
        roll_damage = ADV.of(9).with_asc(4, 10)
        moves = {
            MoveName.CHARGING_UP: DefendMove(ctx, self, 9),
            MoveName.FIERCE_BASH: AttackMove(ctx, self, bash_damage),
            MoveName.VENT_STEAM: DebuffMove(
                ctx,
                self,
                lambda pl: [
                    VulnerablePower(ctx, pl, 2, True),
                    WeakPower(ctx, pl, 2, True),
                ],
            ),
            MoveName.WHIRLWIND: AttackMove(ctx, self, 5, multiplier=4),
            MoveName.DEFENSIVE_MODE: BuffMove(
                ctx, self, lambda m: [SharpHidePower(ctx, m, sharp_hide_amount)]
            ),
            MoveName.ROLL_ATTACK: AttackMove(ctx, self, roll_damage),
            MoveName.TWIN_SLAM: self.TwinSlamMove(ctx, self, 8, multiplier=2),
        }
        health = ADV.of(240).with_asc(9, 250)
        super().__init__(ctx, health, health, moves, *args, **kwargs)
        self.is_open = True
        self.damage_threshold = ADV.of(30).with_asc(9, 35).with_asc(19, 40).resolve()
        self.damage_taken = 0
        self.close_up_triggered = False

    def use_pre_battle_action(self):
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                self,
                self,
                ModeShiftPower(self.ctx, self, self.damage_threshold),
            )
        )

    def damage(self, damage_info: DamageInfo):
        before_health = self.current_health
        super().damage(damage_info)

        if (
            self.is_open
            and not self.close_up_triggered
            and before_health > self.current_health
            and not self.is_dying
        ):
            health_change = before_health - self.current_health
            self.damage_taken += health_change
            if self.has_power(ModeShiftPower):
                msp = self.get_power(ModeShiftPower)
                msp.amount -= health_change

            if self.damage_taken >= self.damage_threshold:
                self.damage_taken = 0
                self.add_to_bottom(TheGuardian.GoDefensiveAction(self.ctx, self))
                self.close_up_triggered = True

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.CHARGING_UP
        elif self.is_open:
            # Offensive mode
            if self.last_move(MoveName.CHARGING_UP):
                mn = MoveName.FIERCE_BASH
            elif self.last_move(MoveName.FIERCE_BASH):
                mn = MoveName.VENT_STEAM
            elif self.last_move(MoveName.VENT_STEAM):
                mn = MoveName.WHIRLWIND
            elif self.last_move(MoveName.WHIRLWIND):
                mn = MoveName.CHARGING_UP
            else:
                # This means came out of defense? So Whirlwind?
                mn = MoveName.WHIRLWIND
                # See if this is right
                assert self.last_move(MoveName.TWIN_SLAM)
        else:
            # Defensive mode
            if self.last_move(MoveName.DEFENSIVE_MODE):
                mn = MoveName.ROLL_ATTACK
            elif self.last_move(MoveName.ROLL_ATTACK):
                mn = MoveName.TWIN_SLAM
            # elif self.last_move(MoveName.TWIN_SLAM):
            else:
                raise Exception("shouldn't get here?")
                # mn = MoveName.WHIRLWIND
        return mn

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)
        self.on_boss_victory_logic()


class GremlinNob(Monster):
    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        rush_damage = ADV.of(14).with_asc(3, 16).resolve()
        bash_damage = ADV.of(6).with_asc(3, 8).resolve()
        bellow_amount = ADV.of(2).with_asc(18, 3).resolve()
        moves = {
            MoveName.BELLOW: BuffMove(
                ctx, self, lambda m: [AngerPower(ctx, m, bellow_amount)]
            ),
            MoveName.RUSH: AttackMove(ctx, self, rush_damage),
            MoveName.SKULL_BASH: AttackDebuffMove(
                ctx, self, lambda p: [VulnerablePower(ctx, p, 2, True)], bash_damage
            ),
        }
        super().__init__(
            ctx,
            ADV.of(82).with_asc(8, 85),
            ADV.of(86).with_asc(8, 90),
            moves,
            *args,
            **kwargs,
        )

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.BELLOW
        elif AscensionManager.get_ascension(self) >= 18:
            if not self.last_two_moves(MoveName.SKULL_BASH):
                # Source's canVuln is always true. Source's impl here is weird. Maybe it was early.
                mn = MoveName.SKULL_BASH
            elif self.last_two_moves(MoveName.RUSH):
                mn = MoveName.SKULL_BASH
            else:
                mn = MoveName.RUSH
        else:
            if num < 33:
                mn = MoveName.SKULL_BASH
            elif self.last_two_moves(MoveName.RUSH):
                mn = MoveName.SKULL_BASH
            else:
                mn = MoveName.RUSH
        return mn


class Hexaghost(Monster):
    class ActivateMove(Move):
        def __init__(
            self, ctx: CCG.Context, owner: Monster, divider: Hexaghost.DividerMove
        ):
            super().__init__(ctx, owner)
            self.divider = divider

        def get_intent(self):
            return Intent.UNKNOWN

        def _act_impl(self, owner: Monster):
            new_base_damage = self.ctx.player.current_health // 12 + 1
            logger.debug(f"Updating Divider's base damage to {new_base_damage}")
            self.divider.update_damage_info(new_base_damage)
            self.owner.apply_powers()

    class DividerMove(AttackMove):
        def update_damage_info(self, new_base_damage: int):
            self.damage_info.base = new_base_damage

    class InfernoMove(AttackMove):
        def _act_impl(self, owner: Monster):
            assert isinstance(self.owner, Hexaghost)
            super()._act_impl(owner)
            self.add_to_bottom(BurnIncreaseAction(self.ctx))
            self.owner.burn_upgraded = True

    def __init__(self, ctx: CCG.Context, *args, **kwargs):
        inferno_damage = ADV.of(2).with_asc(4, 3).resolve()
        tackle_damage = ADV.of(5).with_asc(4, 6).resolve()
        sear_amount = ADV.of(1).with_asc(19, 2).resolve()
        inflame_strength = ADV.of(2).with_asc(19, 3).resolve()
        divider = self.DividerMove(ctx, self, 0, 6)
        moves = {
            MoveName.ACTIVATE: self.ActivateMove(ctx, self, divider),
            MoveName.DIVIDER: divider,
            MoveName.INFERNO: self.InfernoMove(ctx, self, inferno_damage, multiplier=6),
            MoveName.SEAR: AttackTrashDiscardMove(
                ctx,
                self,
                6,
                Burn(
                    ctx,
                ),
                sear_amount,
            ),
            MoveName.TACKLE: AttackMove(ctx, self, tackle_damage, multiplier=2),
            MoveName.INFLAME: DefendBuffMove(
                ctx, self, lambda m: [StrengthPower(ctx, m, inflame_strength)], 12
            ),
        }
        health = ADV.of(250).with_asc(9, 264)
        super().__init__(ctx, health, health, moves, *args, **kwargs)
        self.burn_upgraded = False

    def _get_move_impl(
        self, num: int, is_first_move: bool, ai_rng: Rng, turns_taken: int
    ) -> MoveName:
        if is_first_move:
            mn = MoveName.ACTIVATE
        elif turns_taken == 1:
            mn = MoveName.DIVIDER
        else:
            sequence = [
                MoveName.SEAR,
                MoveName.TACKLE,
                MoveName.SEAR,
                MoveName.INFLAME,
                MoveName.TACKLE,
                MoveName.SEAR,
                MoveName.INFERNO,
            ]
            i = (turns_taken - 2) % len(sequence)
            mn = sequence[i]
        return mn

    def die(self, trigger_relics: bool = None):
        super().die(trigger_relics)
        self.on_boss_victory_logic()


class MonsterGroup:
    def __init__(self, ctx: CCG.Context, monsters: List[Monster]):
        self.ctx = ctx
        self.monsters: List[Monster] = monsters

    def __repr__(self):
        return os.linesep.join([m.__repr__() for m in self.monsters])

    def __iter__(self):
        return self.monsters.__iter__()

    def __getitem__(self, item):
        return self.monsters.__getitem__(item)

    def __len__(self):
        return len(self.monsters)

    def update(self):
        for m in self.monsters:
            m.update()

    def initialize(self):
        for m in self.monsters:
            m.initialize()

    def index_of(self, monster: Monster):
        return self.monsters.index(monster)

    def add_monster(self, monster: Monster):
        # I'm not sure how source deals with dead monsters in groups. Let's see if this works.
        if len(self.monsters) >= MAX_NUM_MONSTERS_IN_GROUP:
            # Find a dead or escaped monster to replace
            replaced_index, replaced_monster = next(
                ((i, m) for i, m in enumerate(self.monsters) if m.is_dead_or_escaped()),
                None,
            )
            if replaced_index is None:
                raise Exception("No room for new monsters in group")
            logger.debug(
                f"Replacing dead/escaped monster {replaced_monster.name} at index {replaced_index}: {monster.name}"
            )
            self.monsters[replaced_index] = monster
        else:
            index = 0
            logger.debug(f"Adding monster at index {index}: {monster.name}")
            self.monsters.insert(index, monster)

    def are_monsters_dead(self):
        return all(m.is_dead or m.escaped for m in self.monsters)

    def are_monsters_basically_dead(self):
        return all(m.is_dying or m.is_escaping for m in self.monsters)

    def use_pre_battle_action(self):
        for m in self.monsters:
            m.use_pre_battle_action()
            m.use_universal_pre_battle_action()

    def apply_pre_turn_logic(self):
        for m in self.monsters:
            if not m.is_dying and not m.is_escaping:
                # TODO barricade
                m.lose_block()

            m.apply_start_of_turn_powers()

    def apply_powers(self):
        for m in self.monsters:
            m.apply_powers()

    def apply_end_of_turn_powers(self):
        for m in self.monsters:
            if not m.is_dying and not m.is_escaping:
                m.apply_end_of_turn_triggers()

        for p in self.ctx.player.powers:
            p.at_end_of_round()

        for m in self.monsters:
            if not m.is_dying and not m.is_escaping:
                for p in m.powers:
                    p.at_end_of_round()

    def have_monsters_escaped(self):
        return all((m.escaped for m in self.monsters))


class EnemyMoveInfo:
    def __init__(
        self,
        next_move: int,
        intent: Intent,
        base_damage: int = None,
        multiplier: int = None,
    ):
        self.next_move: int = next_move
        self.intent: Intent = intent
        self.base_damage: Optional[int] = base_damage
        # Source appears to use this only for showing intent, not damage calculation
        self.multiplier: Optional[int] = multiplier

    def __repr__(self):
        multiplier_repr = f"{self.multiplier}x " if self.multiplier is not None else ""
        base_damage_repr = "X" if self.base_damage is None else self.base_damage
        return f"Next {self.next_move} {self.intent.name} {multiplier_repr}{base_damage_repr}"

    def is_multi_damage(self):
        return self.multiplier is not None


class Intent(Enum):
    ATTACK = 0
    DEFEND = 1
    DEBUFF = 2
    ATTACK_DEBUFF = 3
    UNKNOWN = 4
    BUFF = 5
    DEFEND_BUFF = 6
    ATTACK_DEFEND = 7
    ESCAPE = 8
    STUN = 9
    SLEEP = 10
    ATTACK_BUFF = 11


class SimpleChoiceEventRequest(PlayerRequest):
    def __init__(self, ctx: CCG.Context, event: SimpleChoiceEvent):
        super().__init__(ctx)
        self.event = event

    def __repr__(self):
        return f"Request for {self.event}"

    def handle_play_card_action(self, action: ActionCoord):
        self.event.button_effect(action[0])
        self.ctx.action_manager.outstanding_request = None
        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE

    def generate_action_mask(self) -> ActionMask:
        play_card_slices = [
            ACTION_1_SINGLE_TRUE
            if i < self.event.num_choices
            else ACTION_1_ALL_FALSE_SLICE
            for i in range(MAX_HAND_SIZE)
        ]
        return ActionMask(play_card_slices)


class DiscardRequest(PlayerRequest):
    def __init__(
        self,
        ctx: CCG.Context,
        num_cards: Optional[int],
        any_number: bool,
        can_pick_zero: bool,
        end_turn: bool,
        from_gambling: bool,
    ):
        # You can't specify a number of cards and say "pick any number of cards".
        super().__init__(ctx)
        self.ctx = ctx
        assert not (num_cards is not None and any_number)
        self.num_cards = num_cards
        self.any_number = any_number
        self.can_pick_zero = can_pick_zero
        self.end_turn = end_turn
        self.chosen_cards: List[Card] = []
        self.is_gambling_chip = from_gambling

    def __repr__(self) -> str:
        if self.num_cards is not None:
            s = f"Discard exactly {self.num_cards} cards"
        else:
            assert self.any_number
            s = f'Discard any number of cards, {"in" if self.can_pick_zero else "ex"}cluding zero'

        return s + f" with {len(self.chosen_cards)} already chosen"

    def handle_end_turn_action(self, action: ActionCoord):
        # Only need to stop picking discards if player could pick any number, and they must have satisfied pick zero
        # if not set.
        assert self.any_number and self.can_pick_zero

        if self.is_gambling_chip:
            num_to_draw = len(self.chosen_cards)
            logger.debug(f"Gambling set, enqueueing draw {num_to_draw}")
            self.ctx.action_manager.add_to_top(DrawCardAction(self.ctx, num_to_draw))

        self._do_requested_discards()

    def handle_play_card_action(self, action: ActionCoord):
        i = action[0]
        card = self.ctx.player.hand[i]
        assert self.num_cards is None or self.num_cards > 0

        self.chosen_cards.append(card)

        if not self.can_pick_zero:
            logger.debug(f'{self} has satisfied "cannot pick zero" condition')
            self.can_pick_zero = True

        if self.num_cards is not None:
            assert not self.any_number
            self.num_cards -= 1
            logger.debug(f"{self} has {self.num_cards} cards left")
            if self.num_cards == 0:
                self._do_requested_discards()

        self.clear_response()

    def _do_requested_discards(self):
        # Ensure the request is complete
        assert self.num_cards is None or self.num_cards == 0

        logger.debug(f"Discarding {len(self.chosen_cards)} cards from self")
        for c in self.chosen_cards:
            self.ctx.player.hand.move_to_discard_pile(c)
            c.trigger_on_manual_discard()
            self.ctx.action_manager.increment_discard(self.end_turn)

        logger.debug("Clearing self")
        self.ctx.action_manager.outstanding_request = None

    def generate_action_mask(self) -> ActionMask:
        # Player is choosing a card to discard
        # End turn means stop picking if player wasn't forced to discard a certain number
        player_can_choose_to_stop_discarding = self.can_pick_zero and self.any_number
        end_turn_slice = [
            [False] * MAX_NUM_MONSTERS_IN_GROUP + [player_can_choose_to_stop_discarding]
        ]
        play_card_slices = []
        for card_index in range(MAX_HAND_SIZE):
            # TODO is there any card that can't be discarded?
            if card_index < len(self.ctx.player.hand):
                card = self.ctx.player.hand[card_index]
                can_card_be_discarded = not any(
                    [c.uuid == card.uuid for c in self.chosen_cards]
                )
            else:
                can_card_be_discarded = False

            card_slice = [False] * MAX_NUM_MONSTERS_IN_GROUP + [can_card_be_discarded]
            play_card_slices.append(card_slice)

        return ActionMask(play_card_slices, end_turn_slice)


class PathChoiceRequest(PlayerRequest):
    def __init__(
        self,
        ctx: CCG.Context,
        left_edge: Optional[MapEdge],
        center_edge: Optional[MapEdge],
        right_edge: Optional[MapEdge],
    ):
        super().__init__(ctx)
        self.left_edge = left_edge
        self.center_edge = center_edge
        self.right_edge = right_edge

    @property
    def left_available(self):
        return bool(self.left_edge)

    @property
    def center_available(self):
        return bool(self.center_edge)

    @property
    def right_available(self):
        return bool(self.right_edge)

    def __repr__(self) -> str:
        def available_to_char(available: bool, char_if_available: str):
            assert len(char_if_available) == 1
            return char_if_available if available else "X"

        ll = available_to_char(self.left_available, "\\")
        c = available_to_char(self.center_available, "|")
        r = available_to_char(self.right_available, "/")
        return f"Choose path from: {ll} {c} {r}"

    def generate_action_mask(self) -> ActionMask:
        # Player is choosing to go left, center, right
        play_card_slices = [
            ACTION_1_SINGLE_TRUE if self.left_available else ACTION_1_ALL_FALSE_SLICE,
            ACTION_1_SINGLE_TRUE if self.center_available else ACTION_1_ALL_FALSE_SLICE,
            ACTION_1_SINGLE_TRUE if self.right_available else ACTION_1_ALL_FALSE_SLICE,
        ]
        for _ in range(MAX_HAND_SIZE - 3):
            play_card_slices.append(ACTION_1_ALL_FALSE_SLICE)

        return ActionMask(play_card_slices)

    def handle_play_card_action(self, action: ActionCoord):
        if action[0] == 0:
            edge = self.left_edge
        elif action[0] == 1:
            edge = self.center_edge
        elif action[0] == 2:
            edge = self.right_edge
        else:
            raise ValueError(action)

        assert edge
        logger.debug(f"Path choice edge: {edge}")
        self.ctx.d.next_room_node = self.ctx.d.mapp[edge.dst_y][edge.dst_x]
        self.ctx.action_manager.outstanding_request = None
        self.ctx.d.next_room_transition()


class FirstPathChoiceRequest(PlayerRequest):
    def __init__(self, ctx: CCG.Context, rooms_available: List[bool]):
        super().__init__(ctx)
        assert len(rooms_available) == MAP_WIDTH
        assert any(rooms_available)
        self.rooms_available = rooms_available

    def __repr__(self) -> str:
        def available_to_char(available: bool, char_if_available: str):
            assert len(char_if_available) == 1
            return char_if_available if available else "X"

        available_repr = [available_to_char(a, "|") for a in self.rooms_available]
        return f"Choose initial path from: {available_repr}"

    def handle_play_card_action(self, action: ActionCoord):
        i = action[0]
        assert 0 <= i < MAP_WIDTH
        logger.debug(f"First path choice is {i}")
        self.ctx.d.next_room_node = self.ctx.d.mapp[0][i]
        self.ctx.action_manager.outstanding_request = None
        self.ctx.d.next_room_transition()

    def generate_action_mask(self) -> ActionMask:
        # Player is choosing the initial room in a dungeon
        play_card_slices = []
        for i in range(MAX_HAND_SIZE):
            if i < MAP_WIDTH:
                node_can_be_chosen = self.rooms_available[i]
            else:
                node_can_be_chosen = False

            card_slice = [False] * MAX_NUM_MONSTERS_IN_GROUP + [node_can_be_chosen]
            play_card_slices.append(card_slice)

        return ActionMask(play_card_slices)


class BossPathChoiceRequest(PlayerRequest):
    def generate_action_mask(self) -> ActionMask:
        end_turn_slice = [ACTION_1_SINGLE_TRUE]
        play_card_slices = [ACTION_1_ALL_FALSE_SLICE] * MAX_HAND_SIZE
        return ActionMask(play_card_slices, end_turn_slice)

    def handle_end_turn_action(self, action: ActionCoord):
        boss_node = MapRoomNode(-1, 15)
        boss_node.room = MonsterRoomBoss(
            self.ctx,
        )
        self.ctx.d.next_room_node = boss_node
        self.ctx.action_manager.outstanding_request = None
        self.ctx.d.next_room_transition()


class CombatRewardRequest(PlayerRequest):
    def __init__(self, ctx: CCG.Context, rewards: List[RewardItem]):
        super().__init__(ctx)
        self.rewards = rewards

    def __repr__(self):
        valid_rewards = [r for r in self.rewards if not r.ignore_reward]
        rewards_repr = os.linesep.join([r.__repr__() for r in valid_rewards])
        num_ignored = len(self.rewards) - len(valid_rewards)
        return f"Pick from {len(valid_rewards)} combat rewards ({num_ignored} ignored):{os.linesep}{rewards_repr}"

    def generate_action_mask(self) -> ActionMask:
        # End turn here means done picking rewards
        # TODO you actually can discard and use some potions in combat reward
        end_turn_slice = [ACTION_1_SINGLE_TRUE]
        play_card_slices = []
        assert len(self.rewards) <= MAX_HAND_SIZE
        for card_index in range(MAX_HAND_SIZE):
            if card_index < len(self.rewards):
                card_slice = self.rewards[card_index].to_mask_slice()
            else:
                card_slice = ACTION_1_ALL_FALSE_SLICE
            play_card_slices.append(card_slice)

        return ActionMask(play_card_slices, end_turn_slice)

    def handle_end_turn_action(self, action: ActionCoord):
        left_repr = f", left {len(self.rewards)}" if len(self.rewards) > 0 else ""
        logger.debug(f"Done picking combat rewards{left_repr}")
        self.ctx.action_manager.outstanding_request = None

    def handle_play_card_action(self, action: ActionCoord):
        reward_index = action[0]
        r = self.rewards[reward_index]
        assert not r.ignore_reward
        logger.debug(f"Reward {reward_index} claimed: {r}")
        r.claim_reward(action[1])
        del self.rewards[reward_index]
        # Reset the response so more calls can come in
        self.clear_response()


class BossChestRequest(PlayerRequest):
    def __init__(self, ctx: CCG.Context, rewards: List[RelicRewardItem]):
        super().__init__(ctx)
        self.rewards = rewards

    def __repr__(self):
        # valid_rewards = [r for r in self.rewards if not r.ignore_reward]
        # rewards_repr = os.linesep.join([r.__repr__() for r in valid_rewards])
        # num_ignored = len(self.rewards) - len(valid_rewards)
        # return f'Pick from {len(valid_rewards)} combat rewards ({num_ignored} ignored):{os.linesep}{rewards_repr}'
        return (
            f'Pick a boss relic from: {", ".join([r.__repr__() for r in self.rewards])}'
        )

    def generate_action_mask(self) -> ActionMask:
        # End turn here means done picking rewards
        # TODO you actually can discard and use some potions in combat reward
        end_turn_slice = [ACTION_1_SINGLE_TRUE]
        play_card_slices = []
        assert len(self.rewards) <= MAX_HAND_SIZE
        for card_index in range(MAX_HAND_SIZE):
            if card_index < len(self.rewards):
                card_slice = self.rewards[card_index].to_mask_slice()
            else:
                card_slice = ACTION_1_ALL_FALSE_SLICE
            play_card_slices.append(card_slice)

        return ActionMask(play_card_slices, end_turn_slice)

    def handle_end_turn_action(self, action: ActionCoord):
        # Skip chest
        raise NotImplementedError()

    def handle_play_card_action(self, action: ActionCoord):
        reward_index = action[0]
        r = self.rewards[reward_index]
        logger.debug(f"Boss relic {reward_index} claimed: {r}")
        r.claim_reward(action[1])
        del self.rewards[reward_index]
        self.ctx.action_manager.outstanding_request = None


class CampfireRequest(PlayerRequest):
    def __init__(self, ctx: CCG.Context, options: List[CampfireOption]):
        super().__init__(ctx)
        self.options = options

    def __repr__(self):
        return f'Pick a campfire option from: {", ".join([op.__repr__() for op in self.options])}'

    def handle_play_card_action(self, action: ActionCoord):
        op_i = action[0]
        op = self.options[op_i]
        assert op.usable
        op.use_option()

    def generate_action_mask(self) -> ActionMask:
        def valid(i):
            return i < len(self.options) and self.options[i].usable

        play_card_slices = [
            ACTION_1_SINGLE_TRUE if valid(i) else ACTION_1_ALL_FALSE_SLICE
            for i in range(MAX_HAND_SIZE)
        ]
        return ActionMask(play_card_slices)


class GridSelectRequest(PlayerRequest):
    def __init__(self, ctx: CCG.Context, cards: List[Card]):
        super().__init__(ctx)
        self.cards = cards
        # Ensure we can address all the cards given
        assert len(self.cards) < MAX_HAND_SIZE * ACTION_1_LEN

    def generate_action_mask(self) -> ActionMask:
        # end_turn_slice = [ACTION_1_SINGLE_TRUE]
        play_card_slices = []
        for i in range(MAX_HAND_SIZE):
            play_card_slice = []
            for j in range(ACTION_1_LEN):
                card_index = self.translate_action_to_index((i, j))
                play_card_slice.append(card_index < len(self.cards))
            play_card_slices.append(play_card_slice)

        return ActionMask(play_card_slices)

    def handle_play_card_action(self, action: ActionCoord):
        # Pick card to update
        card_i = self.translate_action_to_index(action)
        card = self.cards[card_i]
        logger.debug(f"Grid select result {action} -> {card_i} -> {card}")
        assert not card.upgraded
        card.upgrade()
        self.ctx.action_manager.outstanding_request = None
        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE

    @staticmethod
    def translate_action_to_index(action: ActionCoord):
        # Because this request uses play card action, action[0] ranges [0, MAX_HAND_SIZE) and action[1] ranges
        # [0, ACTION_1_LEN). This lets us use the whole MAX_HAND_SIZE * ACTION_1_LEN space for indexing.
        return action[0] * ACTION_1_LEN + action[1]

    @staticmethod
    def translate_index_to_action(i: int) -> ActionCoord:
        big = i // ACTION_1_LEN
        small = i % ACTION_1_LEN
        return big, small


class CombatActionRequest(PlayerRequest):
    def generate_action_mask(self) -> ActionMask:
        end_turn_slice = [[False] * MAX_NUM_MONSTERS_IN_GROUP + [True]]
        play_card_slices = []
        for card_index in range(MAX_HAND_SIZE):
            card_slice = []
            if card_index < len(self.ctx.player.hand):
                card = self.ctx.player.hand[card_index]
                for monster_index in range(MAX_NUM_MONSTERS_IN_GROUP):
                    if monster_index < len(self.ctx.d.get_curr_room().monster_group):
                        monster = self.ctx.d.get_curr_room().monster_group[
                            monster_index
                        ]
                        card_slice.append(card.can_use(monster))
                    else:
                        card_slice.append(False)

                # This is for using the card without a target
                card_slice.append(card.can_use(None))

            else:
                card_slice = [False] * (MAX_NUM_MONSTERS_IN_GROUP + 1)

            play_card_slices.append(card_slice)

        # TODO unusable potions like fairy bottle
        use_potion_slices = []
        discard_potion_slices = []
        for potion_index in range(MAX_POTION_SLOTS):
            if potion_index < len(self.ctx.player.potions):
                potion = self.ctx.player.potions[potion_index]
                discard_potion_slice = [False] * MAX_NUM_MONSTERS_IN_GROUP + [
                    potion.can_discard()
                ]
                if potion.target_required:
                    use_potion_slice = [
                        i < len(self.ctx.d.get_curr_room().monster_group)
                        for i in range(MAX_NUM_MONSTERS_IN_GROUP)
                    ] + [False]
                else:
                    use_potion_slice = [False] * MAX_NUM_MONSTERS_IN_GROUP + [True]
            else:
                discard_potion_slice = [False] * (MAX_NUM_MONSTERS_IN_GROUP + 1)
                use_potion_slice = [False] * (MAX_NUM_MONSTERS_IN_GROUP + 1)

            use_potion_slices.append(use_potion_slice)
            discard_potion_slices.append(discard_potion_slice)

        return ActionMask(
            play_card_slices, end_turn_slice, use_potion_slices, discard_potion_slices
        )

    def handle_end_turn_action(self, action: ActionCoord):
        # request = self.ctx.action_manager.outstanding_request
        # assert not request
        # self.ctx.action_manager.end_turn()
        # assert not self.ctx.action_manager.outstanding_request
        # This mirrors EndTurnButton#disable
        self.ctx.action_manager.add_to_bottom(NewQueueCardAction(self.ctx))

        # EndTurnButton#disable sets AbstractPlayer#endTurnQueued, which is read in AbstractPlayer#updateInput to set
        # AbstractPlayer#isEndingTurn, which is read by AbstractRoom#update to call AbstractRoom#endTurn.
        self.ctx.player.end_turn_queued = True

        # Not sure this is correct
        self.ctx.action_manager.outstanding_request = None

    def handle_play_card_action(self, action: ActionCoord):
        self.with_optional_target_index(self._handle_play_card_action_impl)(action)
        # Not sure this is correct
        self.ctx.action_manager.outstanding_request = None

    def _handle_play_card_action_impl(
        self, card_index: int, target_index: Optional[int]
    ):
        card = self.ctx.player.hand[card_index]
        target = (
            None
            if target_index is None
            else self.ctx.d.get_curr_room().monster_group[target_index]
        )
        self.ctx.action_manager.card_queue.appendleft(
            CardQueueItem(
                card, target, self.ctx.player.energy_manager.player_current_energy
            )
        )

    def handle_use_potion_action(self, action: ActionCoord):
        self.with_optional_target_index(self._handle_use_potion_impl)(action)

    def _handle_use_potion_impl(self, potion_index: int, target_index: Optional[int]):
        assert potion_index < len(self.ctx.player.potions)
        potion = self.ctx.player.potions[potion_index]
        assert potion
        target = (
            None
            if target_index is None
            else self.ctx.d.get_curr_room().monster_group[target_index]
        )
        logger.debug(f"Using {potion} on {target.name if target else target}")
        potion.use(target)
        logger.debug(f"Destroying {potion} after use")
        self.ctx.player.potions.remove(potion)
        self.ctx.action_manager.outstanding_request = None

    def handle_destroy_potion_action(self, action: ActionCoord):
        self.with_no_target_index(self._handle_discard_potion_impl)(action)

    def _handle_discard_potion_impl(self, potion_index: int):
        assert potion_index < len(self.ctx.player.potions)
        potion = self.ctx.player.potions[potion_index]
        assert potion
        logger.debug(f"Discarding {potion}")
        self.ctx.player.potions.remove(potion)
        self.ctx.action_manager.outstanding_request = None


class ActionManager:
    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self.next_combat_actions: List[Action] = []
        # self.card_queue_item: Optional[CardQueueItem] = None

        # These deques order differently from the ArrayLists in source for efficiency/semantics's sake. Be careful.
        self.actions: Deque[Action] = deque()
        self.pre_turn_actions: Deque[Action] = deque()
        self.monster_queue: Deque[Monster] = deque()
        self.card_queue: Deque[CardQueueItem] = deque()

        self.monster_attacks_queued: bool = True
        self.turn_has_ended: bool = False
        self.turn_count: int = 0
        self.step_count: int = 0
        self._outstanding_request: Optional[PlayerRequest] = None
        # TODO BUG This never gets reset
        self.total_discarded_this_turn = 0
        self.phase = self.Phase.WAITING_ON_USER
        self.current_action: Optional[Action] = None
        self.using_card = False
        self.has_control = True

    class Phase(Enum):
        WAITING_ON_USER = 0
        EXECUTING_ACTIONS = 1

    # @property
    # def outstanding_request(self):
    #     return self._outstanding_request
    #
    # @outstanding_request.setter
    # def outstanding_request(self, new_request: PlayerRequest):
    #     assert bool(new_request) != bool(self._outstanding_request)
    #     self._outstanding_request = new_request

    def update(self) -> bool:
        # logger.debug(f'{self.phase=}')
        if self.phase == self.Phase.WAITING_ON_USER:
            did_something = self._get_next_action()

        elif self.phase == self.Phase.EXECUTING_ACTIONS:
            if self.current_action:
                # In source this is an update call
                self.current_action.act()
                self.current_action = None
                did_something = True
            else:
                # This seems like a no-op
                # self.current_action = None
                did_something = self._get_next_action()
                if (
                    not self.current_action
                    and self.ctx.d.get_curr_room().phase == RoomPhase.COMBAT
                    and not self.using_card
                ):
                    self.phase = self.Phase.WAITING_ON_USER
                    self.ctx.player.hand.refresh_hand_layout()
                    self.has_control = False

                self.using_card = False

        else:
            raise ValueError(self.phase)

        return did_something

    def _get_next_action(self) -> bool:  # noqa: C901

        if len(self.actions) > 0:
            action = self.actions.pop()
            logger.debug(f"Popped action ({len(self.actions)} remain): {action}")
            self.current_action = action
            self.phase = self.Phase.EXECUTING_ACTIONS
            self.has_control = True
            # action.act()

        elif len(self.pre_turn_actions) > 0:
            action = self.pre_turn_actions.pop()
            logger.debug(
                f"Popped pre-turn action ({len(self.pre_turn_actions)}) remain): {action}"
            )
            self.current_action = action
            self.phase = self.Phase.EXECUTING_ACTIONS
            self.has_control = True
            # action.act()

        elif len(self.card_queue) > 0:
            # TODO lots more here in source: autoplay, randomtarget, unceasing top
            self.using_card = True
            cqi = self.card_queue[-1]

            card = cqi.card
            logger.debug(f"Playing card queue item: {cqi}")

            if card is None:
                logger.debug('Got "end of turn" CardQueueItem')
                self._call_end_of_turn_actions()

            can_play_card = False
            if card is not None:
                card.is_in_autoplay = cqi.autoplay_card

                if cqi.random_target:
                    raise NotImplementedError()

            # TODO lots more here in source: autoplay, randomtarget, unceasing top

            if card is None:
                logger.debug(f"Skipping usual card play logic because {card=}")
            elif not card.can_use(cqi.monster) and not card.dont_trigger_on_use_card:
                # I think source pops up an "I can't play this card bubble" if this happens
                logger.warning("Bad state?")
                raise Exception()
            else:
                can_play_card = True
                if card.free_to_play():
                    card.free_to_play_once = True

                card.energy_on_use = cqi.energy_on_use
                if card.is_in_autoplay:
                    card.ignore_energy_on_use = True
                else:
                    card.ignore_energy_on_use = cqi.ignore_energy_total

                if not card.dont_trigger_on_use_card:
                    for p in self.ctx.player.powers:
                        p.on_play_card(card, cqi.monster)

                    for m in self.ctx.d.get_curr_room().monster_group:
                        for p in m.powers:
                            p.on_play_card(card, cqi.monster)

                    for r in self.ctx.player.relics:
                        r.on_play_card(card, cqi.monster)

                    # TODO stance, blight

                    for c in flatten(
                        [
                            self.ctx.player.hand,
                            self.ctx.player.discard_pile,
                            self.ctx.player.draw_pile,
                        ]
                    ):
                        c.on_play_card(card, cqi.monster)

                # Source checks it, but with an if, not assert
                assert card is not None

                # Source does a last second usability check?
                # What about SELF_AND_ENEMY?
                assert card.card_target != CardTarget.ENEMY or (
                    cqi.monster is not None and not cqi.monster.is_dead_or_escaped()
                )

                self.ctx.player.use_card(cqi)
                # Source has a "if can't play card" branch here, but I'm not sure it matters given all the asserts here.

            # See if anything has changed the card queue before removing this CQI from it
            assert cqi is self.card_queue[-1]
            self.card_queue.pop()

            if not can_play_card and card is not None and card.is_in_autoplay:
                card.dont_trigger_on_use_card = True
                self.add_to_bottom(UseCardAction(self.ctx, card, None))
                # I want to see when this happens
                assert False

        elif not self.monster_attacks_queued:
            logger.debug("Enqueuing monsters")
            self.monster_attacks_queued = True
            if not self.ctx.d.get_curr_room().skip_monster_turn:
                for m in self.ctx.d.get_curr_room().monster_group:
                    if not m.is_dead:
                        self.monster_queue.append(m)

        elif len(self.monster_queue) > 0:
            monster = self.monster_queue[-1]
            if not monster.is_dead_or_escaped() or monster.half_dead:
                logger.debug(f"Monster taking turn: {monster.name}")
                monster.take_turn()
                monster.apply_turn_powers()
            else:
                logger.debug(f"Skipping monster turn: {monster.name}")

            self.monster_queue.pop()

        elif (
            self.turn_has_ended
            and not self.ctx.d.get_curr_room().monster_group.are_monsters_dead()
        ):
            self.turn_count += 1
            logger.debug(
                f"Monster turn over, incremented turn count: {self.turn_count}"
            )
            if not self.ctx.d.get_curr_room().skip_monster_turn:
                self.ctx.d.get_curr_room().monster_group.apply_end_of_turn_powers()

            self.ctx.player.apply_start_of_turn_relics()
            self.ctx.player.apply_start_of_turn_pre_draw_cards()
            self.ctx.player.apply_start_of_turn_cards()
            self.ctx.player.apply_start_of_turn_powers()
            # TODO orb

            self.ctx.d.get_curr_room().skip_monster_turn = False
            self.turn_has_ended = False

            # Player loses block at end of monster turn
            # TODO Barricade, Blur, Calipers will hook in here
            self.ctx.player.lose_block()

            # Source checks this with an if. I suspect my terminal detection hits before this, so let's assert and see.
            assert not self.ctx.d.get_curr_room().is_battle_over
            self.add_to_bottom(
                DrawCardAction(
                    self.ctx, self.ctx.player.game_hand_size, end_turn_draw=True
                )
            )
            self.ctx.player.apply_start_of_turn_post_draw_relics()
            self.ctx.player.apply_start_of_turn_post_draw_powers()

        else:
            # logger.debug('Step returns false')
            return False

        # logger.debug('Step returns true')
        return True

    def end_turn(self):
        logger.debug("End turn called")
        self.turn_has_ended = True

    def add_to_top(self, action: Action):
        logger.debug(f"Adding action to top: {action}")
        self.actions.append(action)

    def add_to_bottom(self, action: Action):
        logger.debug(f"Adding action to bottom: {action}")
        self.actions.appendleft(action)

    def use_next_combat_actions(self):
        for a in self.next_combat_actions:
            self.add_to_bottom(a)
        self.next_combat_actions.clear()

    def clean_card_queue(self):
        # This may not work right, depends on default equality working the same as in source
        cqis_to_remove = [
            cqi for cqi in self.card_queue if cqi.card in self.ctx.player.hand
        ]
        for cqi in cqis_to_remove:
            logger.debug(f"Clearing card queue item {cqi}")
            self.card_queue.remove(cqi)

        # if self.card_queue_item and self.card_queue_item.card in self.ctx.player.hand:
        #     logger.debug(f'Removing next card intended for play: {self.card_queue_item.card}')
        #     self.card_queue_item = None

        # Source does limbo stuff, don't think we need to.

    def add_to_turn_start(self, action: Action):
        # Source checks room is combat here
        self.pre_turn_actions.append(action)

    def increment_discard(self, end_of_turn: bool):
        self.total_discarded_this_turn += 1
        if not self.ctx.action_manager.turn_has_ended and not end_of_turn:
            self.ctx.player.update_cards_on_discard()

            for r in self.ctx.player.relics:
                r.on_manual_discard()

    def clear_post_combat_actions(self):
        logger.debug("Clearing post combat actions")
        # TODO include HealAction
        actions_to_remove = [
            a
            for a in self.actions
            if not isinstance(a, (GainBlockAction, UseCardAction))
            and a.action_type != ActionType.DAMAGE
        ]
        for a in actions_to_remove:
            logger.debug(f"Removing from actions: {a}")
            self.actions.remove(a)

    @property
    def outstanding_request(self):
        return self._outstanding_request

    @outstanding_request.setter
    def outstanding_request(self, r):
        logger.debug(f"Setting request to {r}")
        if bool(r) == bool(self._outstanding_request):
            logger.error(f"Request was already {self._outstanding_request}")
            raise ValueError(r)
        self._outstanding_request = r

    def _call_end_of_turn_actions(self):
        self.ctx.d.get_curr_room().apply_end_of_turn_relics()
        self.ctx.d.get_curr_room().apply_end_of_turn_pre_card_powers()
        # orb

        for c in self.ctx.player.hand:
            c.trigger_on_end_of_turn_for_playing_card()
        # stance

    def clear(self):
        self.actions.clear()
        self.pre_turn_actions.clear()
        self.current_action = None
        self.card_queue.clear()
        self.turn_has_ended = False
        self.turn_count = 1
        self.phase = self.Phase.WAITING_ON_USER
        # There's more in source, but mostly orb, stance, metrics


class CardType(Enum):
    ATTACK = 0
    SKILL = 1
    POWER = 2
    STATUS = 3
    CURSE = 4


class CardTarget(Enum):
    # Backstab, Strike
    ENEMY = 0
    # Die Die Die, All Out Attack
    ALL_ENEMY = 1
    # Accuracy, Alchemize
    SELF = 2
    # Blade Dance, Nightmare
    NONE = 3
    # Spot Weakness (this one appears rare, no green cards)
    SELF_AND_ENEMY = 4
    # Vault (also rare, no green cards)
    ALL = 5


class CardRarity(Enum):
    BASIC = 0
    SPECIAL = 1
    COMMON = 2
    UNCOMMON = 3
    RARE = 4
    CURSE = 5


class CardColor(Enum):
    RED = 0
    GREEN = 1
    BLUE = 2
    PURPLE = 3
    COLORLESS = 4
    CURSE = 5


class Card(ABC):
    base_damage_master = None
    base_block_master = None
    base_magic_number_master = None
    damage_upgrade_amount = None
    block_upgrade_amount = None
    magic_number_upgrade_amount = None
    upgraded_base_cost = None
    rarity: CardRarity = None
    color: CardColor = None

    def __init__(
        self,
        ctx: CCG.Context,
        cost: int,
        card_type: CardType,
        card_target: CardTarget,
        exhaust=False,
        damage_type: DamageType = DamageType.NORMAL,
        is_innate: bool = False,
        is_multi_damage: bool = False,
        self_retain: bool = False,
        is_ethereal: bool = False,
    ):
        self.ctx = ctx
        self.card_type = card_type
        self.card_target = card_target
        self.base_damage: Optional[int] = self.base_damage_master
        # This is calculated per invocation
        self.damage: Optional[int] = self.base_damage
        self.base_block: Optional[int] = self.base_block_master
        self.block: Optional[int] = self.base_block
        # Sentinel values:
        # -2 means unplayable curse/status
        # -1 might mean X cost
        # >= 0 is as it looks
        self.cost: int = cost
        self.cost_for_turn: int = cost
        self.energy_on_use: Optional[int] = None
        self.exhaust: bool = exhaust
        self.exhaust_on_use_once: bool = False
        # Source also has "damage type per turn", but I don't see it ever getting written as anything but "damage type".
        # self.damage_type_for_turn = None
        self.damage_type: DamageType = damage_type
        self.ignore_energy_on_use: bool = False
        self.is_in_autoplay: bool = False
        self.free_to_play_once: bool = False
        self.dont_trigger_on_use_card = False
        self.uuid: uuid.UUID = uuid.uuid4()
        self.base_magic_number: Optional[int] = self.base_magic_number_master
        self.magic_number: Optional[int] = self.base_magic_number
        self.is_innate: bool = is_innate
        self.in_bottle_flame: bool = False
        self.in_bottle_lightning: bool = False
        self.in_bottle_tornado: bool = False
        self.is_multi_damage = is_multi_damage
        self.multi_damage: Optional[List[int]] = None
        self.times_upgraded = 0
        self.self_retain = self_retain
        self.retain = False
        self.is_ethereal = is_ethereal

    def __repr__(self):
        card_name_short, card_attr = self._repr_impl()
        card_repr = f'{card_name_short}{f" {card_attr}" if card_attr else ""}'
        return f'{card_repr}{"+" if self.upgraded else ""} ({str(self.uuid)[0:3]})'

    @abstractmethod
    def _repr_impl(self) -> Tuple[str, Any]:
        """Returns a string repr of the card name and the most relevant stat to append."""
        ...

    @abstractmethod
    def use(self, monster: Optional[Monster]):
        ...

    @property
    def upgraded(self):
        return self.times_upgraded > 0

    @classmethod
    def recipe(
        cls, upgraded=False, bottle=False, *args, **kwargs
    ) -> Callable[[CCG.Context], Card]:
        def f(ctx: CCG.Context):
            # noinspection PyArgumentList
            c = cls(ctx, *args, **kwargs)
            if upgraded:
                c.upgrade()
            if bottle:
                if c.card_type == CardType.ATTACK:
                    c.in_bottle_flame = True
                elif c.card_type == CardType.SKILL:
                    c.in_bottle_lightning = True
                elif c.card_type == CardType.POWER:
                    c.in_bottle_tornado = True
                else:
                    raise ValueError(c.card_type)
            return c

        return f

    @final
    def add_to_bottom(self, action: Action):
        self.ctx.action_manager.add_to_bottom(action)

    @final
    def add_to_top(self, action: Action):
        self.ctx.action_manager.add_to_top(action)

    def get_typical_damage_info(self):
        assert self.damage is not None
        return DamageInfo(self.ctx.player, self.damage)

    @classmethod
    def as_upgraded(cls):
        # noinspection PyArgumentList
        c = cls()
        c.upgrade()
        return c

    @final
    def upgrade(self):
        if not self.upgraded:
            self.upgrade_name()

            # Do the common upgrade operations here.
            if self.damage_upgrade_amount is not None:
                self.upgrade_damage(self.damage_upgrade_amount)
            if self.block_upgrade_amount is not None:
                self.upgrade_block(self.block_upgrade_amount)
            if self.magic_number_upgrade_amount is not None:
                self.upgrade_magic_number(self.magic_number_upgrade_amount)
            if self.upgraded_base_cost is not None:
                self.upgrade_base_cost(self.upgraded_base_cost)

            self.upgrade_impl()

    def upgrade_impl(self):
        ...

    @final
    def upgrade_name(self):
        self.times_upgraded += 1

    def upgrade_damage(self, diff: int):
        new_base_damage = self.base_damage + diff
        logger.debug(f"Upgrade {self} damage {self.base_damage} -> {new_base_damage}")
        self.base_damage = new_base_damage

    def upgrade_block(self, diff: int):
        new_base_block = self.base_block + diff
        logger.debug(f"Upgrade {self} block {self.base_block} -> {new_base_block}")
        self.base_block = new_base_block

    def upgrade_magic_number(self, diff: int):
        new_base_magic_number = self.base_magic_number + diff
        logger.debug(
            f"Upgrade {self} magic number {self.base_magic_number} -> {new_base_magic_number}"
        )
        self.base_magic_number = new_base_magic_number
        self.magic_number = self.base_magic_number

    def upgrade_base_cost(self, new_base_cost: int):
        old_base_cost = self.cost_for_turn
        diff = self.cost_for_turn - self.cost
        self.cost = new_base_cost
        if self.cost_for_turn > 0:
            self.cost_for_turn = self.cost + diff
        self.cost_for_turn = max(0, self.cost_for_turn)
        logger.debug(
            f"Upgrade {self} base cost {old_base_cost} -> {self.cost_for_turn}"
        )

    def apply_powers(self):
        self._apply_powers_to_block()

        # This if isn't in source, might be wrong.
        if not self.base_damage:
            return

        if not self.is_multi_damage:
            running_damage = float(self.base_damage)

            for r in self.ctx.player.relics:
                running_damage = r.at_damage_modify(running_damage, self)

            for p in self.ctx.player.powers:
                running_damage = p.at_damage_give(
                    running_damage, self.damage_type, self
                )

            for p in self.ctx.player.powers:
                running_damage = p.at_damage_final_give(
                    running_damage, self.damage_type
                )

            self.damage = max(0, int(running_damage))
        else:
            running_damages = [float(self.base_damage)] * len(
                self.ctx.d.get_curr_room().monster_group
            )

            for i in range(len(running_damages)):
                for r in self.ctx.player.relics:
                    running_damages[i] = r.at_damage_modify(running_damages[i], self)

                for p in self.ctx.player.powers:
                    running_damages[i] = p.at_damage_give(
                        running_damages[i], self.damage_type, self
                    )

            for i in range(len(running_damages)):
                for p in self.ctx.player.powers:
                    running_damages[i] = p.at_damage_final_give(
                        running_damages[i], self.damage_type
                    )

            self.multi_damage = [
                max(0, int(running_damage)) for running_damage in running_damages
            ]
            self.damage = self.multi_damage[0]

    def calculate_card_damage(self, monster: Optional[Monster] = None):  # noqa: C901
        self._apply_powers_to_block()
        if not self.base_damage:
            return

        if not self.is_multi_damage and monster:
            running_damage = float(self.base_damage)

            for r in self.ctx.player.relics:
                running_damage = r.at_damage_modify(running_damage, self)

            for p in self.ctx.player.powers:
                running_damage = p.at_damage_give(
                    running_damage, self.damage_type, self
                )

            for p in monster.powers:
                running_damage = p.at_damage_receive(running_damage, self.damage_type)

            for p in self.ctx.player.powers:
                running_damage = p.at_damage_final_give(
                    running_damage, self.damage_type
                )

            for p in monster.powers:
                running_damage = p.at_damage_final_receive(
                    running_damage, self.damage_type
                )

            self.damage = max(0, int(running_damage))

        else:
            running_damages = [float(self.base_damage)] * len(
                self.ctx.d.get_curr_room().monster_group
            )

            for i in range(len(running_damages)):
                for r in self.ctx.player.relics:
                    running_damages[i] = r.at_damage_modify(running_damages[i], self)

                for p in self.ctx.player.powers:
                    running_damages[i] = p.at_damage_give(
                        running_damages[i], self.damage_type, self
                    )

            for i in range(len(running_damages)):
                m = self.ctx.d.get_curr_room().monster_group[i]
                for p in m.powers:
                    if not m.is_dying and not m.is_escaping:
                        running_damages[i] = p.at_damage_receive(
                            running_damages[i], self.damage_type
                        )

            for i in range(len(running_damages)):
                for p in self.ctx.player.powers:
                    running_damages[i] = p.at_damage_final_give(
                        running_damages[i], self.damage_type
                    )

            for i in range(len(running_damages)):
                m = self.ctx.d.get_curr_room().monster_group[i]
                for p in m.powers:
                    if not m.is_dying and not m.is_escaping:
                        running_damages[i] = p.at_damage_final_receive(
                            running_damages[i], self.damage_type
                        )

            self.multi_damage = [
                max(0, int(running_damage)) for running_damage in running_damages
            ]

            self.damage = self.multi_damage[0]

    def _apply_powers_to_block(self):
        # Probably complete
        if self.base_block:
            running_block = float(self.base_block)
            for p in self.ctx.player.powers:
                running_block = p.modify_block(running_block)

            for p in self.ctx.player.powers:
                running_block = p.modify_block_last(running_block)

            running_block = max(0.0, running_block)
            self.block = int(running_block)

    @classmethod
    def make_copy(cls, ctx: CCG.Context) -> Card:
        """Returns a new instance of this card with default values and different UUID."""
        # Source does this by having each instance return itself. This seems easier.
        # noinspection PyArgumentList
        return cls(ctx)

    def make_stat_equivalent_copy(self) -> Card:
        """Returns a new instance of this card with same values but different UUID."""
        # Source does this manually. Deep copy might not work in some corner cases.
        the_copy = copy.copy(self)
        # the_copy.ctx = self.ctx
        if self.multi_damage is not None:
            # Pretty sure this is the only thing that needs deep copy
            logger.debug(
                f"copy {id(the_copy.multi_damage)} self {id(self.multi_damage)}"
            )
            assert the_copy.multi_damage is self.multi_damage
            the_copy.multi_damage = copy.deepcopy(self.multi_damage)
            logger.debug(
                f"copy {id(the_copy.multi_damage)} self {id(self.multi_damage)}"
            )
            assert the_copy.multi_damage is not self.multi_damage

        assert the_copy.ctx is self.ctx
        the_copy.uuid = uuid.uuid4()
        return the_copy

    def make_same_instance_of(self) -> Card:
        """Returns a new instance of this card with same values and same UUID."""
        c = self.make_stat_equivalent_copy()
        c.uuid = self.uuid
        return c

    def can_use(self, monster: Optional[Monster]):
        # TODO medical kit, blue candle
        if self.card_type == CardType.STATUS and self.cost_for_turn < -1:
            return False
        if self.card_type == CardType.CURSE and self.cost_for_turn < -1:
            return False

        return self.card_playable(monster) and self.has_enough_energy()

    def card_playable(self, monster: Optional[Monster]):
        # The card is playable if:
        #   it doesn't need a target,
        #     or if this invocation of the card doesn't specify a target
        #     or if this invocation of the card targets a monster that isn't dying
        #   and not all monsters are dead
        # return monster is not None

        # Yes, this method is way longer than necessary, but the condensed form broke my brain for two hours, so deal.

        if self.card_target not in [CardTarget.ENEMY, CardTarget.SELF_AND_ENEMY]:
            # Source doesn't check this, but if we don't, cards like Defend can be played with a target.
            if monster is None:
                return (
                    not self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead()
                )
            else:
                return False

        # At this point, card needs a target
        if monster is None:
            return False

        # At this point, card needs a target and has one
        if monster.is_dying:
            return False

        # Source doesn't check this, probably because escaped monsters aren't selectable from UI
        if monster.is_escaping:
            return False

        # At this point, card needs and has a live target
        return (
            not self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead()
        )

    def has_enough_energy(self):
        # Source checks actionmanager.turnhasended here, but that seems unnecessary.
        assert not self.ctx.action_manager.turn_has_ended

        if (
            self.ctx.player.has_power(EntangledPower)
            and self.card_type == CardType.ATTACK
        ):
            return False

        if (
            not all((p.can_play_card(self) for p in self.ctx.player.powers))
            or not all((r.can_play(self) for r in self.ctx.player.relics))
            or not all((c.can_play(self) for c in self.ctx.player.hand))
        ):
            return False

        return (
            self.ctx.player.energy_manager.player_current_energy >= self.cost_for_turn
            or self.free_to_play()
            or self.is_in_autoplay
        )

    def at_turn_start(self):
        ...

    def trigger_on_gain_energy(self, e: int, due_to_card: bool):
        ...

    def trigger_on_manual_discard(self):
        ...

    def trigger_on_card_played(self, card: Card):
        ...

    def on_remove_from_master_deck(self):
        ...

    def clear_powers(self):
        # Probably complete
        self.reset_attributes()

    def reset_attributes(self):
        # Probably complete
        self.block = self.base_block
        self.damage = self.base_damage
        self.magic_number = self.base_magic_number
        self.cost_for_turn = self.cost

    def trigger_on_other_card_played(self, used_card: Card):
        ...

    def free_to_play(self):
        # TODO implement
        return False

    def took_damage(self):
        ...

    def did_discard(self):
        ...

    def on_retained(self):
        ...

    def trigger_on_end_of_player_turn(self):
        if self.is_ethereal:
            self.add_to_top(
                ExhaustSpecificCardAction(self.ctx, self, self.ctx.player.hand)
            )

    def trigger_on_end_of_turn_for_playing_card(self):
        pass

    def can_play(self, other: Card):
        return True

    def on_play_card(self, card: Card, monster: Monster):
        ...

    def at_turn_start_pre_draw(self):
        ...

    def can_upgrade(self):
        return (
            self.card_type != CardType.CURSE
            and self.card_type != CardType.STATUS
            and not self.upgraded
        )

    def trigger_on_exhaust(self):
        pass

    def trigger_when_copied(self):
        pass


class Strike(Card):
    base_damage_master = 6
    damage_upgrade_amount = 3
    rarity = CardRarity.BASIC
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self):
        return "Strk", self.base_damage

    def use(self, monster):
        self.add_to_bottom(
            DamageAction(
                self.ctx,
                monster,
                DamageInfo(self.ctx.player, self.damage, DamageType.NORMAL),
                self.ctx.player,
            )
        )


class DebugStrike(Card):
    damage_upgrade_amount = 3
    rarity = CardRarity.BASIC
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context, damage: int = 999):
        super().__init__(ctx, 0, CardType.ATTACK, CardTarget.ENEMY)
        self.base_damage = damage

    def _repr_impl(self):
        return "DbgS", self.base_damage

    def use(self, monster):
        self.add_to_bottom(
            DamageAction(
                self.ctx,
                monster,
                DamageInfo(self.ctx.player, self.damage, DamageType.NORMAL),
                self.ctx.player,
            )
        )


class Defend(Card):
    base_block_master = 5
    block_upgrade_amount = 3
    rarity = CardRarity.BASIC
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.SELF)

    def _repr_impl(self):
        return "Def", self.block

    def use(self, monster):
        self.add_to_bottom(GainBlockAction(self.ctx, self.ctx.player, self.block))


class Backstab(Card):
    damage_upgrade_amount = 4
    rarity = CardRarity.UNCOMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(
            ctx, 0, CardType.ATTACK, CardTarget.ENEMY, exhaust=True, is_innate=True
        )
        self.base_damage = 11

    def _repr_impl(self):
        return "Bkstb", self.damage

    def use(self, monster):
        self.add_to_bottom(
            DamageAction(
                self.ctx,
                monster,
                DamageInfo(self.ctx.player, self.damage, DamageType.NORMAL),
                self.ctx.player,
            )
        )


class Footwork(Card):
    base_magic_number_master = 2
    magic_number_upgrade_amount = 1
    rarity = CardRarity.UNCOMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.POWER, CardTarget.SELF)

    def _repr_impl(self):
        return "Ftw", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                self.ctx.player,
                DexterityPower(self.ctx, self.ctx.player, self.magic_number),
            )
        )


class Survivor(Card):
    block_upgrade_amount = 3
    rarity = CardRarity.BASIC
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.SELF)
        self.base_block = 8

    def _repr_impl(self):
        return "Srvr", self.block

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(GainBlockAction(self.ctx, self.ctx.player, self.block))
        self.add_to_bottom(DiscardAction(self.ctx, is_random=False, amount=1))


class Slimed(Card):
    rarity = CardRarity.COMMON
    color = CardColor.COLORLESS

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.STATUS, CardTarget.SELF, exhaust=True)

    def _repr_impl(self):
        return "Slmd", None

    def use(self, monster: Optional[Monster]):
        ...


class Neutralize(Card):
    base_damage_master = 3
    damage_upgrade_amount = 1
    base_magic_number_master = 1
    magic_number_upgrade_amount = 1
    rarity = CardRarity.BASIC
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Neu", self.damage

    def use(self, monster: Optional[Monster]):
        assert monster
        self.add_to_bottom(
            DamageAction(
                self.ctx,
                monster,
                DamageInfo(self.ctx.player, self.damage, self.damage_type),
                self.ctx.player,
            )
        )
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                monster,
                self.ctx.player,
                WeakPower(self.ctx, monster, self.magic_number, False),
            )
        )


class Alchemize(Card):
    upgraded_base_cost = 0
    rarity = CardRarity.RARE
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.SELF, exhaust=True)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Alc", None

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            ObtainPotionAction(self.ctx, self.ctx.d.return_random_potion(True))
        )


class Concentrate(Card):
    magic_number_upgrade_amount = -1
    rarity = CardRarity.UNCOMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, CardType.SKILL, CardTarget.SELF)
        self.base_magic_number = 3
        self.magic_number = self.base_magic_number

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Conc", None

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DiscardAction(self.ctx, is_random=False, amount=self.magic_number)
        )
        self.add_to_bottom(GainEnergyAction(self.ctx, 2))


class AllOutAttack(Card):
    base_damage_master = 10
    damage_upgrade_amount = 4
    rarity = CardRarity.UNCOMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(
            ctx, 1, CardType.ATTACK, CardTarget.ALL_ENEMY, is_multi_damage=True
        )

    def _repr_impl(self) -> Tuple[str, Any]:
        return "AOA", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAllEnemiesAction(
                self.ctx, self.multi_damage, self.damage_type, self.ctx.player
            )
        )
        self.add_to_bottom(DiscardAction(self.ctx, is_random=True, amount=1))


class Wound(Card):
    rarity = CardRarity.COMMON
    color = CardColor.COLORLESS

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -2, CardType.STATUS, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Woun", None

    def use(self, monster: Optional[Monster]):
        ...


class Smite(Card):
    damage_upgrade_amount = 4
    rarity = CardRarity.SPECIAL
    color = CardColor.COLORLESS

    def __init__(self, ctx: CCG.Context):
        super().__init__(
            ctx, 1, CardType.ATTACK, CardTarget.ENEMY, exhaust=True, self_retain=True
        )
        self.base_damage = 12

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Smte", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx,
                monster,
                DamageInfo(self.ctx.player, self.damage),
                self.ctx.player,
            )
        )


class Skewer(Card):
    damage_upgrade_amount = 3
    rarity = CardRarity.UNCOMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -1, CardType.ATTACK, CardTarget.ENEMY)
        self.base_damage = 7

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Skwr", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            SkewerAction(
                self.ctx,
                monster,
                self.damage,
                self.free_to_play_once,
                self.damage_type,
                self.energy_on_use,
            )
        )


class GlassKnife(Card):
    damage_upgrade_amount = 4
    base_damage_master = 8
    base_damage_change_per_use = -2
    rarity = CardRarity.RARE
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -1, CardType.ATTACK, CardTarget.ENEMY)
        self.base_damage = self.base_damage_master

    def _repr_impl(self) -> Tuple[str, Any]:
        return "GKni", self.damage

    def use(self, monster: Optional[Monster]):
        for _ in range(2):
            self.add_to_bottom(
                DamageAction(
                    self.ctx,
                    monster,
                    DamageInfo(self.ctx.player, self.damage, self.damage_type),
                    self.ctx.player,
                )
            )
        self.add_to_bottom(
            ModifyDamageAction(self.ctx, self.uuid, self.base_damage_change_per_use)
        )


class AscendersBane(Card):
    rarity = CardRarity.SPECIAL
    color = CardColor.CURSE

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -2, CardType.CURSE, CardTarget.NONE, is_ethereal=True)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "AscB", None

    def use(self, monster: Optional[Monster]):
        pass


class Acrobatics(Card):
    base_magic_number_master = 3
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Acro", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(DrawCardAction(self.ctx, self.magic_number))
        self.add_to_bottom(DiscardAction(self.ctx, is_random=False, amount=1))


class Backflip(Card):
    base_block_master = 5
    block_upgrade_amount = 3
    draw_amount = 2
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.SELF)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Bkfl", self.block

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(GainBlockAction(self.ctx, self.ctx.player, self.block))
        self.add_to_bottom(DrawCardAction(self.ctx, self.draw_amount))


class Bane(Card):
    base_damage_master = 7
    damage_upgrade_amount = 3
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Bane", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(
            BaneAction(self.ctx, monster, self.get_typical_damage_info())
        )


class DeadlyPoison(Card):
    base_magic_number_master = 5
    magic_number_upgrade_amount = 2
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "DPoi", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                monster,
                self.ctx.player,
                PoisonPower(self.ctx, monster, self.ctx.player, self.magic_number),
            )
        )


class Regret(Card):
    rarity = CardRarity.CURSE
    color = CardColor.CURSE

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -2, CardType.CURSE, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Rgrt", None

    def use(self, monster: Optional[Monster]):
        if self.dont_trigger_on_use_card:
            self.add_to_top(
                LoseHPAction(
                    self.ctx, self.ctx.player, self.ctx.player, self.magic_number
                )
            )

    def trigger_on_end_of_turn_for_playing_card(self):
        self.dont_trigger_on_use_card = True
        self.magic_number = self.base_magic_number = len(self.ctx.player.hand)
        self.ctx.action_manager.card_queue.appendleft(
            CardQueueItem(
                self,
                None,
                self.ctx.player.energy_manager.player_current_energy,
                is_end_turn_auto_play=True,
            )
        )


class BladeDance(Card):
    base_magic_number_master = 3
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "BDnc", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            MakeTempCardInHandAction(
                self.ctx,
                Shiv(
                    self.ctx,
                ),
                self.magic_number,
            )
        )


class Shiv(Card):
    base_damage_master = 4
    damage_upgrade_amount = 2
    rarity = CardRarity.SPECIAL
    color = CardColor.COLORLESS

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, CardType.ATTACK, CardTarget.ENEMY)
        # TODO accuracy

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Shiv", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx,
                monster,
                DamageInfo(self.ctx.player, self.damage, self.damage_type),
                self.ctx.player,
            )
        )


class CloakAndDagger(Card):
    base_block_master = 6
    base_magic_number_master = 1
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.SELF)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "CDgr", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(GainBlockAction(self.ctx, self.ctx.player, self.block))
        self.add_to_bottom(
            MakeTempCardInHandAction(
                self.ctx,
                Shiv(
                    self.ctx,
                ),
                self.magic_number,
            )
        )


class DaggerSpray(Card):
    base_damage_master = 4
    damage_upgrade_amount = 2
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(
            ctx, 1, CardType.ATTACK, CardTarget.ALL_ENEMY, is_multi_damage=True
        )

    def _repr_impl(self) -> Tuple[str, Any]:
        return "DSpr", self.damage

    def use(self, monster: Optional[Monster]):
        for _ in range(2):
            self.add_to_bottom(
                DamageAllEnemiesAction(
                    self.ctx, self.multi_damage, self.damage_type, self.ctx.player
                )
            )


class DaggerThrow(Card):
    base_damage_master = 9
    damage_upgrade_amount = 3
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "DThr", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(DrawCardAction(self.ctx, 1))
        self.add_to_bottom(DiscardAction(self.ctx, False, 1))


class Deflect(Card):
    base_block_master = 4
    block_upgrade_amount = 3
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, CardType.SKILL, CardTarget.SELF)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Defl", self.block

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(GainBlockAction(self.ctx, self.ctx.player, self.block))


class DodgeAndRoll(Card):
    base_block_master = 4
    block_upgrade_amount = 2
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.SELF)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "D&Rl", self.block

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(GainBlockAction(self.ctx, self.ctx.player, self.block))
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                self.ctx.player,
                NextTurnBlockPower(self.ctx, self.ctx.player, self.block),
            )
        )


class FlyingKnee(Card):
    base_damage_master = 8
    damage_upgrade_amount = 3
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "FlyK", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                self.ctx.player,
                EnergizedPower(self.ctx, self.ctx.player, 1),
            )
        )


class Outmaneuver(Card):
    base_magic_number_master = 2
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Outm", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                self.ctx.player,
                EnergizedPower(self.ctx, self.ctx.player, self.magic_number),
            )
        )


class PiercingWail(Card):
    base_magic_number_master = 6
    magic_number_upgrade_amount = 2
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.ALL_ENEMY, exhaust=True)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "PrWl", self.magic_number

    def use(self, monster: Optional[Monster]):
        for m in self.ctx.d.get_curr_room().monster_group:
            self.add_to_bottom(
                ApplyPowerAction(
                    self.ctx,
                    m,
                    self.ctx.player,
                    StrengthPower(self.ctx, m, -self.magic_number),
                )
            )
            # TODO artifact
            self.add_to_bottom(
                ApplyPowerAction(
                    self.ctx,
                    m,
                    self.ctx.player,
                    GainStrengthPower(self.ctx, m, self.magic_number),
                )
            )


class PoisonedStab(Card):
    base_damage_master = 6
    base_magic_number_master = 3
    damage_upgrade_amount = 2
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.SKILL, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "PStb", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                monster,
                self.ctx.player,
                PoisonPower(self.ctx, monster, self.ctx.player, self.magic_number),
            )
        )


class Prepared(Card):
    base_magic_number_master = 1
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, CardType.SKILL, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Prep", self.magic_number

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(DrawCardAction(self.ctx, self.magic_number))
        self.add_to_bottom(DiscardAction(self.ctx, False, self.magic_number))


class QuickSlash(Card):
    base_damage_master = 8
    base_magic_number_master = 1
    damage_upgrade_amount = 4
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "QkSl", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(DrawCardAction(self.ctx, self.magic_number))


class Slice(Card):
    base_damage_master = 6
    damage_upgrade_amount = 3
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Slce", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )


class SneakyStrike(Card):
    base_damage_master = 12
    damage_upgrade_amount = 4
    base_magic_number_master = 2
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 2, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "SStr", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(GainEnergyIfDiscardAction(self.ctx, self.magic_number))


class SuckerPunch(Card):
    base_damage_master = 7
    base_magic_number_master = 1
    damage_upgrade_amount = 2
    magic_number_upgrade_amount = 1
    rarity = CardRarity.COMMON
    color = CardColor.GREEN

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1, CardType.ATTACK, CardTarget.ENEMY)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "SkrP", self.damage

    def use(self, monster: Optional[Monster]):
        self.add_to_bottom(
            DamageAction(
                self.ctx, monster, self.get_typical_damage_info(), self.ctx.player
            )
        )
        self.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                monster,
                self.ctx.player,
                WeakPower(self.ctx, monster, self.magic_number, False),
            )
        )


class Dazed(Card):
    rarity = CardRarity.COMMON
    color = CardColor.COLORLESS

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -2, CardType.STATUS, CardTarget.NONE, is_ethereal=True)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Dazd", None

    def use(self, monster: Optional[Monster]):
        pass


class Burn(Card):
    base_magic_number_master = 2
    magic_number_upgrade_amount = 2
    rarity = CardRarity.COMMON
    color = CardColor.COLORLESS

    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, -2, CardType.STATUS, CardTarget.NONE)

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Burn", self.magic_number

    def use(self, monster: Optional[Monster]):
        if self.dont_trigger_on_use_card:
            self.add_to_bottom(
                DamageAction(
                    self.ctx,
                    self.ctx.player,
                    DamageInfo(self.ctx.player, self.magic_number, DamageType.THORNS),
                    self.ctx.player,
                )
            )

    def trigger_on_end_of_turn_for_playing_card(self):
        self.dont_trigger_on_use_card = True
        self.ctx.action_manager.card_queue.appendleft(
            CardQueueItem(
                self,
                None,
                self.ctx.player.energy_manager.player_current_energy,
                is_end_turn_auto_play=True,
            )
        )


class CurseOfTheBell(Card):
    rarity = CardRarity.SPECIAL
    color = CardColor.CURSE

    # noinspection PyMissingConstructor
    def __init__(self):
        raise NotImplementedError()

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Bell", None

    def use(self, monster: Optional[Monster]):
        pass


class Necronomicurse(Card):
    rarity = CardRarity.SPECIAL
    color = CardColor.CURSE

    # noinspection PyMissingConstructor
    def __init__(self):
        raise NotImplementedError()

    def _repr_impl(self) -> Tuple[str, Any]:
        return "Ncro", None

    def use(self, monster: Optional[Monster]):
        pass


class CardGroup:
    def __init__(
        self, ctx: CCG.Context, group_type: CardGroupType, cards: Iterable[Card] = None
    ):
        self.ctx = ctx
        if cards is None:
            cards = []
        self._ordered_cards: Deque[Card] = deque(cards)
        self.type: CardGroupType = group_type
        # assert all(type(card) in SilentCardUniverse for card in self.ordered_cards)

    def __len__(self):
        return len(self._ordered_cards)

    def __repr__(self):
        cards_repr = ", ".join(map(lambda card: card.__repr__(), self._ordered_cards))
        return f"{self.type.name:12s}: ({len(self._ordered_cards)}) < {cards_repr} >"

    def __iter__(self):
        return self._ordered_cards.__iter__()

    def __getitem__(self, item):
        return self._ordered_cards.__getitem__(item)

    def refresh_hand_layout(self):
        # TODO implement
        ...

    @staticmethod
    def explode_card_group_recipe_manifest(
        manifest: Dict[Callable[[CCG.Context], Card], int]
    ) -> List[Callable[[CCG.Context], Card]]:
        card_recipes = []
        for card_recipe, count in manifest.items():
            for _ in range(count):
                card_recipes.append(card_recipe)
        assert len(card_recipes) == sum(manifest.values())
        return card_recipes

    @staticmethod
    def hydrate_card_recipes(
        ctx: CCG.Context, card_recipes: List[Callable[[CCG.Context], Card]]
    ) -> List[Card]:
        return [cr(ctx) for cr in card_recipes]

    def add_to_top(self, card: Card):
        logger.debug(f"Adding {card} to {self.type}")
        self._ordered_cards.append(card)

    def add_to_bottom(self, card: Card):
        logger.debug(f"Adding {card} to bottom of {self.type}")
        self._ordered_cards.appendleft(card)

    def count_by_card(self) -> List[int]:
        counts = [0] * len(dts.SILENT_CARD_UNIVERSE)
        for card in self._ordered_cards:
            counts[dts.SILENT_CARD_UNIVERSE.index(type(card))] += 1
        return counts

    def shuffle(self):
        random.shuffle(self._ordered_cards)

    def pop_top_card(self):
        return self._ordered_cards.pop()

    def peek_top_card(self):
        return self._ordered_cards[-1]

    def reset_card_before_moving(self, card: Card):
        logger.debug(f"Removing {card} from {self.type}")
        self._safe_remove_card(card)
        # TODO action manager remove from queue

    def _safe_remove_card(self, card: Card):
        # My best guess is that source double removes cards sometimes and relies on java's List::remove not throwing
        # when no element to remove is found.
        try:
            self._ordered_cards.remove(card)
        except ValueError:
            logger.debug(
                f"Card {card.uuid} not found for removal (this isn't necessarily an error)"
            )

    def move_to_draw_pile(self, card: Card):
        self.reset_card_before_moving(card)

        # See notes in move_to_discard_pile
        self.ctx.player.draw_pile.add_to_top(card)
        card.clear_powers()

        self.ctx.player.on_card_draw_or_discard()

    def move_to_discard_pile(self, card: Card):
        self.reset_card_before_moving(card)

        # Source delegates this to Soul::discard, which appears to boil down to adding the card to discard pile and
        # calling clearPowers on the card if it's going to draw or discard. Removing card from hand is done by Player
        # use_card
        self.ctx.player.discard_pile.add_to_top(card)
        card.clear_powers()

        self.ctx.player.on_card_draw_or_discard()

    def move_to_exhaust_pile(self, card: Card):
        for r in self.ctx.player.relics:
            r.on_exhaust(card)

        for p in self.ctx.player.powers:
            p.on_exhaust(card)

        card.trigger_on_exhaust()
        self.reset_card_before_moving(card)

        # See notes in move_to_discard_pile
        self.ctx.player.exhaust_pile.add_to_top(card)

        self.ctx.player.on_card_draw_or_discard()

    def apply_powers(self):
        for card in self._ordered_cards:
            card.apply_powers()

    def remove_card(self, card: Card):
        self._safe_remove_card(card)
        logger.debug(f"Removed {card} from {self.type}")
        if self.type == CardGroupType.MASTER_DECK:
            card.on_remove_from_master_deck()

            for r in self.ctx.player.relics:
                r.on_master_deck_change()

    def trigger_on_other_card_played(self, used_card: Card):
        for card in self._ordered_cards:
            if used_card != card:
                card.trigger_on_other_card_played(used_card)

        for p in self.ctx.player.powers:
            p.on_after_card_played(used_card)

    def initialize_deck(self, master_deck: CardGroup):
        # Probably complete
        # Source clears here, but I want to know if that's needed.
        assert len(self._ordered_cards) == 0
        # This copy isn't the copy probably think it is. It's how source does it.
        copy_cg = CardGroup(
            self.ctx,
            CardGroupType.DRAW_PILE,
            [c.make_same_instance_of() for c in master_deck],
        )
        copy_cg.shuffle()

        place_on_top = []
        for c in copy_cg:
            if c.is_innate:
                place_on_top.append(c)
            elif not any(
                [c.in_bottle_flame, c.in_bottle_tornado, c.in_bottle_lightning]
            ):
                self.add_to_top(c)
            else:
                place_on_top.append(c)

        for c in place_on_top:
            self.add_to_top(c)

        num_placed_on_top_cards_that_would_not_be_drawn_naturally = (
            len(place_on_top) - self.ctx.player.master_hand_size
        )
        if num_placed_on_top_cards_that_would_not_be_drawn_naturally > 0:
            self.ctx.action_manager.add_to_turn_start(
                DrawCardAction(
                    self.ctx, num_placed_on_top_cards_that_would_not_be_drawn_naturally
                )
            )

    def get_top_card(self):
        return self._ordered_cards[-1]

    def get_random_card(self, card_random_rng: Rng):
        # TODO Source has more options for RNG use
        return self._ordered_cards[
            card_random_rng.random_from_0_to(len(self._ordered_cards) - 1)
        ]

    def empower(self, card: Card):
        self.reset_card_before_moving(card)
        # Source calls souls::empower here, but it appears cosmetic only

    def clear(self):
        self._ordered_cards.clear()

    def get_upgradable_cards(self):
        return [c for c in self._ordered_cards if c.can_upgrade()]

    def has_upgradable_cards(self):
        return any((c.can_upgrade() for c in self._ordered_cards))


class CardGroupType(Enum):
    DRAW_PILE = 0
    MASTER_DECK = 1
    HAND = 2
    DISCARD_PILE = 3
    EXHAUST_PILE = 4
    CARD_POOL = 5
    UNSPECIFIED = 6


class CardQueueItem:
    def __init__(
        self,
        card,
        monster: Optional[Monster],
        energy_on_use: int,
        ignore_energy_total: bool = False,
        is_end_turn_auto_play=False,
    ):
        self.card: Card = card
        self.monster: Optional[Monster] = monster
        self.energy_on_use: int = energy_on_use
        self.ignore_energy_total = ignore_energy_total
        self.autoplay_card = False
        self.random_target = False
        self.is_end_turn_auto_play = is_end_turn_auto_play

    def __repr__(self):
        s = f"{self.card} to {self.monster.name if self.monster else None}"
        if self.ignore_energy_total:
            s += " ignoring energy"
        else:
            s += f" with {self.energy_on_use} energy available"
        return s


class Power(ABC):
    cap_stacks_at_999 = False
    cap_stacks_at_neg_999 = False
    remove_self_at_zero_stacks = False

    def __init__(self, ctx: CCG.Context, owner: Character, amount: Optional[int]):
        self.ctx = ctx
        self.owner: Character = owner
        self._amount: Optional[int] = amount

    def __repr__(self):
        amount_repr = f" {self.amount}" if self.amount is not None else ""
        return f"{self.__class__.__name__}{amount_repr}"

    @property
    def amount(self):
        return self._amount

    @amount.setter
    def amount(self, value):
        if self.cap_stacks_at_999 and value > 999:
            logger.debug(f"Hit stack cap {value} -> 999")
            value = min(999, value)
        if self.cap_stacks_at_neg_999 and value < -999:
            logger.debug(f"Hit stack cap {value} -> -999")
            value = max(-999, value)

        logger.debug(f"Changed stack amount {self} -> {value}")
        self._amount = value

        # Source does this with lots of overrides in particular powers. I think this is equivalent and easier.
        if self.remove_self_at_zero_stacks and value == 0:
            logger.debug(f"Enqueuing removal because at 0 stacks: {self}")
            self.enqueue_self_removal(enqueue_at_bottom=False)

    def add_to_top(self, action: Action):
        self.ctx.action_manager.add_to_top(action)

    def add_to_bottom(self, action: Action):
        self.ctx.action_manager.add_to_bottom(action)

    def stack_power(self, amount: int):
        assert self.amount is not None
        new_amount = self.amount + amount
        self.amount = new_amount

    def reduce_power(self, amount: int):
        # This impl diverges a little from source
        if self.amount:
            self.amount = max(0, self.amount - amount)

    def enqueue_self_removal(self, enqueue_at_bottom=True):
        action = RemoveSpecificPowerAction(self.ctx, self.owner, self)
        if enqueue_at_bottom:
            self.ctx.action_manager.add_to_bottom(action)
        else:
            self.ctx.action_manager.add_to_top(action)

    def modify_block(self, amount: float) -> float:
        return amount

    def modify_block_last(self, running_block):
        return running_block

    @final
    def at_damage_give(
        self, amount: float, damage_type: DamageType, card: Card = None
    ) -> float:
        new_amount = self._at_damage_give_impl(amount, damage_type)
        if new_amount != amount:
            logger.debug(
                f"{self.__class__.__name__} changed damage {amount:.1f} -> {new_amount:.1f}"
            )
        return new_amount

    def _at_damage_give_impl(self, damage: float, damage_type: DamageType) -> float:
        return damage

    def at_end_of_round(self):
        ...

    def on_draw_or_discard(self):
        ...

    def on_initial_application(self):
        ...

    def on_remove(self):
        ...

    def on_energy_recharge(self):
        ...

    def at_start_of_turn(self):
        ...

    def during_turn(self):
        ...

    def at_start_of_turn_post_draw(self):
        ...

    def on_use_card(self, card: Card, action: UseCardAction):
        ...

    def at_damage_receive(self, running_damage, damage_type) -> float:
        return running_damage

    def at_damage_final_give(self, running_damage, damage_type) -> float:
        return running_damage

    def at_damage_final_receive(self, running_damage, damage_type) -> float:
        return running_damage

    def on_after_use_card(self, card: Card, action: Action):
        ...

    def on_after_card_played(self, card: Card):
        ...

    def on_attack_to_change_damage(self, damage_info: DamageInfo, damage_amount: int):
        return damage_amount

    def on_attacked_to_change_damage(
        self, damage_info: DamageInfo, damage_amount: int
    ) -> int:
        return damage_amount

    def on_attack(self, damage_info: DamageInfo, damage_amount: int, target: Character):
        ...

    def on_attacked(self, damage_info: DamageInfo, damage_amount) -> int:
        return damage_amount

    def on_lose_hp(self, damage_amount) -> int:
        return damage_amount

    def was_hp_lost(self, damage_info: DamageInfo, damage_amount):
        ...

    def on_inflict_damage(
        self, damage_info: DamageInfo, damage_amount, target: Character
    ):
        ...

    def on_death(self):
        ...

    def on_gained_block(self, amount):
        ...

    def on_player_gained_block(self, running_block) -> float:
        return running_block

    def on_damage_all_enemies(self, damages: List[int]):
        ...

    def can_play_card(self, card: Card) -> bool:
        return True

    def on_play_card(self, card: Card, monster: Monster):
        ...

    def at_end_of_turn_pre_end_turn_cards(self, is_player: bool):
        ...

    def at_end_of_turn(self, is_player: bool):
        ...

    def on_heal(self, amount):
        return amount

    def on_victory(self):
        pass

    def on_exhaust(self, card):
        pass


class PowerWithAmount(Power, metaclass=ABCMeta):
    def __init__(self, ctx: CCG.Context, owner: Character, amount: int):
        super().__init__(ctx, owner, amount)


class StrengthPower(Power):
    cap_stacks_at_999 = True
    cap_stacks_at_neg_999 = True
    remove_self_at_zero_stacks = True

    def _at_damage_give_impl(self, damage: float, damage_type: DamageType) -> float:
        if damage_type == DamageType.NORMAL:
            return damage + self.amount

        return damage


class GainStrengthPower(Power):
    cap_stacks_at_999 = True
    cap_stacks_at_neg_999 = True

    def at_end_of_turn(self, is_player: bool):
        self.ctx.action_manager.add_to_bottom(
            ApplyPowerAction(
                self.ctx,
                self.owner,
                self.owner,
                StrengthPower(self.ctx, self.owner, self.amount),
            )
        )
        self.enqueue_self_removal()


class NextTurnBlockPower(Power):
    def at_start_of_turn(self):
        self.ctx.action_manager.add_to_bottom(
            GainBlockAction(self.ctx, self.owner, self.amount)
        )
        self.enqueue_self_removal()


class CurlUpPower(Power):
    def __init__(self, ctx: CCG.Context, owner: Character, amount: int):
        super().__init__(ctx, owner, amount)
        self.triggered = False

    def on_attacked(self, damage_info: DamageInfo, damage_amount) -> int:
        if (
            not self.triggered
            and self.owner.current_health > damage_amount > 0
            and damage_info.owner is not None
            and damage_info.damage_type == DamageType.NORMAL
        ):
            self.triggered = True
            self.add_to_bottom(GainBlockAction(self.ctx, self.owner, self.amount))
            self.add_to_bottom(RemoveSpecificPowerAction(self.ctx, self.owner, self))

        return damage_amount


class EnergizedPower(Power):
    cap_stacks_at_999 = True

    def __init__(self, ctx: CCG.Context, owner: Character, amount: Optional[int]):
        super().__init__(ctx, owner, min(999, amount))

    def on_energy_recharge(self):
        self.ctx.player.gain_energy(self.amount)
        self.enqueue_self_removal()


class RitualPower(Power):
    def __init__(
        self, ctx: CCG.Context, owner: Character, amount: int, on_player: bool
    ):
        super().__init__(ctx, owner, amount)
        self.on_player = on_player
        self.skip_first = True
        assert on_player == isinstance(owner, Player)

    def at_end_of_turn(self, is_player: bool):
        if is_player:
            self.add_to_bottom(
                ApplyPowerAction(
                    self.ctx,
                    self.owner,
                    self.owner,
                    StrengthPower(self.ctx, self.owner, self.amount),
                )
            )

    def at_end_of_round(self):
        if not self.on_player:
            if not self.skip_first:
                self.add_to_bottom(
                    ApplyPowerAction(
                        self.ctx,
                        self.owner,
                        self.owner,
                        StrengthPower(self.ctx, self.owner, self.amount),
                    )
                )
            else:
                self.skip_first = False


class DexterityPower(Power):
    cap_stacks_at_999 = True
    cap_stacks_at_neg_999 = True
    remove_self_at_zero_stacks = True

    def __init__(self, ctx: CCG.Context, owner, amount):
        super().__init__(ctx, owner, min(999, max(-999, amount)))

    def modify_block(self, amount: float) -> float:
        modified_block = amount + self.amount
        return max(0.0, modified_block)


class DecrementAtTurnEndPower(Power, metaclass=ABCMeta):
    def __init__(self, ctx: CCG.Context, owner, amount, is_source_monster: bool):
        super().__init__(ctx, owner, amount)
        self.just_applied = is_source_monster

    @final
    def at_end_of_round(self):
        if self.just_applied:
            self.just_applied = False
        else:
            if self.amount == 0:
                # Source adds a ReduceSpecificPowerAction here, but it seems equivalent to letting ReducePowerAction do that in the else.
                ...
            else:
                self.ctx.action_manager.add_to_bottom(
                    ReducePowerAction(self.ctx, self.owner, self.__class__, 1)
                )


class WeakPower(DecrementAtTurnEndPower):
    damage_multiplier: float = 0.75

    def _at_damage_give_impl(self, damage: float, damage_type: DamageType) -> float:
        # TODO paper crane
        return (
            damage * self.damage_multiplier
            if damage_type == DamageType.NORMAL
            else damage
        )


class VigorPower(Power):
    def _at_damage_give_impl(self, damage: float, damage_type: DamageType):
        return (
            damage + float(self.amount) if damage_type == DamageType.NORMAL else damage
        )

    def on_use_card(self, card: Card, action: UseCardAction):
        if card.card_type == CardType.ATTACK:
            self.enqueue_self_removal()


class MinionPower(Power):
    def __init__(self, ctx: CCG.Context, owner: Character):
        super().__init__(ctx, owner, None)


class PoisonPower(Power):
    def __init__(
        self, ctx: CCG.Context, owner: Character, source: Character, amount: int
    ):
        super().__init__(ctx, owner, min(9999, amount))
        self.source = source

    def at_start_of_turn(self):
        # Room phase check in source
        if not self.ctx.d.get_curr_room().monster_group.are_monsters_basically_dead():
            self.ctx.action_manager.add_to_bottom(
                PoisonLoseHpAction(self.ctx, self.owner, self.source, self.amount)
            )


class FrailPower(DecrementAtTurnEndPower):
    block_multiplier = 0.75

    def modify_block(self, amount: float) -> float:
        return amount * self.block_multiplier


class SplitPower(Power):
    def __init__(self, ctx: CCG.Context, owner: Character):
        super().__init__(ctx, owner, None)


class SporeCloudPower(PowerWithAmount):
    def on_death(self):
        self.add_to_top(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                None,
                VulnerablePower(
                    self.ctx, self.ctx.player, self.amount, is_source_monster=True
                ),
            )
        )


class VulnerablePower(DecrementAtTurnEndPower):
    def __init__(
        self, ctx: CCG.Context, owner: Character, amount: int, is_source_monster: bool
    ):
        super().__init__(ctx, owner, amount, is_source_monster)
        # Source sets this one a little differently than WeakPower.
        self.just_applied = self.ctx.action_manager.turn_has_ended and is_source_monster

    def at_damage_receive(self, running_damage, damage_type) -> float:
        if damage_type == DamageType.NORMAL:
            # TODO odd mushroom, paper frog
            return running_damage * 1.5
        else:
            return running_damage


class AngryPower(PowerWithAmount):
    def on_attacked(self, damage_info: DamageInfo, damage_amount) -> int:
        # Source checks owner for null
        if damage_amount > 0 and damage_info.damage_type not in [
            DamageType.HP_LOSS,
            DamageType.THORNS,
        ]:
            self.add_to_top(
                ApplyPowerAction(
                    self.ctx,
                    self.owner,
                    self.owner,
                    StrengthPower(self.ctx, self.owner, self.amount),
                )
            )

        return damage_amount


class MetallicizePower(PowerWithAmount):
    def at_end_of_turn_pre_end_turn_cards(self, is_player: bool):
        self.add_to_bottom(GainBlockAction(self.ctx, self.owner, self.amount))


class ThieveryPower(PowerWithAmount):
    ...


class EntangledPower(Power):
    def at_end_of_turn(self, is_player: bool):
        if is_player:
            self.add_to_bottom(RemoveSpecificPowerAction(self.ctx, self.owner, self))


class SharpHidePower(PowerWithAmount):
    def on_use_card(self, card: Card, action: UseCardAction):
        if card.card_type == CardType.ATTACK:
            self.add_to_bottom(
                DamageAction(
                    self.ctx,
                    self.ctx.player,
                    DamageInfo(self.owner, self.amount, DamageType.THORNS),
                    self.owner,
                )
            )


class ModeShiftPower(PowerWithAmount):
    ...


class AngerPower(PowerWithAmount):
    def on_use_card(self, card: Card, action: UseCardAction):
        if card.card_type == CardType.SKILL:
            self.add_to_top(
                ApplyPowerAction(
                    self.ctx,
                    self.owner,
                    self.owner,
                    StrengthPower(self.ctx, self.owner, self.amount),
                )
            )


class NewPowersHere:
    ...


class RelicTier(Enum):
    STARTER = 0
    COMMON = 1
    UNCOMMON = 2
    RARE = 3
    SPECIAL = 4
    BOSS = 5
    SHOP = 6


class Relic(ABC):
    def __init__(self, ctx: CCG.Context, counter=-1):
        # As best I can tell, counter at -1 means the relic doesn't show a count and is disarmed (if it can be armed),
        # and counter at -2 means it's armed.
        self.ctx = ctx
        self.counter = counter
        self.is_pulsing = False

    def __repr__(self) -> str:
        pulsing_repr = "✓" if self.is_pulsing else "✗"
        counter_repr = ""
        if self.counter >= 0:
            counter_repr = f" {self.counter}"
        elif self.is_armed:
            counter_repr = " ARM"

        return f"{self.__class__.__name__} {pulsing_repr}{counter_repr}"

    @property
    def is_armed(self):
        # I think all arming relics use the -1/-2 scheme. This might end up being equivalent to is_pulsing.
        assert self.counter == -1 or self.counter == -2
        return self.counter == -2

    @is_armed.setter
    def is_armed(self, value):
        assert self.counter == -1 or self.counter == -2
        assert isinstance(value, bool)
        if value:
            self.counter = -2
        else:
            self.counter = -1

    @classmethod
    def get_tier(cls) -> RelicTier:
        raise NotImplementedError()

    @final
    def instant_obtain(self, player: Player, call_on_equip: bool):
        # There's a lot in source that I don't think we have to do.
        logger.debug(f"{player.name} obtained relic {self.__class__.__name__}")
        if not isinstance(self, (Circlet, RedCirclet)):
            assert not any(isinstance(r, type(self)) for r in player.relics)
        player.relics.append(self)

        if call_on_equip:
            self.on_equip()

    def at_battle_start_pre_draw(self):
        ...

    def at_battle_start(self):
        ...

    def on_equip(self):
        ...

    def on_energy_recharge(self):
        ...

    def at_turn_start(self):
        ...

    def at_turn_start_post_draw(self):
        ...

    def on_use_card(self, card: Card, action: UseCardAction):
        ...

    def on_master_deck_change(self):
        ...

    def at_damage_modify(self, running_damage: float, card: Card):
        return running_damage

    def on_block_broken(self, monster: Monster):
        ...

    def on_attack_to_change_damage(self, damage_info: DamageInfo, damage_amount: int):
        return damage_amount

    def on_attacked_to_change_damage(
        self, damage_info: DamageInfo, damage_amount: int
    ) -> int:
        return damage_amount

    def on_attack(self, damage_info: DamageInfo, damage_amount: int, target: Character):
        ...

    def on_attacked(self, damage_info: DamageInfo, damage_amount) -> int:
        return damage_amount

    def on_lose_hp_last(self, damage_amount) -> int:
        return damage_amount

    def on_lose_hp(self, damage_amount):
        ...

    def was_hp_lost(self, damage_amount):
        ...

    def on_bloodied(self):
        ...

    def on_monster_death(self, monster: Monster):
        ...

    def on_player_gained_block(self, running_block) -> float:
        return running_block

    def on_manual_discard(self):
        ...

    def on_spawn_monster(self, monster: Monster):
        ...

    def can_play(self, card: Card):
        return True

    def on_play_card(self, card: Card, monster: Monster):
        ...

    def on_enter_room(self, room: Room):
        ...

    def just_entered_room(self, room: Room):
        ...

    def on_player_heal(self, amount):
        return amount

    def on_not_bloodied(self):
        ...

    def on_enter_rest_room(self):
        ...

    def change_number_of_cards_in_reward(self, num_cards: int):
        return num_cards

    def change_rare_card_reward_chance(self, rare_card_chance):
        return rare_card_chance

    def change_uncommon_card_reward_chance(self, uncommon_card_chance):
        return uncommon_card_chance

    def on_preview_obtain_card(self, card):
        pass

    def on_obtain_card(self, card):
        pass

    def on_victory(self):
        pass

    def on_gain_gold(self):
        pass

    def on_exhaust(self, card):
        pass

    def on_chest_open(self, is_boss_chest: bool):
        pass

    def on_chest_open_after(self, is_boss_chest: bool):
        pass

    def can_use_campfire_option(self, op: CampfireOption):
        return True

    def add_campfire_option(self, options: List[CampfireOption]):
        pass

    def on_rest(self):
        pass

    def on_player_end_turn(self):
        pass

    def on_smith(self):
        pass

    def at_pre_battle(self):
        pass


class SnakeRing(Relic):
    magic_number = 2

    @classmethod
    def get_tier(cls) -> RelicTier:
        return RelicTier.STARTER

    def at_battle_start(self):
        self.ctx.action_manager.add_to_bottom(
            DrawCardAction(self.ctx, self.magic_number)
        )


class CommonRelic(Relic):
    @classmethod
    @final
    def get_tier(cls) -> RelicTier:
        return RelicTier.COMMON


class SpecialRelic(Relic):
    @classmethod
    @final
    def get_tier(cls) -> RelicTier:
        return RelicTier.SPECIAL


class Akabeko(CommonRelic):
    amount = 8

    def at_battle_start(self):
        self.ctx.action_manager.add_to_top(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                self.ctx.player,
                VigorPower(self.ctx, self.ctx.player, self.amount),
            )
        )


class GamblingChip(CommonRelic):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.activated = False

    def at_battle_start_pre_draw(self):
        self.activated = False

    def at_turn_start_post_draw(self):
        if not self.activated:
            self.activated = True
            self.ctx.action_manager.add_to_bottom(
                GamblingChipAction(
                    self.ctx,
                )
            )


class OddlySmoothStone(CommonRelic):
    def at_battle_start(self):
        self.ctx.action_manager.add_to_top(
            ApplyPowerAction(
                self.ctx,
                self.ctx.player,
                self.ctx.player,
                DexterityPower(self.ctx, self.ctx.player, 1),
            )
        )


class Anchor(CommonRelic):
    def at_battle_start(self):
        self.ctx.action_manager.add_to_bottom(
            GainBlockAction(self.ctx, self.ctx.player, 10)
        )


class AncientTeaSet(CommonRelic):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.is_first_turn = False

    def on_enter_rest_room(self):
        self.is_armed = True
        self.is_pulsing = True

    def at_pre_battle(self):
        self.is_first_turn = True

    def at_turn_start(self):
        if self.is_first_turn:
            if self.is_armed:
                self.is_armed = False
                self.is_pulsing = False
                self.ctx.action_manager.add_to_top(GainEnergyAction(self.ctx, 2))
            self.is_first_turn = False


class ArtOfWar(CommonRelic):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.is_first_turn = False

    def at_pre_battle(self):
        self.is_first_turn = True
        self.is_armed = True
        self.is_pulsing = True

    def at_turn_start(self):
        self.is_pulsing = True
        if self.is_armed and not self.is_first_turn:
            self.ctx.action_manager.add_to_bottom(GainEnergyAction(self.ctx, 1))

        self.is_first_turn = False
        self.is_armed = True

    def on_use_card(self, card: Card, action: UseCardAction):
        if card.card_type == CardType.ATTACK:
            self.is_armed = False
            self.is_pulsing = False

    def on_victory(self):
        self.is_pulsing = False


# noinspection PyAbstractClass
class GoldenIdol(SpecialRelic):
    # noinspection PyMissingConstructor
    def __init__(self):
        raise NotImplementedError()


class Circlet(SpecialRelic):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1)


class RedCirclet(SpecialRelic):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 1)


class PotionRarity(Enum):
    COMMON = 0
    UNCOMMON = 1
    RARE = 2


class Potion(ABC):
    def __init__(self, ctx: CCG.Context, rarity: PotionRarity, target_required: bool):
        self.ctx = ctx
        self.target_required: bool = target_required
        self.rarity: PotionRarity = rarity
        # Source does this with initializeData, but it seems like all that every does in its many overrides is this.
        self.potency: int = self._get_potency()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__} {self.potency}"

    @abstractmethod
    def use(self, target: Optional[Character] = None):
        ...

    def _get_potency(self):
        potency = self.get_potency_with_ascension(AscensionManager.get_ascension(self))
        # TODO sacred bark
        return potency

    @abstractmethod
    def get_potency_with_ascension(self, ascension_level: int) -> int:
        # Source calls this get_potency, but I'm doing it a bit different and python doesn't do method overloading.
        ...

    @classmethod
    def make_copy(cls):
        raise NotImplementedError()
        # return cls()

    def add_to_bottom(self, action: Action):
        self.ctx.action_manager.add_to_bottom(action)

    def add_to_top(self, action: Action):
        self.ctx.action_manager.add_to_top(action)

    def can_discard(self):
        # TODO event we meet again
        return True


class EnergyPotion(Potion):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, PotionRarity.COMMON, False)

    def use(self, target: Optional[Character] = None):
        self.add_to_bottom(GainEnergyAction(self.ctx, self.potency))

    def get_potency_with_ascension(self, ascension_level: int) -> int:
        return 2


class FirePotion(Potion):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, PotionRarity.COMMON, True)

    def use(self, target: Optional[Character] = None):
        damage_info = DamageInfo(self.ctx.player, self.potency, DamageType.THORNS)
        damage_info.apply_enemy_powers_only(target)
        self.add_to_bottom(DamageAction(self.ctx, target, damage_info, self.ctx.player))

    def get_potency_with_ascension(self, ascension_level: int) -> int:
        return 20


class GetAllInBattleInstances:
    @staticmethod
    def get(card_uuid: uuid.UUID, player: Player) -> Set[Card]:
        cards = set()

        if player.card_in_use.uuid == card_uuid:
            cards.add(player.card_in_use)

        # TODO limbo?
        for c in flatten(
            [player.draw_pile, player.discard_pile, player.exhaust_pile, player.hand]
        ):
            if c.uuid == card_uuid:
                cards.add(c)

        return cards


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


class AscensionManager:
    _V = TypeVar("_V")
    _ascension_level: int = 0

    @classmethod
    def check_ascension(
        cls,
        caller,
        value_if_lt: _V,
        ascension_threshold: int,
        value_if_ge: _V,
        ascension_threshold_2: int = None,
        value_if_ge_2: _V = None,
    ) -> _V:
        assert (ascension_threshold_2 is None) == (value_if_ge_2 is None)
        prefix = f"ASC {cls._ascension_level:2d} check"

        if (
            ascension_threshold_2 is not None
            and cls._ascension_level >= ascension_threshold_2
        ):
            logger.debug(
                f"{prefix}:  {value_if_ge}  |{ascension_threshold_2:2d}| [{value_if_ge_2}]"
            )
            result = value_if_ge_2
        elif cls._ascension_level >= ascension_threshold:
            logger.debug(
                f"{prefix}:  {value_if_lt}  |{ascension_threshold:2d}| [{value_if_ge}]"
            )
            result = value_if_ge
        else:
            logger.debug(
                f"{prefix}: [{value_if_lt}] |{ascension_threshold:2d}|  {value_if_ge} "
            )
            result = value_if_lt

        return result

    @classmethod
    def get_ascension(cls, caller):
        logger.debug(f"ASC {cls._ascension_level} retrieved")
        return cls._ascension_level

    # TODO can't set asc statically like this
    # @classmethod
    # def set_ascension(cls, caller, asc: int):
    #     logger.debug(f'Set ASC to {asc}')
    #     cls._ascension_level = asc


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


class TheSilent(Player):
    def __init__(
        self,
        ctx: CCG.Context,
        max_health: int = 80,
        energy_master: int = 3,
        starting_deck_override: List[Callable[[CCG.Context], Card]] = None,
        initial_potions: Callable[[CCG.Context], List[Potion]] = None,
    ):
        super().__init__(ctx, max_health, energy_master, initial_potions)
        self.starting_deck_override = starting_deck_override

    def get_card_pool(self) -> List[Card]:
        # TODO source is more robust, calls CardLibrary, but this'll do for now
        return [
            c
            for c in dts.SILENT_CARD_UNIVERSE
            if c.rarity != CardRarity.BASIC and c.color == CardColor.GREEN
        ]

    @classmethod
    def get_ascension_max_hp_loss(cls):
        return 4

    def get_starting_deck(self) -> List[Card]:
        if self.starting_deck_override:
            card_recipes = self.starting_deck_override
        else:
            card_recipes = CardGroup.explode_card_group_recipe_manifest(
                {
                    Strike.recipe(): 5,
                    Defend.recipe(): 5,
                    Survivor.recipe(): 1,
                    Neutralize.recipe(): 1,
                }
            )

        return CardGroup.hydrate_card_recipes(self.ctx, card_recipes)


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


class Chest(ABC):
    def __init__(self, ctx: CCG.Context) -> None:
        super().__init__()
        self.ctx = ctx

    @abstractmethod
    def open(self):
        ...


class BossChest(Chest):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.relics = [self.ctx.d.return_random_relic(RelicTier.BOSS) for _ in range(3)]

    def open(self):
        for r in self.ctx.player.relics:
            # TODO matryoshka
            r.on_chest_open(False)


class OrdinaryChest(Chest):
    def __init__(
        self,
        ctx: CCG.Context,
        common_chance: int,
        uncommon_chance: int,
        gold_chance: int,
        gold_amount: int,
    ):
        super().__init__(ctx)
        assert common_chance + uncommon_chance <= 100
        self.gold_amount = gold_amount
        roll = self.ctx.treasure_rng.random_from_0_to(99)
        logger.debug(
            f"Open chest roll {roll} vs {gold_chance} for base {gold_amount} gold"
        )
        self.gold_reward = roll < gold_chance

        if roll < common_chance:
            self.relic_reward_tier = RelicTier.COMMON
        elif roll < common_chance + uncommon_chance:
            self.relic_reward_tier = RelicTier.UNCOMMON
        else:
            self.relic_reward_tier = RelicTier.RARE

    def open(self):
        for r in self.ctx.player.relics:
            # TODO matryoshka
            r.on_chest_open(False)

        if self.gold_reward:
            jittered_gold = round(
                self.ctx.treasure_rng.random_float_between(
                    0.9 * self.gold_amount, 1.1 * self.gold_amount
                )
            )
            self.ctx.d.get_curr_room().add_gold_to_rewards(jittered_gold)

        self.ctx.d.get_curr_room().add_relic_to_rewards(self.relic_reward_tier)

        if not self.ctx.player.has_sapphire_key:
            linked_reward = self.ctx.d.get_curr_room().rewards[-1]
            assert isinstance(linked_reward, RelicRewardItem)
            self.ctx.d.get_curr_room().add_sapphire_key(linked_reward)

        for r in self.ctx.player.relics:
            r.on_chest_open_after(False)

        # Source opens combat reward screen here


class SmallChest(OrdinaryChest):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 75, 25, 50, 25)


class MediumChest(OrdinaryChest):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 35, 50, 35, 50)


class LargeChest(OrdinaryChest):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx, 0, 75, 50, 75)
