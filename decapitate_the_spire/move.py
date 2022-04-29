from __future__ import annotations

from abc import ABC, abstractmethod, ABCMeta
from typing import final, Optional, Callable, Iterable, List

from decapitate_the_spire.action import Action, DamageAction, GainBlockAction, ApplyPowerAction, \
    MakeTempCardInDiscardAction, CannotLoseAction, SuicideAction, SpawnMonsterAction, CanLoseAction, EscapeAction, \
    DamageInfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG
    from decapitate_the_spire.character import Player, Monster, EnemyMoveInfo
from decapitate_the_spire.enums import Intent
from decapitate_the_spire.ascension import AscensionDependentValue, AscensionDependentValueOrInt
from decapitate_the_spire.power import Power
from decapitate_the_spire.card import Card


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
        from decapitate_the_spire.character import EnemyMoveInfo
        return EnemyMoveInfo(
            self.get_intent(), self.get_damage(), self.get_multiplier()
        )

    def get_damage(self) -> Optional[int]:
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

    def get_damage(self) -> Optional[int]:
        return self.damage_info.output

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
