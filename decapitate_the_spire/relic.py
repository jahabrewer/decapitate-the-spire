from __future__ import annotations

import logging
from abc import ABC
from typing import final, List

from decapitate_the_spire.action import UseCardAction, DamageInfo, DrawCardAction, ApplyPowerAction, GamblingChipAction, \
    GainBlockAction, GainEnergyAction, CampfireOption

from typing import TYPE_CHECKING

from decapitate_the_spire.enums import RelicTier, CardType

if TYPE_CHECKING:
    from decapitate_the_spire.card import Card
    from decapitate_the_spire.character import Player, Monster, Character
    from decapitate_the_spire.game import CCG
    from decapitate_the_spire.room import Room
from decapitate_the_spire.power import VigorPower, DexterityPower

logger = logging.getLogger(__name__)


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
