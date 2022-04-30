from __future__ import annotations

import logging
import os
from typing import List

from typing import TYPE_CHECKING

from decapitate_the_spire.enums import Screen

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG
from decapitate_the_spire.rewards import RewardItem, CardRewardItem
from decapitate_the_spire.room import TreasureRoom, RestRoom

logger = logging.getLogger(__name__)

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


