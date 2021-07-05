import decapitate_the_spire.game as dg

from . import test_utils as tu
from .dungeon_test_case import DungeonTestCase


class TestMiniDungeon(DungeonTestCase):
    def test_run_mini_dungeon(self):
        game = tu.create_game(
            create_dungeon=dg.MiniDungeon,
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10},
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path(0))
        )
        # Play through two fights
        for _ in range(2):
            self.win_simple_fight(game)
            tu.throw_if_step_action_was_illegal(
                game.step(
                    dg.ActionGenerator.pick_specific_combat_reward_type(
                        game.ctx.action_manager.outstanding_request.rewards,
                        dg.GoldRewardItem,
                    )
                )
            )
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_combat_reward())
            )
            tu.throw_if_step_action_was_illegal(
                game.step(
                    dg.ActionGenerator.pick_any_valid_path(
                        game.ctx.action_manager.outstanding_request
                    )
                )
            )

        # Treasure room
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)
        for _ in range(len(request.rewards) - 1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_simple_combat_reward(0))
            )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.end_combat_reward())
        )

        # Boss
        # self.assertIsInstance(game.ctx.action_manager.outstanding_request, BossPathChoiceRequest)
        # throw_if_step_action_was_illegal(game.step(ActionGenerator.proceed_to_boss()))
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.go_to_boss()))
        self.win_simple_fight(game)
        # TODO enable this when ready
        # card_rew_i = next((i for i, rew in enumerate(game.ctx.action_manager.outstanding_request.rewards) if
        #                    isinstance(rew, CardRewardItem)))
        # for c in game.ctx.action_manager.outstanding_request.rewards[card_rew_i].cards:
        #     self.assertEqual(CardRarity.RARE, c.rarity)

        # Boss is dead, proceed past combat reward
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.end_combat_reward())
        )

        # Boss relic
        self.assertIsInstance(game.ctx.d.get_curr_room(), dg.TreasureRoomBoss)
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.BossChestRequest)
        self.assertTrue(
            all((isinstance(rew, dg.RelicRewardItem) for rew in request.rewards))
        )
        # TODO enable this when there's more than one relic
        # throw_if_step_action_was_illegal(game.step(ActionGenerator.pick_simple_combat_reward(2)))

    def test_relic_link(self):
        game = tu.create_game(create_dungeon=dg.MiniDungeon)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_treasure())
        )

        # Treasure room
        self.assert_current_request_is_and_get(game, dg.CombatRewardRequest)

        # Pick the relic
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.pick_specific_combat_reward_type(
                    game.ctx.action_manager.outstanding_request.rewards,
                    dg.RelicRewardItem,
                )
            )
        )
        # Ensure sapphire key isn't pickable
        tu.throw_if_step_action_was_legal(
            game.step(
                dg.ActionGenerator.pick_specific_combat_reward_type(
                    game.ctx.action_manager.outstanding_request.rewards,
                    dg.SapphireKeyRewardItem,
                )
            )
        )

    def test_skip_treasure_room(self):
        game = tu.create_game(create_dungeon=dg.MiniDungeon)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_treasure())
        )

        # Treasure room
        self.assert_current_room_is_and_get(game, dg.TreasureRoom)
        self.assert_current_request_is_and_get(game, dg.CombatRewardRequest)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.end_combat_reward())
        )

    def test_emerald_key(self):
        game = tu.create_game(
            create_dungeon=dg.MiniDungeon,
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10},
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_elite())
        )
        self.win_simple_fight(game)

        self.pick_reward(game, dg.EmeraldKeyRewardItem)

        self.assertTrue(game.ctx.player.has_emerald_key)
        # Emerald key isn't linked to a relic! You get it just for beating a super elite.

    def test_rest_room_rest(self):
        game = tu.create_game(create_dungeon=dg.MiniDungeon)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_rest())
        )

        # Rest room
        self.assert_current_room_is_and_get(game, dg.RestRoom)
        self.assert_current_request_is_and_get(game, dg.CampfireRequest)

        # Pick rest option, damage player first
        game.ctx.player.current_health = 1
        self.pick_campfire_option(game, dg.RestOption)
        self.assertEqual(
            1 + int(0.3 * game.ctx.player.max_health), game.ctx.player.current_health
        )
        self.assert_current_request_is_and_get(game, dg.PathChoiceRequest)

    def test_grid_select_coordinate_transform_roundtrip(self):
        for i in range(dg.MAX_HAND_SIZE * dg.ACTION_1_LEN):
            self.assertEqual(
                i,
                dg.GridSelectRequest.translate_action_to_index(
                    dg.GridSelectRequest.translate_index_to_action(i)
                ),
            )

    def test_rest_room_smith(self):
        game = tu.create_game(create_dungeon=dg.MiniDungeon)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_rest())
        )

        # Rest room
        self.assert_current_room_is_and_get(game, dg.RestRoom)
        self.assert_current_request_is_and_get(game, dg.CampfireRequest)

        # Pick smith option
        self.pick_campfire_option(game, dg.SmithOption)
        self.assert_current_request_is_and_get(game, dg.GridSelectRequest)
        up_card_i = 2
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_grid_select_index(up_card_i))
        )
        self.assertTrue(game.ctx.player.master_deck[up_card_i].upgraded)
        self.assert_current_request_is_and_get(game, dg.PathChoiceRequest)

    def test_event(self):
        game = tu.create_game(create_dungeon=dg.MiniDungeon)

        with tu.SetRestoreEventRng(game, tu.FixedRngRandomFloat(0.99)):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_neow_reward(True))
            )
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_event())
            )

            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_simple_event_choice(0))
            )
            self.assert_current_request_is_and_get(game, dg.PathChoiceRequest)

    def test_shop_bypass(self):
        # TODO This test will break once shop is actually implemented
        game = tu.create_game(create_dungeon=dg.MiniDungeon)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_shop())
        )

        self.assert_current_request_is_and_get(game, dg.PathChoiceRequest)
