from __future__ import annotations

from enum import Enum


class Screen(Enum):
    NONE = 0
    COMBAT_REWARD = 1


class RelicTier(Enum):
    STARTER = 0
    COMMON = 1
    UNCOMMON = 2
    RARE = 3
    SPECIAL = 4
    BOSS = 5
    SHOP = 6


class RoomPhase(Enum):
    COMBAT = 0
    EVENT = 1
    COMPLETE = 2
    INCOMPLETE = 3


class Intent(Enum):
    ATTACK = 0
    DEFEND = 1
    DEBUFF = 2
    ATTACK_DEBUFF = 3
    UNKNOWN = 4
    BUFF = 5
    DEFEND_BUFF = 6
    ATTACK_DEFEND = 7
    ESCAPE = 8
    STUN = 9
    SLEEP = 10
    ATTACK_BUFF = 11


class CardType(Enum):
    ATTACK = 0
    SKILL = 1
    POWER = 2
    STATUS = 3
    CURSE = 4


class CardTarget(Enum):
    # Backstab, Strike
    ENEMY = 0
    # Die Die Die, All Out Attack
    ALL_ENEMY = 1
    # Accuracy, Alchemize
    SELF = 2
    # Blade Dance, Nightmare
    NONE = 3
    # Spot Weakness (this one appears rare, no green cards)
    SELF_AND_ENEMY = 4
    # Vault (also rare, no green cards)
    ALL = 5


class CardRarity(Enum):
    BASIC = 0
    SPECIAL = 1
    COMMON = 2
    UNCOMMON = 3
    RARE = 4
    CURSE = 5


class CardColor(Enum):
    RED = 0
    GREEN = 1
    BLUE = 2
    PURPLE = 3
    COLORLESS = 4
    CURSE = 5
