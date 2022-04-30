from __future__ import annotations

import logging
from abc import ABC, ABCMeta
from typing import Optional, final, List
from typing import TYPE_CHECKING

from decapitate_the_spire.action import Action, RemoveSpecificPowerAction, DamageType, UseCardAction, DamageInfo, \
    ApplyPowerAction, GainBlockAction, ReducePowerAction, PoisonLoseHpAction, DamageAction

from decapitate_the_spire.enums import CardType
if TYPE_CHECKING:
    from decapitate_the_spire.card import Card
    from decapitate_the_spire.game import CCG
    from decapitate_the_spire.character import Character, Monster
logger = logging.getLogger(__name__)


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
        # assert on_player == isinstance(owner, Player)

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
