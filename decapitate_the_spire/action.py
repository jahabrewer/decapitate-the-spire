from __future__ import annotations

import logging
import os
import random
import uuid
from abc import ABC, abstractmethod, ABCMeta
from collections import deque
from enum import Enum
from typing import Optional, List, Union, Type, final, Set, Deque, TYPE_CHECKING, Callable

from decapitate_the_spire.config import MAX_HAND_SIZE, ACTION_1_ALL_FALSE_SLICE, MAX_POTION_SLOTS, ACTION_1_LEN, \
    MAX_NUM_MONSTERS_IN_GROUP, ACTION_1_SINGLE_TRUE, MAP_WIDTH
from decapitate_the_spire.enums import Screen, RoomPhase, Intent, CardType, CardTarget
from decapitate_the_spire.util import flatten

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG, ActionMaskSlices, ActionCoord, ActionCoordConsumer
    from decapitate_the_spire.power import Power, MinionPower, PoisonPower
    from decapitate_the_spire.potion import Potion
    from decapitate_the_spire.rewards import RewardItem, RelicRewardItem
    from decapitate_the_spire.card import Card, Burn, CardGroup, CardQueueItem
    from decapitate_the_spire.character import Character, Player, Monster, MoveName, Looter, MonsterGroup
    from decapitate_the_spire.event import SimpleChoiceEvent
    from decapitate_the_spire.map import MapEdge


logger = logging.getLogger(__name__)


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
                from decapitate_the_spire.card import CardQueueItem
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


class NewActionsHere:
    ...


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


class ProceedButton:
    @classmethod
    def on_click(cls, ctx: CCG.Context):
        """Source doesn't have this method; this is a shortened version of what happens when source's
        ProceedButton#update detects a click."""
        curr_room = ctx.d.get_curr_room()
        from decapitate_the_spire.room import MonsterRoomBoss, TreasureRoomBoss, EventRoom
        if isinstance(curr_room, MonsterRoomBoss):
            from decapitate_the_spire.dungeon import TheBeyond, TheEnding
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
        from decapitate_the_spire.map import MapRoomNode
        from decapitate_the_spire.room import TreasureRoomBoss
        node = MapRoomNode(-1, 15)
        node.room = TreasureRoomBoss(ctx)
        ctx.d.next_room_node = node
        # Source does this with nextRoomTransitionStart, but I think this is equivalent enough for us.
        ctx.d.next_room_transition()


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
            from decapitate_the_spire.action import DrawCardAction
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
        from decapitate_the_spire.room import MonsterRoomBoss
        from decapitate_the_spire.map import MapRoomNode
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
        from decapitate_the_spire.action import NewQueueCardAction
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
        from decapitate_the_spire.card import CardQueueItem
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
