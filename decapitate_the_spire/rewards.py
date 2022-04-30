from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decapitate_the_spire.game import CCG
    from decapitate_the_spire.potion import Potion
    from decapitate_the_spire.relic import Relic
from decapitate_the_spire.config import ACTION_1_LEN, ACTION_1_ALL_FALSE_SLICE, ACTION_1_SINGLE_TRUE

logger = logging.getLogger(__name__)


class RewardItem(ABC):
    def __init__(self, ctx: CCG.Context):
        self.ctx = ctx
        self.ignore_reward = False

    @abstractmethod
    def claim_reward(self, action_1: int):
        ...

    def to_mask_slice(self):
        if self.ignore_reward:
            return ACTION_1_ALL_FALSE_SLICE

        return self._to_mask_slice_impl()

    @abstractmethod
    def _to_mask_slice_impl(self):
        ...


class PotionRewardItem(RewardItem):
    def __init__(self, ctx: CCG.Context, potion: Potion):
        super().__init__(ctx)
        self.potion = potion

    def __repr__(self):
        return f"Potion: {self.potion}"

    def claim_reward(self, action_1: int):
        # TODO sozu
        self.ctx.player.obtain_potion(self.potion)
        logger.debug(f"Claimed potion reward: {self.potion}")

    def _to_mask_slice_impl(self):
        if len(self.ctx.player.potions) < self.ctx.player.potion_slots:
            return ACTION_1_SINGLE_TRUE
        else:
            return ACTION_1_ALL_FALSE_SLICE


class CardRewardItem(RewardItem):
    def __init__(self, ctx: CCG.Context):
        super().__init__(ctx)
        self.cards = self.ctx.d.get_reward_cards()

    def __repr__(self):
        cards_repr = ", ".join([c.__repr__() for c in self.cards])
        return f"Cards: < {cards_repr} >"

    def _to_mask_slice_impl(self):
        assert len(self.cards) <= 4
        # TODO singing bowl
        # [ pick card 0..3, +2 max hp ]
        return [i < len(self.cards) for i in range(ACTION_1_LEN)]

    def claim_reward(self, action_1: int):
        # TODO busted crown, question card
        assert action_1 < len(self.cards)
        card = self.cards[action_1]
        logger.debug(f"Claimed card reward: {card}")
        self.ctx.player.obtain_card(card)


class GoldRewardItem(RewardItem):
    def __init__(self, ctx: CCG.Context, gold: int):
        super().__init__(ctx)
        self.base_gold = gold
        self.bonus_gold = 0

    def __repr__(self):
        return f"Gold: {self.base_gold} ({self.bonus_gold})"

    @property
    def total_gold(self):
        return self.base_gold + self.bonus_gold

    def increment_gold(self, added_gold: int):
        self.base_gold += added_gold

    def _apply_gold_bonus(self):
        # TODO golden idol
        ...

    def claim_reward(self, action_1: int):
        self.ctx.player.gain_gold(self.total_gold)
        logger.debug(f"Claimed gold reward: {self.total_gold}")

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class StolenGoldRewardItem(GoldRewardItem):
    def __repr__(self):
        return f"Stolen gold: {self.base_gold} ({self.bonus_gold})"


class LinkedRelicItem(RewardItem):
    def __init__(self, ctx: CCG.Context, relic_link: Optional[RelicRewardItem]):
        super().__init__(ctx)
        self.relic_link = relic_link
        # Ensure the linked item knows about self
        if self.relic_link:
            assert self.relic_link.relic_link is None
            self.relic_link.relic_link = self

    def trigger_relic_link(self):
        if self.relic_link:
            assert not self.relic_link.ignore_reward
            self.relic_link.ignore_reward = True
            logger.debug(f"Activated relic link for {self.relic_link}")


class RelicRewardItem(LinkedRelicItem):
    def __init__(
        self, ctx: CCG.Context, relic: Relic, relic_link: RelicRewardItem = None
    ):
        super().__init__(ctx, relic_link)
        self.relic = relic

    def __repr__(self):
        return f"Relic: {self.relic}"

    def claim_reward(self, action_1: int):
        assert not self.ignore_reward
        self.relic.instant_obtain(self.ctx.player, True)
        self.trigger_relic_link()

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class EmeraldKeyRewardItem(RewardItem):
    def __repr__(self):
        return "Emerald Key"

    def claim_reward(self, action_1: int):
        logger.debug("Claimed emerald key")
        self.ctx.player.obtain_emerald_key()

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE


class SapphireKeyRewardItem(LinkedRelicItem):
    def __repr__(self):
        return "Sapphire Key"

    def claim_reward(self, action_1: int):
        logger.debug("Claimed sapphire key")
        assert not self.ignore_reward
        self.ctx.player.obtain_sapphire_key()
        self.trigger_relic_link()

    def _to_mask_slice_impl(self):
        return ACTION_1_SINGLE_TRUE
