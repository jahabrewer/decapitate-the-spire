from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decapitate_the_spire.action import Action, GainEnergyAction, DamageInfo, DamageType, DamageAction
    from decapitate_the_spire.character import Character
    from decapitate_the_spire.game import CCG
from decapitate_the_spire.ascension import AscensionManager


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
