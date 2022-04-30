from __future__ import annotations

import logging
import os
from enum import Enum
from typing import (
    Callable,
    List,
    Optional,
    Tuple,
)

from decapitate_the_spire.action import AllFalseActionMask, ActionManager, BossChestRequest
from decapitate_the_spire.character import Player
from decapitate_the_spire.map import MapRoomNode
from decapitate_the_spire.dungeon import Dungeon
from decapitate_the_spire.relic import Relic
from decapitate_the_spire.rng import Rng
from decapitate_the_spire.room import MonsterRoom
from decapitate_the_spire.screen import CombatRewardScreen
from decapitate_the_spire.enums import Screen, RoomPhase

logger = logging.getLogger(__name__)


class GameMode(Enum):
    CHAR_SELECT = 0
    GAMEPLAY = 1
    DUNGEON_TRANSITION = 2


class CCG:
    """CardCrawlGame... the static-est of statics"""

    class Context:
        def __init__(self):
            # noinspection PyTypeChecker
            self.d: Dungeon = None
            self.combat_reward_screen = CombatRewardScreen(self)
            # TODO Source inits this to CHAR_SELECT and calls onEquip on starter relics under that mode
            self.mode = GameMode.CHAR_SELECT

            # This serves the same purpose as source's dungeonTransitionScreen. In source, it starts as the equivalent of False,
            # but I suspect I can get away with initing it True to avoid replicating source's convoluted init.
            self.is_transitioning_dungeon = True
            # I'm patching over all of source's convoluted init with this. Maybe this is good enough?
            # is_very_beginning = True

            # Source sets this as a static on dungeon, but I think we have to put it here because of how python statics work.
            # TODO consolidate this with our dungeon's player
            # noinspection PyTypeChecker
            self.player: Player = None
            self.create_dungeon: Optional[Callable[[Player], Dungeon]] = None
            self.screen = Screen.NONE
            self.action_manager = ActionManager(self)

            self.monster_hp_rng = Rng()
            self.ai_rng = Rng()
            self.shuffle_rng = Rng()
            self.card_rng = Rng()
            self.card_random_rng = Rng()
            self.misc_rng = Rng()
            self.map_rng = Rng()
            self.treasure_rng = Rng()
            self.relic_rng = Rng()
            self.potion_rng = Rng()
            self.monster_rng = Rng()
            self.event_rng = Rng()

            # Various things that source sticks on classes statically
            self.blizzard_potion_mod = 0

        def is_screen_up(self):
            return self.action_manager.outstanding_request is not None

        def reset(self):
            self.d = None
            self.mode = GameMode.CHAR_SELECT
            self.is_transitioning_dungeon = True
            self.player = None
            self.create_dungeon = None
            self.screen = Screen.NONE

        def update(self) -> bool:
            # TODO woefully incomplete

            # This is not source
            # if self.ctx.is_very_beginning:
            #     self.ctx.is_very_beginning = False

            did_something = False

            if self.mode == GameMode.CHAR_SELECT:
                did_something = True
                # Source creates player here, but we'll assume it's given
                for r in self.player.relics:
                    # I guess we hope this doesn't rely on dungeon being created? Does source make the same assumption?
                    r.on_equip()

                self.mode = GameMode.GAMEPLAY

            elif self.mode == GameMode.GAMEPLAY:

                if self.is_transitioning_dungeon:
                    did_something = True
                    # create dungeon, set on CCG
                    # open map screen if next dungeon not exordium
                    self.is_transitioning_dungeon = False
                    # if self.create_dungeon:
                    #     logger.debug('Using provided create dungeon func')
                    #     self.d = self.create_dungeon(self, self.player)
                    #     self.create_dungeon = None
                    # else:
                    #     logger.debug('Using default dungeon')
                    #     self.d = Exordium(self, self.player)
                else:
                    did_something |= self.d.update()

                # TODO check for dungeon beaten (isDungeonBeaten in source)
            else:
                raise NotImplementedError()

            return did_something

        def on_modify_power(self):
            self.player.hand.apply_powers()
            self.d.get_curr_room().monster_group.apply_powers()


# class RewardType:
#     CARD = 0
#     GOLD = 1
#     RELIC = 2
#     POTION = 3
#     STOLEN_GOLD = 4
#     EMERALD_KEY = 5
#     SAPPHIRE_KEY = 6


Map = List[List[MapRoomNode]]
MapCoord = Tuple[int, int]
ActionCoord = Tuple[int, int]
ActionCoordConsumer = Callable[[ActionCoord], None]
ActionMaskSlices = List[List[bool]]


