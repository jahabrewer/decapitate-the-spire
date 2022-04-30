from __future__ import annotations

import logging
from abc import ABC, abstractmethod, ABCMeta
from typing import final

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG
from decapitate_the_spire.action import ActionGenerator, SimpleChoiceEventRequest

logger = logging.getLogger(__name__)

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
        from decapitate_the_spire.enums import RoomPhase
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
        from decapitate_the_spire.enums import RoomPhase
        self.ctx.d.get_curr_room().phase = RoomPhase.COMPLETE


class DebugNoOpNeowEvent(SimpleChoiceEvent):
    num_choices_if_always_same = 1

    def button_effect_impl(self, num: int):
        logger.debug(f"Player chose neow reward {num}")
        assert self.ctx.d.get_curr_room().event is self
        from decapitate_the_spire.enums import RoomPhase
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
