from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, List

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG
    from decapitate_the_spire.character import MonsterGroup
from decapitate_the_spire.ascension import AscensionManager
from decapitate_the_spire.util import flatten
from decapitate_the_spire.enums import RelicTier, RoomPhase, CardRarity
from decapitate_the_spire.action import UnnamedRoomEndTurnAction, DrawCardAction, ClearCardQueueAction, \
    DiscardAtEndOfTurnAction, GainEnergyAndEnableControlsAction, ActionManager, ProceedButton, CombatRewardRequest, \
    BossChestRequest, CampfireRequest, CombatActionRequest, CampfireOption, RestOption, SmithOption, \
    RecallOption
from decapitate_the_spire.event import Event, NeowEvent, DebugNoOpNeowEvent
from decapitate_the_spire.rewards import RewardItem, StolenGoldRewardItem, PotionRewardItem, RelicRewardItem, \
    GoldRewardItem, SapphireKeyRewardItem, EmeraldKeyRewardItem

logger = logging.getLogger(__name__)


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
                from decapitate_the_spire.dungeon import TheBeyond, TheEnding
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
