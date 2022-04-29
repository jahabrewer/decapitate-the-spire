from __future__ import annotations

import copy
import logging
import random
import uuid
from abc import ABC, abstractmethod
from collections import deque
from enum import Enum
from typing import Optional, List, Tuple, Any, Callable, final, Iterable, Deque, Dict
from typing import TYPE_CHECKING

import decapitate_the_spire as dts
from decapitate_the_spire.action import DamageType, Action, DamageInfo, ExhaustSpecificCardAction, DamageAction, \
    GainBlockAction, ApplyPowerAction, DiscardAction, ObtainPotionAction, GainEnergyAction, DamageAllEnemiesAction, \
    SkewerAction, ModifyDamageAction, DrawCardAction, BaneAction, LoseHPAction, MakeTempCardInHandAction, \
    GainEnergyIfDiscardAction
from decapitate_the_spire.enums import CardType, CardTarget, CardRarity, CardColor

if TYPE_CHECKING:
    from decapitate_the_spire.character import Monster
    from decapitate_the_spire.game import CCG
from decapitate_the_spire.power import StrengthPower, GainStrengthPower, NextTurnBlockPower, EnergizedPower, \
    DexterityPower, WeakPower, PoisonPower, EntangledPower
from decapitate_the_spire.rng import Rng

logger = logging.getLogger(__name__)


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
