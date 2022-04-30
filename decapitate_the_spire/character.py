from __future__ import annotations

import logging
import os
import random
from abc import ABC, abstractmethod
from collections import deque
from enum import Enum
from typing import List, Optional, Type, Callable, Dict, Iterable, final

import decapitate_the_spire as dts
from decapitate_the_spire.action import Action, DamageInfo, DamageType, UseCardAction, RollMoveAction, SetMoveAction, \
    SpawnMonsterAction, ApplyPowerAction, GainBlockAction, SuicideAction, LoseHPAction, GainBlockRandomMonsterAction, \
    AddStolenGoldToMonsterAction, RemoveSpecificPowerAction, LoseBlockAction, BurnIncreaseAction
from typing import TYPE_CHECKING

from decapitate_the_spire.ascension import AscensionManager, AscensionDependentValue, ADV
from decapitate_the_spire.config import MAX_NUM_MONSTERS_IN_GROUP
from decapitate_the_spire.util import flatten
from decapitate_the_spire.relic import Relic, SnakeRing
from decapitate_the_spire.power import Power, StrengthPower, CurlUpPower, RitualPower, DexterityPower, WeakPower, \
    MinionPower, FrailPower, SplitPower, SporeCloudPower, VulnerablePower, AngryPower, MetallicizePower, ThieveryPower, \
    EntangledPower, SharpHidePower, ModeShiftPower, AngerPower
from decapitate_the_spire.card import Card, Slimed, Wound, AscendersBane, Dazed, Burn, CurseOfTheBell, \
    Necronomicurse, CardGroup, CardGroupType, CardQueueItem, Strike, Defend, Survivor, Neutralize
from decapitate_the_spire.move import Move, DebuffMove, AttackMove, AttackTrashDiscardMove, SplitMove, BuffMove, \
    AttackDefendMove, DefendBuffMove, DefendMove, AttackDebuffMove, DamageMove, EscapeMove, TrashDiscardMove, NoOpMove, \
    SplitDifferentMove
from decapitate_the_spire.rng import Rng
from decapitate_the_spire.room import MonsterRoomElite, MonsterRoomBoss
from decapitate_the_spire.enums import RoomPhase, Intent, CardType, CardRarity, CardColor

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG, ADVOrInt
    from decapitate_the_spire.potion import Potion

logger = logging.getLogger(__name__)


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
        dead_repr = "DEAD" if self.is_dead else "NOT DEAD"
        escaped_repr = "ESCAPED" if self.escaped else "NOT ESCAPED"
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
        # This ends up setting output in DamageInfo.
        for move in self.names_to_moves.values():
            move.apply_powers()

        # These two predicates might mean the same thing; source might use -1 as sentinel to mean "None".
        # if self.move_info.base_damage is not None and self.move_info.base_damage > -1:
        #     self._calculate_damage(self.move_info.base_damage)

    # def _calculate_damage(self, damage: int):
    #     running_damage = float(damage)
    #
    #     for power in self.powers:
    #         running_damage = power.at_damage_give(running_damage, DamageType.NORMAL)
    #
    #     # TODO incomplete
    #
    #     self.intent_damage = max(0, int(running_damage))

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
        intent: Intent,
        damage: int = None,
        multiplier: int = None,
    ):
        self.intent: Intent = intent
        # This is calculated damage (with powers applied), not base damage.
        self.damage: Optional[int] = damage
        # Source appears to use this only for showing intent, not damage calculation
        self.multiplier: Optional[int] = multiplier

    def __repr__(self):
        if self.damage is None:
            return f"{self.intent.name}: {self.intent}"
        else:
            multiplier_repr = (
                f"{self.multiplier}x " if self.multiplier is not None else ""
            )
            return f"{self.intent.name}: {multiplier_repr}{self.damage}"

    def is_multi_damage(self):
        return self.multiplier is not None


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
