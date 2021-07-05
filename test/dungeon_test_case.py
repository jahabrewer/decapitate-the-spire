import logging
import sys
import unittest
from typing import Tuple, Type

import decapitate_the_spire as dts

from .test_utils import throw_if_step_action_was_illegal


class DungeonTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = logging.StreamHandler(sys.stdout)
        self.handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)-8s - %(funcName)-16s - %(message)s"
            )
        )
        self.logger = logging.getLogger("dts")
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)

    def assert_player_has_power_and_get(
        self,
        game: dts.game.Game,
        power_type: Type[dts.game.Power],
        stack_amount: int = None,
        negate=False,
    ):
        return self.assert_character_has_power_and_get(
            game.ctx.player, power_type, negate, stack_amount
        )

    def assert_first_monster_has_power_and_get(
        self,
        game: dts.game.Game,
        power_type: Type[dts.game.Power],
        stack_amount: int = None,
        negate=False,
    ):
        return self.assert_character_has_power_and_get(
            game.ctx.d.get_curr_room().monster_group[0],
            power_type,
            negate,
            stack_amount,
        )

    def assert_character_has_power_and_get(
        self,
        character: dts.game.Character,
        power_type: Type[dts.game.Power],
        negate: bool,
        stack_amount: int = None,
    ):
        matching_powers = [p for p in character.powers if isinstance(p, power_type)]
        if negate:
            self.assertEqual(0, len(matching_powers))
            p = None
        else:
            self.assertEqual(1, len(matching_powers))
            p = matching_powers[0]

        if stack_amount is not None:
            if negate:
                raise NotImplementedError()
            self.assertEqual(stack_amount, p.amount)
        return p

    def assert_current_request_is_and_get(
        self, game: dts.game.Game, request_type: Type[dts.game.PlayerRequest]
    ):
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, request_type)
        return request

    def assert_current_room_is_and_get(
        self, game: dts.game.Game, room_type: Type[dts.game.Room]
    ):
        room = game.ctx.d.get_curr_room()
        # Check exact type, not isinstance. MonsterRoomBoss would pass as MonsterRoom otherwise.
        self.assertEqual(room_type, type(room))
        return room

    def assert_current_room_phase(self, game: dts.game.Game, phase: dts.game.RoomPhase):
        room = game.ctx.d.get_curr_room()
        self.assertEqual(phase, room.phase)

    def win_simple_fight(self, game: dts.game.Game):
        self.assert_current_request_is_and_get(game, dts.game.CombatActionRequest)
        self.assertTrue(
            all((isinstance(c, dts.game.DebugStrike) for c in game.ctx.player.hand))
        )
        for i in range(len(game.ctx.d.get_curr_room().monster_group)):
            throw_if_step_action_was_illegal(
                game.step(dts.game.ActionGenerator.play_card(0, i))
            )
        self.assertTrue(game.ctx.d.get_curr_room().is_battle_over)

    def pick_reward(self, game: dts.game.Game, reward_type: Type[dts.game.RewardItem]):
        throw_if_step_action_was_illegal(
            game.step(
                dts.game.ActionGenerator.pick_specific_combat_reward_type(
                    game.ctx.action_manager.outstanding_request.rewards, reward_type
                )
            )
        )

    def pick_campfire_option(
        self, game: dts.game.Game, option_type: Type[dts.game.CampfireOption]
    ):
        self.assert_current_request_is_and_get(game, dts.game.CampfireRequest)
        throw_if_step_action_was_illegal(
            game.step(
                dts.game.ActionGenerator.pick_specific_campfire_option(
                    game.ctx.action_manager.outstanding_request.options, option_type
                )
            )
        )

    @classmethod
    def find_first_instance_of_cards(
        cls, cg: dts.game.CardGroup, card_types: Tuple[Type[dts.game.Card]]
    ) -> Tuple[int, dts.game.Card]:
        return next(((i, c) for i, c in enumerate(cg) if isinstance(c, card_types)))

    @classmethod
    def find_first_instance_of_card(
        cls, cg: dts.game.CardGroup, card_type: Type[dts.game.Card]
    ) -> Tuple[int, dts.game.Card]:
        return cls.find_first_instance_of_cards(cg, (card_type,))

    def assert_num_cards_in_hand(
        self, game: dts.game.Game, amount: int, card_type: Type[dts.game.Card] = None
    ):
        return self._assert_num_cards_in_card_group(
            game.ctx.player.hand, amount, card_type
        )

    def assert_num_cards_in_discard(
        self, game: dts.game.Game, amount: int, card_type: Type[dts.game.Card] = None
    ):
        return self._assert_num_cards_in_card_group(
            game.ctx.player.discard_pile, amount, card_type
        )

    def _assert_num_cards_in_card_group(
        self, cg: dts.game.CardGroup, amount: int, card_type: Type[dts.game.Card] = None
    ):
        if card_type is None:
            self.assertEqual(amount, len(cg))
        else:
            self.assertEqual(amount, len([c for c in cg if isinstance(c, card_type)]))

    def assert_player_has_block(self, game: dts.game.Game, amount: int):
        self.assertEqual(amount, game.ctx.player.current_block)

    def assert_first_monster_has_block(self, game: dts.game.Game, amount: int):
        self.assertEqual(
            amount, game.ctx.d.get_curr_room().monster_group[0].current_block
        )

    def assert_player_has_energy(self, game: dts.game.Game, amount: int):
        self.assertEqual(amount, game.ctx.player.energy_manager.player_current_energy)

    def assert_first_monster_intent(self, game: dts.game.Game, intent: dts.game.Intent):
        self.assertEqual(
            intent, game.ctx.d.get_curr_room().monster_group[0].next_move.get_intent()
        )

    def assert_first_monster_move(
        self, game: dts.game.Game, move_name: dts.game.MoveName
    ):
        self.assertEqual(
            move_name, game.ctx.d.get_curr_room().monster_group[0].next_move_name
        )

    def assert_first_monster_move_not(
        self, game: dts.game.Game, move_name: dts.game.MoveName
    ):
        self.assertNotEqual(
            move_name, game.ctx.d.get_curr_room().monster_group[0].next_move_name
        )

    def assert_num_alive_monsters(
        self, game: dts.game.Game, num: int, monster_type: Type[dts.game.Monster] = None
    ):
        alive_monsters = [
            m
            for m in game.ctx.d.get_curr_room().monster_group
            if not m.is_dead_or_escaped()
        ]
        self.assertEqual(num, len(alive_monsters))
        if monster_type:
            self.assertTrue(all((isinstance(m, monster_type) for m in alive_monsters)))

    def find_first_instance_of_monster(
        self, game: dts.game.Game, monster_type: Type[dts.game.Monster]
    ):
        return next(
            (
                m
                for m in game.ctx.d.get_curr_room().monster_group
                if isinstance(m, monster_type)
            )
        )

    def assert_player_gold(self, game: dts.game.Game, amount: int):
        self.assertEqual(amount, game.ctx.player.gold)