class Game:
    def __init__(
        self,
        create_player: Callable[[CCG.Context], Player],
        create_dungeon: Callable[[CCG.Context], Dungeon],
        relics: Callable[[CCG.Context], List[Relic]] = None,
    ):
        self.logger = logging.getLogger("dts.Game")
        self.step_has_been_called = False
        self.ctx = CCG.Context()
        # CCG.ctx = self.ctx

        player = create_player(self.ctx)
        self.ctx.player = player
        d = create_dungeon(self.ctx)
        self.ctx.d = d
        # self.ctx.create_dungeon = create_dungeon
        # self.id = uuid.uuid4()

        if relics:
            for r in relics(self.ctx):
                # TODO This probably breaks when we do multi room.
                r.instant_obtain(player, True)

        self.game_over_and_won = None

        # If we model "game start" as going here, I think we look at CardCrawlGame#update, specifically the logic
        # around setting CardCrawlGame#mode from CHAR_SELECT to GAMEPLAY.

        # Is it right to call this now?
        while self.ctx.update():
            ...

        # May not be correct to call this here. The initial nrt call comes from AbstractDungeon#updateFading, via
        # AbstractDungeon#fadeOut, via AbstractDungeon#nextRoomTransitionStart. nrts is called from several spots, like
        # DungeonMap (for going to boss), MapRoomNode (when a room on dungeon map is clicked), and the various "go to X
        # room" methods in ProceedButton.
        # self.dungeon = CCG.ctx.d
        self.history = []

    def __repr__(self):
        if self.game_over_and_won is None:
            room = self.ctx.d.get_curr_room()
            if isinstance(room, MonsterRoom):
                monsters = os.linesep.join([m.__repr__() for m in room.monster_group])
            else:
                monsters = ""

            return f"{self.ctx.player}{os.linesep}{monsters}"
        elif self.game_over_and_won:
            return "Game over: win"
        else:
            return "Game over: loss"

    def step(self, action: ActionCoord) -> Tuple[float, bool, dict]:
        self.step_has_been_called = True
        reward = 0.0
        is_terminal = False
        info = {}

        # Give a reward per floor climbed
        start_floor = self.ctx.d.floor_num
        start_total_monster_health = None
        # # start_monster_health_proportion = None
        if self.ctx.d.get_curr_room().phase == RoomPhase.COMBAT:
            start_total_monster_health = sum([m.current_health for m in self.ctx.d.get_curr_room().monster_group])
            m = self.ctx.d.get_curr_room().monster_group[0]
            # start_monster_health_proportion = m.current_health / m.max_health
        start_player_health = self.ctx.player.current_health

        # Ensure action is valid
        if not self.is_action_valid(action):
            # reward, is_terminal, info = self._pinch(action)
            # logger.debug(f'Rewarding {reward} for illegal move, now {reward}')
            # assert False
            self.history.append((action, "invalid"))
            return self._pinch(action)
        else:
            reward += 0.001
            # Only set response if action is valid, right?
            if self.ctx.action_manager.outstanding_request:
                self.ctx.action_manager.outstanding_request.set_response(action)

            logger.debug("Before dungeon update")
            while self.ctx.update() and not self.ctx.player.is_dead:
                ...
            logger.debug(f"After dungeon update:{os.linesep}{self}")

            # assert CCG.d is self.ctx.d
            # assert CCG.player is self.ctx.player
            if self.ctx.player.is_dead:
                logger.debug("Player is dead, returning loss")
                self.history.append(
                    (action, self.ctx.action_manager.outstanding_request)
                )
                return self._loss()
            elif isinstance(
                self.ctx.action_manager.outstanding_request, BossChestRequest
            ):
                logger.debug("Boss beat, returning win")
                self.history.append(
                    (action, self.ctx.action_manager.outstanding_request)
                )
                return self._win()
            else:
                if self.ctx.action_manager.outstanding_request is None:
                    self.history.append(
                        (action, self.ctx.action_manager.outstanding_request)
                    )
                    print(self.ctx.d)
                    assert False

            if self.ctx.d.floor_num > start_floor:
                # Do it like this for floor skips like secret portal?
                amount = self.ctx.d.floor_num - start_floor
                reward += amount * 3
                logger.debug(f'Rewarding {amount} for floor increment, now {reward}')
            if self.ctx.d.get_curr_room().phase == RoomPhase.COMBAT and start_total_monster_health is not None:
                change_in_health = sum(
                    [m.current_health for m in self.ctx.d.get_curr_room().monster_group]) - start_total_monster_health
                if change_in_health < 0:
                    amount = .002 * abs(change_in_health)
                    reward += amount
                    logger.debug(f'Rewarding {amount} for monster damage, now {reward}')
            player_health_change = self.ctx.player.current_health - start_player_health
            health_change_reward_multiplier = .005
            # health_change_reward_multiplier = 1
            reward += player_health_change * health_change_reward_multiplier

        self.history.append((action, self.ctx.action_manager.outstanding_request))
        return reward, is_terminal, info

    def _win(self):
        print("GAME OVER: WIN")
        self.logger.debug("Game over: WIN")
        self.game_over_and_won = True
        return 100.0, True, {"win": True}

    def _loss(self):
        self.logger.debug("Game over: LOSS")
        self.game_over_and_won = False
        return -100.0, True, {"win": False}

    def _pinch(self, action):
        self.logger.debug(f"Pinching for illegal move: {action}")
        return -0.001, False, {"illegal": True}
        # return -1.0, True, {'illegal': True}

    def generate_action_mask(self) -> List[List[bool]]:
        # Action dim 0: [end turn, play card 0..n, use potion 0..n]
        # Action dim 1: [target 0..n, no target]

        request = self.ctx.action_manager.outstanding_request
        if not request:
            assert self.game_over or not self.step_has_been_called
            return AllFalseActionMask().to_raw()

        action_mask = request.generate_action_mask()
        return action_mask.to_raw()

    def is_action_valid(self, action: ActionCoord) -> bool:
        mask = self.generate_action_mask()
        return mask[action[0]][action[1]]

    @property
    def game_over(self):
        return self.game_over_and_won is not None
