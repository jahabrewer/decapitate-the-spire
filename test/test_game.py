import collections
from typing import Callable

import decapitate_the_spire as dts
import decapitate_the_spire.game as dg

from . import test_utils as tu
from .dungeon_test_case import DungeonTestCase


class TestGame(DungeonTestCase):
    @staticmethod
    def _create_game_and_end_turn(monster: Callable[[dg.CCG.Context], dg.Monster]):
        game = tu.create_game(monster=monster)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        return game

    @staticmethod
    def _create_game_and_nav_to_first_exordium_fight(**kwargs):
        game = tu.create_game(create_dungeon=dg.Exordium, **kwargs)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        first_available_path_index = next(
            (i for i, node in enumerate(game.ctx.d.mapp[0]) if node.has_edges())
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path(first_available_path_index))
        )

        return game

    def test_create(self):
        game = tu.create_game()

        self.assertEqual(tu.default_player_max_health, game.ctx.player.current_health)
        self.assertEqual(
            tu.default_energy_per_turn, game.ctx.player.energy_manager.energy_master
        )
        for monster in game.ctx.d.get_curr_room().monster_group:
            self.assertEqual(tu.default_monster_max_health, monster.current_health)

    def test_play_strike(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Strike.recipe(): 6})

        # Plays first card in hand
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            tu.default_monster_max_health - 6,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(
            tu.default_energy_per_turn - 1,
            game.ctx.player.energy_manager.player_current_energy,
        )

    def test_strike_upgrade(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Strike.recipe(True): 6})
        played_card_index = 0
        played_card = game.ctx.player.hand[played_card_index]

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(played_card_index, 0))
        )

        self.assertEqual(
            tu.default_monster_max_health - played_card.base_damage,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(
            tu.default_energy_per_turn - played_card.cost,
            game.ctx.player.energy_manager.player_current_energy,
        )

    def test_game_ends_if_player_dead(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, 100, damage_amount=100)
        )

        reward, is_terminal, info = tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.end_turn())
        )

        self.assertTrue(is_terminal)
        self.assertLess(reward, 0)
        self.assertFalse(game.game_over_and_won)

    def test_battle_ends_if_monster_dead(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, 1, damage_amount=1),
            initial_draw_pile_manifest={dg.Strike.recipe(): 6},
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertTrue(game.ctx.d.get_curr_room().is_battle_over)
        self.assertFalse(game.ctx.player.is_dead)
        self.assertTrue(game.ctx.d.get_curr_room().monster_group.are_monsters_dead())

    def test_player_loses_block_after_turn_end(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Defend.recipe(): 10})

        # Play 3 defends
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        # End turn
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(0, game.ctx.player.current_block)

    def test_exhaust(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Backstab.recipe(): 10})

        # Play a backstab
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(1, len(game.ctx.player.exhaust_pile))
        self.assertIsInstance(game.ctx.player.exhaust_pile[0], dg.Backstab)

    def test_innate(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Strike.recipe(): 10, dg.Backstab.recipe(): 1}
        )

        self.assertIsInstance(game.ctx.player.hand[0], dg.Backstab)

    def test_backstab(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Backstab.recipe(): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            tu.default_monster_max_health - 11,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_backstab_upgrade(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Backstab.recipe(True): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            tu.default_monster_max_health - game.ctx.player.hand[0].base_damage,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_weak_lowers_damage(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
            monster=lambda ctx: dg.AlwaysWeakenMonster(
                ctx, tu.default_monster_max_health
            ),
        )

        # End turn so monster weakens player
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        # Play a strike
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        damage_to_monster_expected = int(6 * dg.WeakPower.damage_multiplier)
        self.assertEqual(
            tu.default_monster_max_health - damage_to_monster_expected,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_card_discards_after_play(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Strike.recipe(): 10})

        # Play strike
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(1, len(game.ctx.player.discard_pile))
        self.assertIsInstance(game.ctx.player.discard_pile[0], dg.Strike)

    def test_acid_slime_m_cant_tackle_consecutively(self):
        move_rng_overrides = collections.deque([69] * 3)
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Defend.recipe(): 10},
            monster=lambda ctx: dg.AcidSlimeM(
                ctx, move_rng_overrides=move_rng_overrides
            ),
        )

        self.assert_first_monster_move(game, dg.MoveName.TACKLE)
        # End turn, monster tackles
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_first_monster_move_not(game, dg.MoveName.TACKLE)

    def test_player_energy_reset_after_end_turn(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Defend.recipe(): 10})

        # Play defend
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        self.assertEqual(
            tu.default_energy_per_turn - 1,
            game.ctx.player.energy_manager.player_current_energy,
        )

        # End turn
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(
            tu.default_energy_per_turn,
            game.ctx.player.energy_manager.player_current_energy,
        )

    def test_powers_stack_in_single_instance(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Defend.recipe(): 10},
            monster=lambda ctx: dg.AlwaysWeakenMonster(ctx, 1),
        )

        # Monster weakens once
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        # Monster weakens again
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(1, len(game.ctx.player.powers))
        self.assertIsInstance(game.ctx.player.powers[0], dg.WeakPower)
        self.assertEqual(3, game.ctx.player.powers[0].amount)

    def test_power_deletes_when_stacks_down_to_zero(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.DeadlyPoison.recipe(): 10})
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        for _ in range(5):
            self.assertIsInstance(
                game.ctx.d.get_curr_room().monster_group[0].powers[0], dg.PoisonPower
            )
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assertEqual(0, len(game.ctx.d.get_curr_room().monster_group[0].powers))
        self.assertEqual(
            tu.default_monster_max_health - 5 * 6 / 2,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_snake_ring(self):
        game = tu.create_game()

        self.assertEqual(game.ctx.player.game_hand_size + 2, len(game.ctx.player.hand))

    def test_akabeko(self):
        monster_max_health = 100
        game = tu.create_game(
            relics=lambda ctx: [dg.Akabeko(ctx)],
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
            monster_hp=monster_max_health,
        )

        # Play dtsgame.Strike
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assertEqual(
            monster_max_health - 6 - dg.Akabeko.amount,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

        # Play dtsgame.Strike again
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assertEqual(
            monster_max_health - 2 * 6 - dg.Akabeko.amount,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_pick_single_discard_from_hand(self):
        num_total_cards = 10
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Survivor.recipe(): num_total_cards},
            monster=lambda ctx: dg.AlwaysWeakenMonster(ctx, 1),
        )

        original_hand_size = len(game.ctx.player.hand)

        # Play Survivor
        reward, is_terminal, _ = tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        # Ensure game is waiting for player to choose a card to discard
        self.assertFalse(is_terminal)
        self.assert_current_request_is_and_get(game, dg.DiscardRequest)
        energy_after_playing_card = game.ctx.player.energy_manager.player_current_energy

        # Choose the second card in hand
        reward, is_terminal, _ = tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(1))
        )

        # Ensure the played card and the chosen card to discard are in discard
        self.assertFalse(is_terminal)
        self.assertEqual(0, len(game.ctx.player.exhaust_pile))
        self.assertEqual(2, len(game.ctx.player.discard_pile))
        self.assertEqual(original_hand_size - 2, len(game.ctx.player.hand))
        self.assertEqual(num_total_cards, game.ctx.player.get_total_card_count())
        self.assert_current_request_is_and_get(game, dg.CombatActionRequest)
        self.assertEqual(
            energy_after_playing_card,
            game.ctx.player.energy_manager.player_current_energy,
        )

    def test_survivor(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Survivor.recipe(): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(1))
        )

        self.assertEqual(
            game.ctx.player.hand[0].base_block, game.ctx.player.current_block
        )

    def test_survivor_upgrade(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Survivor.recipe(True): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(1))
        )

        self.assertEqual(
            game.ctx.player.hand[0].base_block, game.ctx.player.current_block
        )

    def test_neutralize(self):
        monster_attack_amount = 10
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Neutralize.recipe(): 10},
            monster=lambda ctx: dg.AlwaysAttackMonster(
                ctx, tu.default_monster_max_health, monster_attack_amount
            ),
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        monster = game.ctx.d.get_curr_room().monster_group[0]
        self.assertEqual(
            tu.default_monster_max_health - dg.Neutralize.base_damage_master,
            monster.current_health,
        )
        self.assertEqual(1, len(monster.powers))
        self.assertIsInstance(monster.powers[0], dg.WeakPower)
        self.assertEqual(
            monster.powers[0].amount, dg.Neutralize.base_magic_number_master
        )

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(
            tu.default_player_max_health
            - int(monster_attack_amount * dg.WeakPower.damage_multiplier),
            game.ctx.player.current_health,
        )

    def test_neutralize_upgrade(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Neutralize.recipe(True): 10}
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        monster = game.ctx.d.get_curr_room().monster_group[0]
        self.assertIsInstance(monster.powers[0], dg.WeakPower)
        self.assertEqual(2, monster.powers[0].amount)

    def test_energy_potion(self):
        game = tu.create_game(potions=lambda ctx: [dg.EnergyPotion(ctx)])

        # Use potion 0
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.use_potion(0, None))
        )

        self.assertEqual(
            tu.default_energy_per_turn + 2,
            game.ctx.player.energy_manager.player_current_energy,
        )
        self.assertEqual(0, len(game.ctx.player.potions))

    def test_alchemize(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Alchemize.recipe(): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(1, len(game.ctx.player.potions))

    def test_alchemize_upgrade(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Alchemize.recipe(True): 10}
        )
        energy_before_playing = game.ctx.player.energy_manager.player_current_energy

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(1, len(game.ctx.player.potions))
        self.assertEqual(
            energy_before_playing - 0,
            game.ctx.player.energy_manager.player_current_energy,
        )

    def test_attack_second_monster(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.AlwaysAttackMonster(ctx, tu.default_monster_max_health, 1),
                    dg.AlwaysAttackMonster(ctx, tu.default_monster_max_health, 1),
                ],
            ),
        )
        attacked_monster_index = 1

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, attacked_monster_index))
        )

        self.assertEqual(
            tu.default_monster_max_health - 6,
            game.ctx.d.get_curr_room()
            .monster_group[attacked_monster_index]
            .current_health,
        )
        self.assertEqual(
            tu.default_monster_max_health,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_battle_ends_only_when_all_monsters_dead(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [dg.AlwaysAttackMonster(ctx, 1, 1), dg.AlwaysAttackMonster(ctx, 1, 1)],
            ),
        )

        # Kill monster 1
        reward, is_terminal, info = tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 1))
        )

        self.assertFalse(is_terminal)
        self.assertFalse(game.ctx.d.get_curr_room().monster_group.are_monsters_dead())

        # Kill monster 0
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertTrue(game.ctx.d.get_curr_room().is_battle_over)
        self.assertTrue(game.ctx.d.get_curr_room().monster_group.are_monsters_dead())

    def test_player_attacked_by_three_monsters(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                ],
            ),
        )

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(
            tu.default_player_max_health - 3, game.ctx.player.current_health
        )

    def test_fire_potion(self):
        monster_hp = 30
        game = tu.create_game(
            potions=lambda ctx: [
                dg.FirePotion(
                    ctx,
                )
            ],
            monster=lambda ctx: dg.SimpleMonster(ctx, 30, 1, 1),
        )

        # Use potion 0
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.use_potion(0, 0))
        )

        self.assertEqual(
            monster_hp - 20, game.ctx.d.get_curr_room().monster_group[0].current_health
        )
        self.assertEqual(0, len(game.ctx.player.potions))

    def test_use_potion_on_second_monster(self):
        attacked_monster_index = 1
        game = tu.create_game(
            potions=lambda ctx: [
                dg.FirePotion(
                    ctx,
                )
            ],
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                ],
            ),
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.use_potion(0, attacked_monster_index))
        )

        self.assertEqual(
            tu.default_monster_max_health - 20,
            game.ctx.d.get_curr_room()
            .monster_group[attacked_monster_index]
            .current_health,
        )
        self.assertEqual(0, len(game.ctx.player.potions))

    def test_concentrate(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Concentrate.recipe(): 10})
        hand_size_before_play = len(game.ctx.player.hand)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        # Check that game goes into request mode
        self.assertIsNotNone(game.ctx.action_manager.outstanding_request)
        # Ensure the played card is out of hand for the discard picking
        self.assertEqual(hand_size_before_play - 1, len(game.ctx.player.hand))

        # Pick 3 cards to discard
        discarded_indexes = [3, 1, 0]
        discarded_uuids = [game.ctx.player.hand[i].uuid for i in discarded_indexes]
        for i in discarded_indexes:
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_discard_from_hand(i))
            )

        self.assertEqual(hand_size_before_play - 4, len(game.ctx.player.hand))
        self.assertEqual(4, len(game.ctx.player.discard_pile))
        for discarded_uuid in discarded_uuids:
            self.assertNotIn(discarded_uuid, [c.uuid for c in game.ctx.player.hand])
            self.assertIn(
                discarded_uuid, [c.uuid for c in game.ctx.player.discard_pile]
            )

    # def test_concentrate_upgrade(self):
    #     game = tu.create_game(initial_draw_pile_manifest={dg.Concentrate.recipe(True): 10})
    #     tu.throw_if_step_action_was_illegal(game.step(dtsgame.ActionGenerator.play_card(0, None)))
    #     not_upgraded_magic_number = Concentrate.base_magic_number_master
    #     upgraded_magic_number = Concentrate.recipe(True).magic_number
    #     self.assertLess(upgraded_magic_number, not_upgraded_magic_number)
    #
    #     for i in range(upgraded_magic_number):
    #         tu.throw_if_step_action_was_illegal(game.step(dtsgame.ActionGenerator.pick_discard_from_hand(i)))
    #
    #     # Check that game is not in request mode
    #     self.assert_current_request_is_and_get(game, dg.CombatActionRequest)

    def test_picking_same_card_twice_for_discard_is_illegal(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Concentrate.recipe(): 10})
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        index = 1
        _, is_terminal, info = tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(index))
        )
        self.assertFalse(is_terminal)
        self.assertNotIn("illegal", info)
        _, is_terminal, info = game.step(
            dg.ActionGenerator.pick_discard_from_hand(index)
        )
        # self.assertFalse(is_terminal)
        self.assertTrue(info["illegal"])

    def test_all_out_attack(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.AllOutAttack.recipe(): 10},
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.AlwaysAttackMonster(ctx, tu.default_monster_max_health, 1),
                    dg.AlwaysAttackMonster(ctx, tu.default_monster_max_health, 1),
                ],
            ),
        )
        randomly_discarded_card_index = 2
        randomly_discarded_card_uuid = game.ctx.player.hand[
            randomly_discarded_card_index
        ].uuid

        with tu.SetRestoreCardRandomRng(
            game, tu.FixedRng(randomly_discarded_card_index)
        ):
            # Pick past the card we'll discard so the index isn't affected.
            tu.throw_if_step_action_was_illegal(
                game.step(
                    dg.ActionGenerator.play_card(
                        randomly_discarded_card_index + 1, None
                    )
                )
            )

        for m in game.ctx.d.get_curr_room().monster_group:
            self.assertEqual(
                tu.default_monster_max_health - dg.AllOutAttack.base_damage_master,
                m.current_health,
            )
        self.assertIn(
            randomly_discarded_card_uuid, [c.uuid for c in game.ctx.player.discard_pile]
        )
        self.assertEqual(2, len(game.ctx.player.discard_pile))

    def test_all_out_attack_upgrade(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.AllOutAttack.recipe(True): 10}
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(
            tu.default_monster_max_health - 14,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_gambling_chip_pick_none(self):
        game = tu.create_game(
            relics=lambda ctx: [
                dg.GamblingChip(
                    ctx,
                )
            ]
        )

        # Assert that game is waiting for player's discard picks
        self.assert_current_request_is_and_get(game, dg.DiscardRequest)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.done_picking_discards())
        )

        # Assert that game is not waiting for player's discard picks
        self.assert_current_request_is_and_get(game, dg.CombatActionRequest)
        self.assertEqual(
            game.ctx.player.game_hand_size + dg.SnakeRing.magic_number,
            len(game.ctx.player.hand),
        )

    def test_gambling_chip_pick_two(self):
        game = tu.create_game(
            relics=lambda ctx: [
                dg.GamblingChip(
                    ctx,
                )
            ]
        )

        # Assert that game is waiting for player's discard picks
        self.assert_current_request_is_and_get(game, dg.DiscardRequest)

        discarded_indexes = [1, 3]
        discarded_uuids = [game.ctx.player.hand[i].uuid for i in discarded_indexes]
        for i in discarded_indexes:
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_discard_from_hand(i))
            )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.done_picking_discards())
        )

        # Assert that game is not waiting for player's discard picks
        self.assert_current_request_is_and_get(game, dg.CombatActionRequest)
        self.assertEqual(
            game.ctx.player.game_hand_size
            + dg.SnakeRing.magic_number
            - len(discarded_indexes),
            len(game.ctx.player.hand),
        )
        for discarded_uuid in discarded_uuids:
            self.assertIn(
                discarded_uuid, [c.uuid for c in game.ctx.player.discard_pile]
            )

    def test_damage_type_hp_loss(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Defend.recipe(True): 10})
        # Get some block
        for _ in range(2):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )
        # This is a bit hacky
        game.ctx.action_manager.add_to_top(
            dg.LoseHPAction(
                game.ctx, game.ctx.player, game.ctx.player, tu.default_player_max_health
            )
        )

        # Player should be dead after all actions handled
        reward, is_terminal, info = tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(0, game.ctx.player.current_health)
        self.assertTrue(is_terminal)
        self.assertFalse(info["win"])

    def test_reptomancer_spawn_low_asc(self):
        game = tu.create_game(monster=lambda ctx: dg.Reptomancer(ctx))

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(2, len(game.ctx.d.get_curr_room().monster_group))
        self.assertIsInstance(
            game.ctx.d.get_curr_room().monster_group[0], dg.SnakeDagger
        )
        self.assertEqual(tu.default_player_max_health, game.ctx.player.current_health)

    def test_reptomancer_daggers_self_destruct(self):
        # Forbid Reptomancer from spawning daggers after first turn
        move_overrides = [None, dg.MoveName.SNAKE_STRIKE, dg.MoveName.SNAKE_STRIKE]
        game = tu.create_game(
            monster=lambda ctx: dg.Reptomancer(ctx, move_overrides=move_overrides),
            player_hp=999,
        )
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        # Daggers spawned
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        # Daggers have attacked first time

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        # Daggers should have self destructed

        self.assertEqual(
            1,
            len(
                [
                    m
                    for m in game.ctx.d.get_curr_room().monster_group
                    if not m.is_dying and not m.is_dead
                ]
            ),
        )

    # def test_reptomancer_spawn_high_asc(self):
    #     with SetRestoreAscension(20):
    #         game = tu.create_game(monster=lambda ctx:dg.Reptomancer(ctx))
    #
    #         tu.throw_if_step_action_was_illegal(game.step(dtsgame.ActionGenerator.end_turn()))
    #
    #         self.assertEqual(3, len(game.ctx.d.get_curr_room().monster_group))
    #         for i in range(2):
    #             self.assertIsInstance(game.ctx.d.get_curr_room().monster_group[i], dg.SnakeDagger)
    #         self.assertEqual(tu.default_player_max_health, game.ctx.player.current_health)

    def test_game_ends_when_only_minions_alive(self):
        game = tu.create_game(
            monster=lambda ctx: dg.Reptomancer(ctx),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10},
        )
        # Let reptomancer spawn daggers
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assertGreater(len(game.ctx.d.get_curr_room().monster_group), 1)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 1))
        )

        self.assertTrue(game.ctx.d.get_curr_room().is_battle_over)
        self.assertFalse(game.ctx.player.is_dead)
        self.assertTrue(game.ctx.d.get_curr_room().monster_group.are_monsters_dead())

    def test_cannot_target_dead_minion(self):
        game = tu.create_game(
            monster=lambda ctx: dg.Reptomancer(ctx),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10},
        )
        # Spawn dagger
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        dagger_index, dagger = next(
            (
                (i, m)
                for i, m in enumerate(game.ctx.d.get_curr_room().monster_group)
                if isinstance(m, dg.SnakeDagger)
            )
        )
        # Kill the dagger
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, dagger_index))
        )
        self.assertTrue(dagger.is_dead or dagger.is_dying)

        # Use card on (dead) dagger
        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.play_card(0, dagger_index))
        )

    def test_discard_potion(self):
        game = tu.create_game(potions=lambda ctx: [dg.FirePotion(ctx)])

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.discard_potion(0))
        )

        self.assertEqual(0, len(game.ctx.player.potions))

    def test_cannot_play_status_card(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Wound.recipe(): 10})

        for i in range(dts.game.MAX_NUM_MONSTERS_IN_GROUP):
            tu.throw_if_step_action_was_legal(
                game.step(dg.ActionGenerator.play_card(0, i))
            )
        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

    def test_retain(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Smite.recipe(): 10})

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(10, len(game.ctx.player.hand))

    def test_bottled_flame(self):
        game = tu.create_game(
            initial_draw_pile_manifest={
                dg.Defend.recipe(): 100,
                dg.Strike.recipe(bottle=True): 1,
            }
        )

        self.assertIsInstance(game.ctx.player.hand[0], dg.Strike)

    def test_bottled_tornado(self):
        game = tu.create_game(
            initial_draw_pile_manifest={
                dg.Defend.recipe(): 100,
                dg.Footwork.recipe(bottle=True): 1,
            }
        )

        self.assertIsInstance(game.ctx.player.hand[0], dg.Footwork)

    def test_bottled_lightning(self):
        game = tu.create_game(
            initial_draw_pile_manifest={
                dg.Strike.recipe(): 100,
                dg.Defend.recipe(bottle=True): 1,
            }
        )

        self.assertIsInstance(game.ctx.player.hand[0], dg.Defend)

    def test_x_cost_uses_all_energy(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Skewer.recipe(): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(0, game.ctx.player.energy_manager.player_current_energy)

    def test_can_play_x_cost_on_zero_energy(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Skewer.recipe(): 1, dg.Defend.recipe(): 6}
        )
        _, skewer = self.find_first_instance_of_card(game.ctx.player.hand, dg.Skewer)
        # Play 3 defends to get energy to 0
        for _ in range(3):
            tu.throw_if_step_action_was_illegal(
                game.step(
                    dg.ActionGenerator.play_first_card_of_type(
                        game.ctx.player.hand, dg.Defend, None
                    )
                )
            )
        self.assertEqual(0, game.ctx.player.energy_manager.player_current_energy)

        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.play_first_card_of_type(
                    game.ctx.player.hand, dg.Skewer, 0
                )
            )
        )

        self.assertEqual(
            tu.default_monster_max_health,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertIn(skewer.uuid, [c.uuid for c in game.ctx.player.discard_pile])
        self.assertEqual(3, len(game.ctx.player.hand))

    def test_skewer(self):
        monster_max_health = 100
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Skewer.recipe(): 10},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, monster_max_health, 1),
        )
        energy_available = game.ctx.player.energy_manager.player_current_energy
        self.assertEqual(3, energy_available)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            monster_max_health - (energy_available * 7),
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(0, game.ctx.player.energy_manager.player_current_energy)

    def test_skewer_upgrade(self):
        monster_max_health = 100
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Skewer.recipe(True): 10},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, monster_max_health, 1),
        )
        energy_available = game.ctx.player.energy_manager.player_current_energy
        self.assertEqual(3, energy_available)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            monster_max_health
            - (energy_available * game.ctx.player.hand[0].base_damage),
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(0, game.ctx.player.energy_manager.player_current_energy)

    def test_glass_knife(self):
        monster_max_health = 100
        game = tu.create_game(
            initial_draw_pile_manifest={dg.GlassKnife.recipe(): 10},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, monster_max_health, 1),
        )
        card_i, card = self.find_first_instance_of_card(
            game.ctx.player.hand, dg.GlassKnife
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(card_i, 0))
        )

        self.assertEqual(
            monster_max_health - (2 * dg.GlassKnife.base_damage_master),
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(
            dg.GlassKnife.base_damage_master + dg.GlassKnife.base_damage_change_per_use,
            card.base_damage,
        )

    def test_glass_knife_upgrade(self):
        monster_max_health = 100
        game = tu.create_game(
            initial_draw_pile_manifest={dg.GlassKnife.recipe(True): 10},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, monster_max_health, 1),
        )
        card_i, card = self.find_first_instance_of_card(
            game.ctx.player.hand, dg.GlassKnife
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(card_i, 0))
        )

        self.assertEqual(
            monster_max_health
            - (
                2
                * (
                    dg.GlassKnife.base_damage_master
                    + dg.GlassKnife.damage_upgrade_amount
                )
            ),
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(
            dg.GlassKnife.base_damage_master
            + dg.GlassKnife.damage_upgrade_amount
            + dg.GlassKnife.base_damage_change_per_use,
            card.base_damage,
        )

    def test_glass_knife_stops_decrementing_at_zero_damage(self):
        monster_max_health = 100
        game = tu.create_game(
            initial_draw_pile_manifest={dg.GlassKnife.recipe(): 1},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, monster_max_health, 1),
        )
        _, card = self.find_first_instance_of_card(game.ctx.player.hand, dg.GlassKnife)
        expected_damage = 2 * 8 + 2 * 6 + 2 * 4 + 2 * 2

        for _ in range(5):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assertEqual(
            monster_max_health - expected_damage,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )
        self.assertEqual(0, card.base_damage)

    def test_acrobatics(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Acrobatics.recipe(): 10})
        initial_hand_size = len(game.ctx.player.hand)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(0))
        )

        # Expect that Acrobatics drew 3, then discarded itself and then picked card (-2)
        self.assertEqual(
            initial_hand_size + dg.Acrobatics.base_magic_number_master - 2,
            len(game.ctx.player.hand),
        )
        # Ensure game isn't waiting for more discards by seeing if it's legal to play a card
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

    def test_acrobatics_upgrade(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Acrobatics.recipe(True): 20}
        )
        initial_hand_size = len(game.ctx.player.hand)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(0))
        )

        # Expect that Acrobatics drew 3+1, then discarded itself and then picked card (-2)
        self.assertEqual(
            initial_hand_size
            + dg.Acrobatics.base_magic_number_master
            + dg.Acrobatics.magic_number_upgrade_amount
            - 2,
            len(game.ctx.player.hand),
        )
        # Ensure game isn't waiting for more discards by seeing if it's legal to play a card
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

    def test_backflip(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Backflip.recipe(): 10})
        initial_hand_size = len(game.ctx.player.hand)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(dg.Backflip.base_block_master, game.ctx.player.current_block)
        self.assertEqual(
            initial_hand_size + dg.Backflip.draw_amount - 1, len(game.ctx.player.hand)
        )

    def test_backflip_upgrade(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Backflip.recipe(True): 10})
        initial_hand_size = len(game.ctx.player.hand)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(
            dg.Backflip.base_block_master + dg.Backflip.block_upgrade_amount,
            game.ctx.player.current_block,
        )
        self.assertEqual(
            initial_hand_size + dg.Backflip.draw_amount - 1, len(game.ctx.player.hand)
        )

    def test_deadly_poison(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.DeadlyPoison.recipe(): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        p = game.ctx.d.get_curr_room().monster_group[0].powers[0]
        self.assertIsInstance(p, dg.PoisonPower)
        self.assertEqual(5, p.amount)

    def test_deadly_poison_upgrade(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.DeadlyPoison.recipe(True): 10}
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        p = game.ctx.d.get_curr_room().monster_group[0].powers[0]
        self.assertIsInstance(p, dg.PoisonPower)
        self.assertEqual(7, p.amount)

    def test_poison_decrements_after_end_turn(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.DeadlyPoison.recipe(): 10})
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        p = game.ctx.d.get_curr_room().monster_group[0].powers[0]
        self.assertIsInstance(p, dg.PoisonPower)
        self.assertEqual(5 - 1, p.amount)
        self.assertEqual(
            tu.default_monster_max_health - 5,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_bane_on_poisoned_monster(self):
        game = tu.create_game(
            initial_draw_pile_manifest={
                dg.DeadlyPoison.recipe(): 1,
                dg.Bane.recipe(): 4,
            }
        )
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.play_first_card_of_type(
                    game.ctx.player.hand, dg.DeadlyPoison, 0
                )
            )
        )

        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.play_first_card_of_type(
                    game.ctx.player.hand, dg.Bane, 0
                )
            )
        )

        self.assertEqual(
            tu.default_monster_max_health - 2 * dg.Bane.base_damage_master,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_bane_on_not_poisoned_monster(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Bane.recipe(): 4})

        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.play_first_card_of_type(
                    game.ctx.player.hand, dg.Bane, 0
                )
            )
        )

        self.assertEqual(
            tu.default_monster_max_health - dg.Bane.base_damage_master,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_spike_slime_s(self):
        game = self._create_game_and_end_turn(dg.SpikeSlimeS)

        self.assertEqual(
            tu.default_player_max_health - 5, game.ctx.player.current_health
        )

    def test_spike_slime_m(self):
        game = self._create_game_and_end_turn(
            lambda ctx: dg.SpikeSlimeM(ctx, move_overrides=[dg.MoveName.FLAME_TACKLE])
        )

        self.assertEqual(
            tu.default_player_max_health - 8, game.ctx.player.current_health
        )
        self.assert_num_cards_in_discard(game, 1, dg.Slimed)

    def test_frail(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SpikeSlimeM(ctx, move_overrides=[dg.MoveName.LICK]),
            initial_draw_pile_manifest={dg.Defend.recipe(): 10},
        )
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_power_and_get(game, dg.FrailPower, 1)

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(
            int(dg.FrailPower.block_multiplier * dg.Defend.base_block_master),
            game.ctx.player.current_block,
        )

    def test_strike_requires_target(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Strike.recipe(): 10})

        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

    def test_defend_forbids_target(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Defend.recipe(): 10})

        tu.throw_if_step_action_was_legal(game.step(dg.ActionGenerator.play_card(0, 0)))

    def test_ethereal(self):
        game = tu.create_game(
            initial_draw_pile_manifest={
                dg.Defend.recipe(): 4,
                dg.AscendersBane.recipe(): 1,
            }
        )
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(1, len(game.ctx.player.exhaust_pile))
        self.assertIsInstance(game.ctx.player.exhaust_pile[0], dg.AscendersBane)

    def test_exordium(self):
        game = self._create_game_and_nav_to_first_exordium_fight()

        # noinspection PyTypeChecker
        targetable_i, targetable_card = self.find_first_instance_of_cards(
            game.ctx.player.hand, (dg.Strike, dg.Neutralize)
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(targetable_i, 0))
        )

    def test_can_target_second_monster(self):
        game = tu.create_game(
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.AcidSlimeM(
                        ctx,
                    ),
                    dg.AcidSlimeM(
                        ctx,
                    ),
                ],
            ),
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 1))
        )

    def test_damage_intent_updates_after_power_applied(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, 10, 8),
            initial_draw_pile_manifest={dg.Neutralize.recipe(): 10},
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(6, game.ctx.d.get_curr_room().monster_group[0].intent_damage)

    def test_slimed_exhausts(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Slimed.recipe(): 10})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assertEqual(1, len(game.ctx.player.exhaust_pile))

    def test_combat_reward_gold(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )
        starting_gold = game.ctx.player.gold

        self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        # Find gold reward, ensure only one
        gold_rewards_and_indexes = [
            (i, rew)
            for i, rew in enumerate(request.rewards)
            if isinstance(rew, dg.GoldRewardItem)
        ]
        self.assertEqual(1, len(gold_rewards_and_indexes))
        gold_rew_i, gold_rew = gold_rewards_and_indexes[0]

        # Pick the reward
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_simple_combat_reward(gold_rew_i))
        )
        self.assertEqual(starting_gold + gold_rew.total_gold, game.ctx.player.gold)

    def test_combat_reward_potion(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )

        # Ensure we roll a potion reward at battle end
        with tu.SetRestorePotionRng(game, tu.FixedRng(0)):
            self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        # Find potion reward, ensure only one
        potion_rewards_and_indexes = [
            (i, rew)
            for i, rew in enumerate(request.rewards)
            if isinstance(rew, dg.PotionRewardItem)
        ]
        self.assertEqual(1, len(potion_rewards_and_indexes))
        potion_rew_i, potion_rew = potion_rewards_and_indexes[0]

        # Pick the reward
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_simple_combat_reward(potion_rew_i))
        )
        self.assertEqual(1, len(game.ctx.player.potions))
        self.assertIsInstance(game.ctx.player.potions[0], type(potion_rew.potion))

    def test_combat_reward_pick_two_and_proceed(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )

        # Ensure we roll a potion reward at battle end
        with tu.SetRestorePotionRng(game, tu.FixedRng(0)):
            self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        # Pick two rewards
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.pick_specific_combat_reward_type(
                    request.rewards, dg.GoldRewardItem
                )
            )
        )
        self.assertGreater(game.ctx.player.gold, 0)
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.pick_specific_combat_reward_type(
                    request.rewards, dg.PotionRewardItem
                )
            )
        )
        self.assertEqual(1, len(game.ctx.player.potions))
        # Proceed
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.end_combat_reward())
        )

        # Ensure game requests a path choice
        path_choice_req = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(path_choice_req, dg.PathChoiceRequest)
        # Choose a path
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_any_valid_path(path_choice_req))
        )

    def test_combat_reward_card(self):
        initial_deck_size = 10
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): initial_deck_size}
        )

        self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        # Find potion reward, ensure only one
        card_rewards_and_indexes = [
            (i, rew)
            for i, rew in enumerate(request.rewards)
            if isinstance(rew, dg.CardRewardItem)
        ]
        self.assertEqual(1, len(card_rewards_and_indexes))
        card_rew_i, card_rew = card_rewards_and_indexes[0]
        self.assertEqual(3, len(card_rew.cards))

        # Try picking a bad index
        bad_card_i = len(card_rew.cards)
        tu.throw_if_step_action_was_legal(
            game.step(
                dg.ActionGenerator.pick_card_combat_reward(card_rew_i, bad_card_i)
            )
        )

        # Pick the reward
        picked_card_i = 1
        picked_card = card_rew.cards[picked_card_i]
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.pick_card_combat_reward(card_rew_i, picked_card_i)
            )
        )
        self.assertEqual(initial_deck_size + 1, len(game.ctx.player.master_deck))
        self.assertIn(picked_card, game.ctx.player.master_deck)
        # self.assertEqual(1, len(
        #     [md_card for md_card in game.ctx.player.master_deck if not isinstance(md_card, dtsgame.DebugStrike)]))

    def test_cannot_pick_out_of_range_combat_reward(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )

        self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        bad_reward_index = len(request.rewards)
        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.pick_simple_combat_reward(bad_reward_index))
        )

    def test_picking_combat_reward_removes_reward_from_rewards(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )
        # starting_gold = game.ctx.player.gold

        self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        # Find gold reward, ensure only one
        gold_rewards_and_indexes = [
            (i, rew)
            for i, rew in enumerate(request.rewards)
            if isinstance(rew, dg.GoldRewardItem)
        ]
        self.assertEqual(1, len(gold_rewards_and_indexes))
        gold_rew_i, gold_rew = gold_rewards_and_indexes[0]

        # Pick the reward
        num_rewards_before_first_pick = len(request.rewards)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_simple_combat_reward(gold_rew_i))
        )
        self.assertEqual(num_rewards_before_first_pick - 1, len(request.rewards))

    def test_cannot_pick_potion_combat_reward_with_no_empty_slots(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10},
            potions=lambda ctx: [
                dg.EnergyPotion(
                    ctx,
                ),
                dg.EnergyPotion(
                    ctx,
                ),
                dg.EnergyPotion(
                    ctx,
                ),
            ],
        )

        # Ensure we roll a potion reward at battle end
        with tu.SetRestorePotionRng(game, tu.FixedRng(0)):
            self.win_simple_fight(game)

        # Monsters should be dead, battle over, combat reward available
        request = game.ctx.action_manager.outstanding_request
        self.assertIsInstance(request, dg.CombatRewardRequest)

        # Find potion reward, ensure only one
        potion_rewards_and_indexes = [
            (i, rew)
            for i, rew in enumerate(request.rewards)
            if isinstance(rew, dg.PotionRewardItem)
        ]
        self.assertEqual(1, len(potion_rewards_and_indexes))
        potion_rew_i, potion_rew = potion_rewards_and_indexes[0]

        # Try to get another potion, which should fail
        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.pick_simple_combat_reward(potion_rew_i))
        )
        self.assertEqual(3, len(game.ctx.player.potions))

    def test_regret(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AlwaysWeakenMonster(ctx, 1),
            initial_draw_pile_manifest={dg.Regret.recipe(): 1, dg.Defend.recipe(): 4},
        )
        initial_hand_size = len(game.ctx.player.hand)
        # Ensure in hand, but not playable
        tu.throw_if_step_action_was_legal(
            game.step(
                dg.ActionGenerator.play_first_card_of_type(
                    game.ctx.player.hand, dg.Regret, None
                )
            )
        )

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(
            tu.default_player_max_health - initial_hand_size,
            game.ctx.player.current_health,
        )

    def test_shiv(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Shiv.recipe(): 8})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            tu.default_monster_max_health - dg.Shiv.base_damage_master,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_shiv_upgraded(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Shiv.recipe(True): 8})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )

        self.assertEqual(
            tu.default_monster_max_health - 6,
            game.ctx.d.get_curr_room().monster_group[0].current_health,
        )

    def test_blade_dance(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.BladeDance.recipe(): 2})

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assert_num_cards_in_hand(game, 3, dg.Shiv)
        self.assert_num_cards_in_hand(game, 4)

    def test_blade_dance_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.BladeDance.recipe(True): 2}
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assert_num_cards_in_hand(game, 4, dg.Shiv)
        self.assert_num_cards_in_hand(game, 5)

    def test_blade_dance_some_into_discard(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.BladeDance.recipe(): 7})

        # Fill hand
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        self.assert_num_cards_in_hand(game, 9)
        self.assert_num_cards_in_hand(game, 3, dg.Shiv)

        # These shivs should overflow hand
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        self.assert_num_cards_in_hand(game, 5, dg.Shiv)
        self.assert_num_cards_in_discard(game, 1, dg.Shiv)
        self.assert_num_cards_in_discard(game, 3)

    def test_cloak_and_dagger(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.CloakAndDagger.recipe(): 2}
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assert_num_cards_in_hand(game, 1, dg.Shiv)
        self.assert_num_cards_in_hand(game, 2)
        self.assert_player_has_block(game, 6)

    def test_cloak_and_dagger_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.CloakAndDagger.recipe(True): 2}
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )

        self.assert_num_cards_in_hand(game, 2, dg.Shiv)
        self.assert_num_cards_in_hand(game, 3)
        self.assert_player_has_block(game, 6)

    def test_dagger_spray(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.DaggerSpray.recipe(): 2})

        with tu.FirstMonsterDamageMonitor(game, 8), tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

    def test_dagger_spray_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.DaggerSpray.recipe(True): 2}
        )

        with tu.FirstMonsterDamageMonitor(game, 12), tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

    def test_dagger_throw(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.DaggerThrow.recipe(): 11})

        with tu.FirstMonsterDamageMonitor(game, 9), tu.HandSizeChangeMonitor(
            game, -1
        ), tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

            self.assert_current_request_is_and_get(game, dg.DiscardRequest)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_discard_from_hand(0))
            )
            self.assert_current_request_is_and_get(game, dg.CombatActionRequest)

    def test_dagger_throw_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.DaggerThrow.recipe(True): 11}
        )

        with tu.FirstMonsterDamageMonitor(game, 12), tu.HandSizeChangeMonitor(
            game, -1
        ), tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

            self.assert_current_request_is_and_get(game, dg.DiscardRequest)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.pick_discard_from_hand(0))
            )
            self.assert_current_request_is_and_get(game, dg.CombatActionRequest)

    def test_deflect(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Deflect.recipe(): 1})

        with tu.EnergyChangeMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

        self.assert_player_has_block(game, 4)

    def test_deflect_upgraded(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Deflect.recipe(True): 1})

        with tu.EnergyChangeMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

        self.assert_player_has_block(game, 7)

    def test_dodge_and_roll(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.DodgeAndRoll.recipe(): 1})

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

        self.assert_player_has_block(game, 4)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 4)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 0)

    def test_dodge_and_roll_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.DodgeAndRoll.recipe(True): 1}
        )

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

        self.assert_player_has_block(game, 6)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 6)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 0)

    def test_dodge_and_roll_with_dexterity(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.DodgeAndRoll.recipe(): 1},
            relics=lambda ctx: [dg.OddlySmoothStone(ctx)],
        )

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )

        self.assert_player_has_block(game, 5)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 5)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 0)

    def test_oddly_smooth_stone(self):
        game = tu.create_game(relics=lambda ctx: [dg.OddlySmoothStone(ctx)])
        dex = self.assert_player_has_power_and_get(game, dg.DexterityPower)
        self.assertEqual(1, dex.amount)

    def test_flying_knee(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.FlyingKnee.recipe(): 1})

        with tu.EnergyChangeMonitor(game, -1), tu.FirstMonsterDamageMonitor(game, 8):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_player_has_power_and_get(game, dg.EnergizedPower, 1)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn + 1)

    def test_flying_knee_multiple(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.FlyingKnee.recipe(): 2})

        with tu.EnergyChangeMonitor(game, -1 * 2), tu.FirstMonsterDamageMonitor(
            game, 8 * 2
        ):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_player_has_power_and_get(game, dg.EnergizedPower, 2)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn + 2)

    def test_flying_knee_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.FlyingKnee.recipe(True): 1}
        )

        with tu.EnergyChangeMonitor(game, -1), tu.FirstMonsterDamageMonitor(game, 11):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_player_has_power_and_get(game, dg.EnergizedPower, 1)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn + 1)

    def test_outmaneuver(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Outmaneuver.recipe(): 1})

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )
            self.assert_player_has_power_and_get(game, dg.EnergizedPower, 2)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn + 2)

    def test_outmaneuver_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Outmaneuver.recipe(True): 1}
        )

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )
            self.assert_player_has_power_and_get(game, dg.EnergizedPower, 3)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn + 3)

    def test_piercing_wail(self):
        monster_damage = 10
        game = tu.create_game(
            initial_draw_pile_manifest={dg.PiercingWail.recipe(): 3},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, 1, monster_damage),
        )

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, -6)
        self.assert_first_monster_has_power_and_get(game, dg.GainStrengthPower, 6)

        with tu.PlayerDamageMonitor(game, monster_damage - 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assertEqual(0, len(game.ctx.d.get_curr_room().monster_group[0].powers))

        with tu.PlayerDamageMonitor(game, monster_damage):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_piercing_wail_upgraded(self):
        monster_damage = 10
        game = tu.create_game(
            initial_draw_pile_manifest={dg.PiercingWail.recipe(True): 3},
            monster=lambda ctx: dg.AlwaysAttackMonster(ctx, 1, monster_damage),
        )

        with tu.EnergyChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, None))
            )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, -8)
        self.assert_first_monster_has_power_and_get(game, dg.GainStrengthPower, 8)

        with tu.PlayerDamageMonitor(game, monster_damage - 8):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assertEqual(0, len(game.ctx.d.get_curr_room().monster_group[0].powers))

        with tu.PlayerDamageMonitor(game, monster_damage):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_poisoned_stab(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.PoisonedStab.recipe(): 3})

        with tu.EnergyChangeMonitor(game, -1), tu.FirstMonsterDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        self.assert_first_monster_has_power_and_get(game, dg.PoisonPower, 3)

    def test_poisoned_stab_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.PoisonedStab.recipe(True): 3}
        )

        with tu.EnergyChangeMonitor(game, -1), tu.FirstMonsterDamageMonitor(game, 8):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        self.assert_first_monster_has_power_and_get(game, dg.PoisonPower, 4)

    def test_prepared(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Prepared.recipe(): 10})

        with tu.EnergyChangeMonitor(game, 0), tu.HandSizeChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(3, None))
            )
            self.assert_current_request_is_and_get(game, dg.DiscardRequest)

            with tu.CardGoesToDiscardMonitor(game, 0):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.pick_discard_from_hand(0))
                )

    def test_prepared_upgraded(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Prepared.recipe(True): 10})

        with tu.EnergyChangeMonitor(game, 0), tu.HandSizeChangeMonitor(game, -1):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(3, None))
            )
            self.assert_current_request_is_and_get(game, dg.DiscardRequest)

            with tu.CardGoesToDiscardMonitor(game, [0, 1]):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.pick_discard_from_hand(0))
                )
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.pick_discard_from_hand(1))
                )

    def test_quick_slash(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.QuickSlash.recipe(): 10})

        with tu.EnergyChangeMonitor(game, -1), tu.HandSizeChangeMonitor(
            game, 0
        ), tu.FirstMonsterDamageMonitor(game, 8):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_quick_slash_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.QuickSlash.recipe(True): 10}
        )

        with tu.EnergyChangeMonitor(game, -1), tu.HandSizeChangeMonitor(
            game, 0
        ), tu.FirstMonsterDamageMonitor(game, 12):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_slice(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Slice.recipe(): 3})

        with tu.EnergyChangeMonitor(game, 0), tu.FirstMonsterDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_slice_upgraded(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Slice.recipe(True): 3})

        with tu.EnergyChangeMonitor(game, 0), tu.FirstMonsterDamageMonitor(game, 9):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_sneaky_strike_no_discard(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.SneakyStrike.recipe(): 3})

        with tu.EnergyChangeMonitor(game, -2), tu.FirstMonsterDamageMonitor(game, 12):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_sneaky_strike_with_discard(self):
        game = tu.create_game(
            initial_draw_pile_manifest={
                dg.SneakyStrike.recipe(): 3,
                dg.Prepared.recipe(): 1,
            }
        )
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.play_first_card_of_type(
                    game.ctx.player.hand, dg.Prepared, None
                )
            )
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_discard_from_hand(0))
        )

        with tu.EnergyChangeMonitor(game, 0), tu.FirstMonsterDamageMonitor(game, 12):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_sneaky_strike_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.SneakyStrike.recipe(True): 3}
        )

        with tu.EnergyChangeMonitor(game, -2), tu.FirstMonsterDamageMonitor(game, 16):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )

    def test_sucker_punch(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.SuckerPunch.recipe(): 3})

        with tu.EnergyChangeMonitor(game, -1), tu.FirstMonsterDamageMonitor(game, 7):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        self.assert_first_monster_has_power_and_get(game, dg.WeakPower, 1)

    def test_sucker_punch_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.SuckerPunch.recipe(True): 3}
        )

        with tu.EnergyChangeMonitor(game, -1), tu.FirstMonsterDamageMonitor(game, 9):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        self.assert_first_monster_has_power_and_get(game, dg.WeakPower, 2)

    def test_anchor(self):
        game = tu.create_game(relics=lambda ctx: [dg.Anchor(ctx)])

        self.assert_player_has_block(game, 10)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_block(game, 0)

    def test_ancient_tea_set_positive(self):
        game = tu.create_game(
            relics=lambda ctx: [
                dg.AncientTeaSet(
                    ctx,
                )
            ],
            create_dungeon=dg.MiniDungeon,
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_rest())
        )
        self.pick_campfire_option(game, dg.RestOption)
        tu.throw_if_step_action_was_illegal(
            game.step(
                dg.ActionGenerator.pick_any_valid_path(
                    game.ctx.action_manager.outstanding_request
                )
            )
        )
        self.assert_current_room_is_and_get(game, dg.MonsterRoomElite)

        self.assert_player_has_energy(game, tu.default_energy_per_turn + 2)

    def test_ancient_tea_set_negative(self):
        game = tu.create_game(
            relics=lambda ctx: [
                dg.AncientTeaSet(
                    ctx,
                )
            ],
            create_dungeon=dg.MiniDungeon,
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_neow_reward(True))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.pick_first_path_mini_dungeon_elite())
        )
        self.assert_player_has_energy(game, tu.default_energy_per_turn)

    def test_art_of_war(self):
        game = tu.create_game(
            relics=lambda ctx: [
                dg.ArtOfWar(
                    ctx,
                )
            ],
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
        )

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn + 1)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_energy(game, tu.default_energy_per_turn)

    def test_cultist(self):
        game = tu.create_game(monster=dg.Cultist)

        self.assert_first_monster_move(game, dg.MoveName.INCANTATION)
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_first_monster_has_power_and_get(game, dg.RitualPower, 3)

        self.assert_first_monster_move(game, dg.MoveName.DARK_STRIKE)
        with tu.PlayerDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_first_monster_has_power_and_get(game, dg.RitualPower, 3)
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 3)

        self.assert_first_monster_intent(game, dg.Intent.ATTACK)
        with tu.PlayerDamageMonitor(game, 9):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_first_monster_has_power_and_get(game, dg.RitualPower, 3)
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 6)

    def test_ascension_dependent_value_simple(self):
        adv = dg.AscensionDependentValue.of(2)
        self.assertEqual(2, adv.resolve())

    def test_ascension_dependent_value_one_pair(self):
        adv = dg.AscensionDependentValue.of(2).with_asc(5, 3)
        self.assertEqual(2, adv.resolve(4))
        self.assertEqual(3, adv.resolve(5))

    def test_ascension_dependent_value_two_pair(self):
        adv = dg.AscensionDependentValue.of(2).with_asc(5, 3).with_asc(7, 4)
        self.assertEqual(2, adv.resolve(4))
        self.assertEqual(3, adv.resolve(5))
        self.assertEqual(4, adv.resolve(7))
        self.assertEqual(4, adv.resolve(8))

    def test_ascension_dependent_value_two_pair_reversed(self):
        adv = dg.AscensionDependentValue.of(2).with_asc(7, 4).with_asc(5, 3)
        self.assertEqual(2, adv.resolve(4))
        self.assertEqual(3, adv.resolve(5))
        self.assertEqual(4, adv.resolve(7))
        self.assertEqual(4, adv.resolve(8))

    def test_jaw_worm_easy(self):
        game = tu.create_game(monster=dg.JawWorm)

        self.assert_first_monster_move(game, dg.MoveName.CHOMP)
        with tu.PlayerDamageMonitor(game, 11):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move_not(game, dg.MoveName.CHOMP)

    def test_jaw_worm_hard(self):
        game = tu.create_game(monster=lambda ctx: dg.JawWorm(ctx, hard_mode=True))

        self.assert_first_monster_move(game, dg.MoveName.CHOMP)
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 3)
        self.assert_first_monster_has_block(game, 6)

    def test_louse_defensive(self):
        def create_monster_group(ctx):
            return dg.MonsterGroup(
                ctx,
                [
                    dg.LouseDefensive(
                        ctx, move_overrides=[dg.MoveName.SPIT_WEB, dg.MoveName.BITE]
                    )
                ],
            )

        game = tu.create_game(create_monster_group=create_monster_group)
        self.assert_first_monster_has_power_and_get(game, dg.CurlUpPower)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_player_has_power_and_get(game, dg.WeakPower, 2)

        with tu.PlayerDamageMonitor(game, (5, 7 + 1)):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_louse_normal(self):
        def create_monster_group(ctx):
            return dg.MonsterGroup(
                ctx,
                [
                    dg.LouseNormal(
                        ctx, move_overrides=[dg.MoveName.GROW, dg.MoveName.BITE]
                    )
                ],
            )

        game = tu.create_game(create_monster_group=create_monster_group)
        self.assert_first_monster_has_power_and_get(game, dg.CurlUpPower)

        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        grow_str = 3
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, grow_str)

        with tu.PlayerDamageMonitor(game, (5 + grow_str, 7 + grow_str + 1)):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_acid_slime_l_tackle(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AcidSlimeL(
                ctx, 66, move_overrides=[dg.MoveName.TACKLE]
            ),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 34): 1},
        )

        with tu.PlayerDamageMonitor(game, 16):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_acid_slime_l_split(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AcidSlimeL(ctx, 66),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 34): 1},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_move(game, dg.MoveName.SPLIT)

        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_alive_monsters(game, 2, dg.AcidSlimeM)
        for m in game.ctx.d.get_curr_room().monster_group:
            if not m.is_dead_or_escaped():
                self.assertEqual(66 - 34, m.current_health)

    def test_acid_slime_l_no_split(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AcidSlimeL(ctx, 66),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 32): 1},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)

    def test_acid_slime_l_combat_ends_if_dead(self):
        game = tu.create_game(
            monster=lambda ctx: dg.AcidSlimeL(ctx, 66),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 33): 2},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        for _ in range(2):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        self.assert_current_room_phase(game, dg.RoomPhase.COMPLETE)

    def test_spike_slime_l_lick(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SpikeSlimeL(
                ctx, 66, move_overrides=[dg.MoveName.LICK]
            ),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 34): 1},
        )

        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_player_has_power_and_get(game, dg.FrailPower)

    def test_spike_slime_l_split(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SpikeSlimeL(ctx, 66),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 34): 1},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_move(game, dg.MoveName.SPLIT)

        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_alive_monsters(game, 2, dg.SpikeSlimeM)
        for m in game.ctx.d.get_curr_room().monster_group:
            if not m.is_dead_or_escaped():
                self.assertEqual(66 - 34, m.current_health)

    def test_spike_slime_l_no_split(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SpikeSlimeL(ctx, 66),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 32): 1},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)

    def test_spike_slime_l_combat_ends_if_dead(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SpikeSlimeL(ctx, 66),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 33): 2},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        for _ in range(2):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        self.assert_current_room_phase(game, dg.RoomPhase.COMPLETE)

    def test_fungi_beast_grow(self):
        game = tu.create_game(
            monster=lambda ctx: dg.FungiBeast(ctx, move_overrides=[dg.MoveName.GROW])
        )

        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 3)

    def test_fungi_beast_bite(self):
        game = tu.create_game(
            monster=lambda ctx: dg.FungiBeast(ctx, move_overrides=[dg.MoveName.BITE])
        )

        with tu.PlayerDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_fungi_beast_spore_cloud(self):
        game = tu.create_game(
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.FungiBeast(ctx, move_overrides=[dg.MoveName.GROW]),
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                ],
            ),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 2},
        )

        fungi_beast = self.find_first_instance_of_monster(game, dg.FungiBeast)
        self.assertTrue(
            any((isinstance(p, dg.SporeCloudPower) for p in fungi_beast.powers))
        )
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_player_has_power_and_get(game, dg.VulnerablePower, 2)

    def test_vulnerable(self):
        game = tu.create_game(
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.FungiBeast(ctx, move_overrides=[dg.MoveName.GROW]),
                    dg.AlwaysAttackMonster(ctx, 1, 10),
                ],
            ),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 2},
        )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_player_has_power_and_get(game, dg.VulnerablePower, 2)
        with tu.PlayerDamageMonitor(game, 15):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_gremlin_fat(self):
        game = tu.create_game(monster=dg.GremlinFat)

        with tu.PlayerDamageMonitor(game, 4):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_player_has_power_and_get(game, dg.WeakPower)

    def test_gremlin_tsundere_shield_bash(self):
        game = tu.create_game(
            monster=lambda ctx: dg.GremlinTsundere(
                ctx, move_overrides=[dg.MoveName.SHIELD_BASH]
            )
        )

        with tu.PlayerDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_first_monster_move(game, dg.MoveName.SHIELD_BASH)

    def test_gremlin_tsundere_protect(self):
        game = tu.create_game(
            monster_group=lambda ctx: dg.MonsterGroup(
                ctx,
                [
                    dg.GremlinTsundere(
                        ctx,
                    ),
                    dg.AlwaysAttackMonster(ctx, 1, 1),
                ],
            ),
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 2},
        )

        for _ in range(10):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
            self.assertEqual(
                7, game.ctx.d.get_curr_room().monster_group[1].current_block
            )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 1))
        )
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))
        self.assert_first_monster_has_block(game, 7)
        self.assert_first_monster_move(game, dg.MoveName.SHIELD_BASH)

    def test_gremlin_thief(self):
        game = tu.create_game(monster=dg.GremlinThief)

        for _ in range(5):
            with tu.PlayerDamageMonitor(game, 9):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

    def test_gremlin_warrior(self):
        game = tu.create_game(
            monster=dg.GremlinWarrior,
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
        )

        self.assert_first_monster_has_power_and_get(game, dg.AngryPower, 1)
        for _ in range(5):
            with tu.PlayerDamageMonitor(game, 4):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 1)

    def test_angry_power(self):
        game = tu.create_game(
            monster=dg.GremlinWarrior,
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
        )

        self.assert_first_monster_has_power_and_get(game, dg.AngryPower, 1)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 1)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 2)

        for _ in range(2):
            with tu.PlayerDamageMonitor(game, 4 + 2):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

    def test_gremlin_wizard(self):
        game = tu.create_game(
            monster=dg.GremlinWizard,
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
        )

        for _ in range(2):
            self.assert_first_monster_move(game, dg.MoveName.CHARGING)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.ULTIMATE_BLAST)
        with tu.PlayerDamageMonitor(game, 25):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        for _ in range(3):
            self.assert_first_monster_move(game, dg.MoveName.CHARGING)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.ULTIMATE_BLAST)
        with tu.PlayerDamageMonitor(game, 25):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_lagavulin_idle_wakeup(self):
        game = tu.create_game(monster=dg.Lagavulin)

        for _ in range(3):
            self.assert_first_monster_move(game, dg.MoveName.SLEEP)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.ATTACK)

    def test_lagavulin(self):
        game = tu.create_game(
            monster=dg.Lagavulin,
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 20): 2},
        )

        self.assert_first_monster_move(game, dg.MoveName.SLEEP)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_move(game, dg.MoveName.STUNNED)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        for _ in range(2):
            self.assert_first_monster_move(game, dg.MoveName.ATTACK)
            with tu.PlayerDamageMonitor(game, 18):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

        self.assert_first_monster_move(game, dg.MoveName.SIPHON_SOUL)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_player_has_power_and_get(game, dg.StrengthPower, -1)
        self.assert_player_has_power_and_get(game, dg.DexterityPower, -1)
        self.assert_first_monster_move(game, dg.MoveName.ATTACK)

    def test_looter(self):
        game = tu.create_game(monster=dg.Looter)
        game.ctx.player.gold = 100

        with tu.SetRestoreAiRng(game, tu.FixedRng(random_bool_returns=True)):
            for _ in range(2):
                self.assert_first_monster_move(game, dg.MoveName.MUG)
                with tu.PlayerDamageMonitor(game, 10), tu.PlayerGoldMonitor(game, -15):
                    tu.throw_if_step_action_was_illegal(
                        game.step(dg.ActionGenerator.end_turn())
                    )

            self.assert_first_monster_move(game, dg.MoveName.LUNGE)
            with tu.PlayerDamageMonitor(game, 12), tu.PlayerGoldMonitor(game, -15):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

            self.assert_first_monster_move(game, dg.MoveName.SMOKE_BOMB)
            with tu.PlayerDamageMonitor(game, 0):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

            self.assert_first_monster_move(game, dg.MoveName.ESCAPE)
            self.assert_first_monster_has_block(game, 6)
            with tu.PlayerDamageMonitor(game, 0):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

            self.assert_current_request_is_and_get(game, dg.CombatRewardRequest)

    def test_stolen_gold_returned_if_monster_killed(self):
        game = tu.create_game(
            monster=dg.Looter, initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )
        game.ctx.player.gold = 100

        with tu.PlayerGoldMonitor(game, 0), tu.SetRestoreAiRng(
            game, tu.FixedRng(random_bool_returns=True)
        ):
            for _ in range(2):
                self.assert_first_monster_move(game, dg.MoveName.MUG)
                with tu.PlayerDamageMonitor(game, 10), tu.PlayerGoldMonitor(game, -15):
                    tu.throw_if_step_action_was_illegal(
                        game.step(dg.ActionGenerator.end_turn())
                    )

            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_current_request_is_and_get(game, dg.CombatRewardRequest)
            self.pick_reward(game, reward_type=dg.StolenGoldRewardItem)

    def test_dazed(self):
        game = tu.create_game(initial_draw_pile_manifest={dg.Dazed.recipe(): 10})

        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_legal(game.step(dg.ActionGenerator.play_card(0, 0)))
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assert_num_cards_in_discard(game, 0)

    def test_sentry(self):
        # Make draw pile big so that dazed cards stay in discard
        game = tu.create_game(
            monster=dg.Sentry, initial_draw_pile_manifest={dg.Defend.recipe(): 100}
        )

        for i in range(3):
            self.assert_first_monster_move(game, dg.MoveName.BOLT)
            with tu.PlayerDamageMonitor(game, 9):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )

            self.assert_first_monster_move(game, dg.MoveName.BEAM)
            with tu.PlayerDamageMonitor(game, 0):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_turn())
                )
            self.assert_num_cards_in_discard(game, 2 * (i + 1), dg.Dazed)

    def test_slaver_blue(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SlaverBlue(
                ctx, move_overrides=[dg.MoveName.RAKE, dg.MoveName.STAB]
            )
        )

        with tu.PlayerDamageMonitor(game, 7):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_player_has_power_and_get(game, dg.WeakPower, 1)

        with tu.PlayerDamageMonitor(game, 12):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_slaver_red(self):
        game = tu.create_game(
            monster=lambda ctx: dg.SlaverRed(
                ctx,
                move_overrides=[
                    dg.MoveName.STAB,
                    dg.MoveName.SCRAPE,
                    dg.MoveName.ENTANGLE,
                    dg.MoveName.STAB,
                ],
            ),
            initial_draw_pile_manifest={dg.Strike.recipe(): 10},
        )

        with tu.PlayerDamageMonitor(game, 13):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        with tu.PlayerDamageMonitor(game, 8):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_player_has_power_and_get(game, dg.VulnerablePower, 1)

        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_player_has_power_and_get(game, dg.EntangledPower)
        tu.throw_if_step_action_was_legal(game.step(dg.ActionGenerator.play_card(0, 0)))
        tu.throw_if_step_action_was_illegal(game.step(dg.ActionGenerator.end_turn()))

        self.assertEqual(0, len(game.ctx.player.powers))

    def test_slime_boss(self):
        game = tu.create_game(
            monster=dg.SlimeBoss, initial_draw_pile_manifest={dg.Defend.recipe(): 100}
        )

        self.assert_first_monster_move(game, dg.MoveName.GOOP_SPRAY)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_cards_in_discard(game, 3, dg.Slimed)

        self.assert_first_monster_move(game, dg.MoveName.PREPARING)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.SLAM)
        with tu.PlayerDamageMonitor(game, 35):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.GOOP_SPRAY)

    def test_slime_boss_split(self):
        game = tu.create_game(
            monster=dg.SlimeBoss,
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 80): 1},
        )

        self.assert_first_monster_move_not(game, dg.MoveName.SPLIT)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, 0))
        )
        self.assert_first_monster_move(game, dg.MoveName.SPLIT)

        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_alive_monsters(game, 2)
        for m in game.ctx.d.get_curr_room().monster_group:
            if not m.is_dead_or_escaped():
                self.assertEqual(140 - 80, m.current_health)

    def test_guardian_offensive(self):
        game = tu.create_game(monster=dg.TheGuardian, player_hp=999)

        self.assert_first_monster_move(game, dg.MoveName.CHARGING_UP)
        self.assert_first_monster_has_power_and_get(game, dg.ModeShiftPower, 30)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_first_monster_has_block(game, 9)

        self.assert_first_monster_move(game, dg.MoveName.FIERCE_BASH)
        self.assert_first_monster_has_power_and_get(game, dg.ModeShiftPower, 30)
        with tu.PlayerDamageMonitor(game, 32):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.VENT_STEAM)
        self.assert_first_monster_has_power_and_get(game, dg.ModeShiftPower, 30)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_player_has_power_and_get(game, dg.VulnerablePower, 2)
        self.assert_player_has_power_and_get(game, dg.WeakPower, 2)

        self.assert_first_monster_move(game, dg.MoveName.WHIRLWIND)
        self.assert_first_monster_has_power_and_get(game, dg.ModeShiftPower, 30)
        with tu.PlayerDamageMonitor(game, 7 * 4):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.CHARGING_UP)

    def test_guardian_defensive(self):
        game = tu.create_game(
            monster=dg.TheGuardian,
            player_hp=999,
            initial_draw_pile_manifest={dg.DebugStrike.recipe(False, False, 16): 10},
        )

        self.assert_first_monster_move(game, dg.MoveName.CHARGING_UP)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_first_monster_has_power_and_get(game, dg.ModeShiftPower, 14)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_first_monster_has_power_and_get(
                game, dg.ModeShiftPower, negate=True
            )
            self.assert_first_monster_move(game, dg.MoveName.DEFENSIVE_MODE)
            self.assert_first_monster_has_block(game, 20)
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.ROLL_ATTACK)
        self.assert_first_monster_has_power_and_get(game, dg.SharpHidePower, 3)
        with tu.PlayerDamageMonitor(game, 3):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
        with tu.PlayerDamageMonitor(game, 9):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.TWIN_SLAM)
        with tu.PlayerDamageMonitor(game, 8 * 2):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.WHIRLWIND)
        self.assert_first_monster_has_power_and_get(
            game, dg.SharpHidePower, negate=True
        )
        self.assert_first_monster_has_power_and_get(game, dg.ModeShiftPower, 40)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_first_monster_has_power_and_get(
                game, dg.ModeShiftPower, 40 - 16
            )
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.play_card(0, 0))
            )
            self.assert_first_monster_has_power_and_get(
                game, dg.ModeShiftPower, 40 - 32
            )
            self.assert_first_monster_move(game, dg.MoveName.WHIRLWIND)

    def test_gremlin_nob(self):
        game = tu.create_game(
            monster=lambda ctx: dg.GremlinNob(
                ctx, move_overrides=[None, dg.MoveName.RUSH, dg.MoveName.SKULL_BASH]
            ),
            player_hp=999,
            initial_draw_pile_manifest={dg.Defend.recipe(): 10},
        )

        self.assert_first_monster_move(game, dg.MoveName.BELLOW)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_has_power_and_get(game, dg.AngerPower, 2)
        with tu.PlayerDamageMonitor(game, 14):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        with tu.PlayerDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_player_has_power_and_get(game, dg.VulnerablePower, 2)
        tu.throw_if_step_action_was_illegal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 2)

    def test_burn(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Burn.recipe(): 1},
            monster=lambda ctx: dg.AlwaysWeakenMonster(ctx, 1),
        )

        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_legal(game.step(dg.ActionGenerator.play_card(0, 0)))
        with tu.PlayerDamageMonitor(game, 2):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_burn_upgraded(self):
        game = tu.create_game(
            initial_draw_pile_manifest={dg.Burn.recipe(True): 1},
            monster=lambda ctx: dg.AlwaysWeakenMonster(ctx, 1),
        )

        tu.throw_if_step_action_was_legal(
            game.step(dg.ActionGenerator.play_card(0, None))
        )
        tu.throw_if_step_action_was_legal(game.step(dg.ActionGenerator.play_card(0, 0)))
        with tu.PlayerDamageMonitor(game, 4):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

    def test_hexaghost(self):
        game = tu.create_game(
            monster=dg.Hexaghost,
            player_hp=300,
            initial_draw_pile_manifest={dg.Strike.recipe(): 100},
        )

        self.assert_first_monster_move(game, dg.MoveName.ACTIVATE)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.DIVIDER)
        with tu.PlayerDamageMonitor(game, (300 // 12 + 1) * 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.SEAR)
        with tu.PlayerDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_cards_in_discard(game, 1, dg.Burn)

        self.assert_first_monster_move(game, dg.MoveName.TACKLE)
        with tu.PlayerDamageMonitor(game, 10):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.SEAR)
        with tu.PlayerDamageMonitor(game, 6):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_cards_in_discard(game, 2, dg.Burn)

        self.assert_first_monster_move(game, dg.MoveName.INFLAME)
        with tu.PlayerDamageMonitor(game, 0):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_first_monster_has_block(game, 12)
        self.assert_first_monster_has_power_and_get(game, dg.StrengthPower, 2)

        self.assert_first_monster_move(game, dg.MoveName.TACKLE)
        with tu.PlayerDamageMonitor(game, 14):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )

        self.assert_first_monster_move(game, dg.MoveName.SEAR)
        with tu.PlayerDamageMonitor(game, 8):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_cards_in_discard(game, 3, dg.Burn)

        self.assert_first_monster_move(game, dg.MoveName.INFERNO)
        with tu.PlayerDamageMonitor(game, 24):
            tu.throw_if_step_action_was_illegal(
                game.step(dg.ActionGenerator.end_turn())
            )
        self.assert_num_cards_in_discard(game, 6, dg.Burn)
        for c in game.ctx.player.discard_pile:
            if isinstance(c, dg.Burn):
                self.assertTrue(c.upgraded)

        self.assert_first_monster_move(game, dg.MoveName.SEAR)

    def test_run_exordium(self):
        game = self._create_game_and_nav_to_first_exordium_fight(
            initial_draw_pile_manifest={dg.DebugStrike.recipe(): 10}
        )

        for _ in range(15):
            room = game.ctx.d.get_curr_room()
            if isinstance(room, dg.MonsterRoomBoss):
                self.win_simple_fight(game)
                _, is_terminal, info = game.step(dg.ActionGenerator.end_combat_reward())
                self.assertTrue(is_terminal)
                self.assertTrue(info["win"])
                return
            elif isinstance(room, dg.MonsterRoom):
                self.win_simple_fight(game)
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_combat_reward())
                )
            elif isinstance(room, dg.EventRoom):
                # For now, only big fish
                self.assert_current_request_is_and_get(
                    game, dg.SimpleChoiceEventRequest
                )
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.pick_simple_event_choice(0))
                )
            elif isinstance(room, dg.RestRoom):
                self.pick_campfire_option(game, dg.RestOption)
            elif isinstance(room, dg.TreasureRoom):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.end_treasure_room())
                )
            elif isinstance(room, dg.ShopRoom):
                ...
            else:
                raise ValueError(room.__class__)

            req = game.ctx.action_manager.outstanding_request
            if isinstance(req, dg.BossPathChoiceRequest):
                tu.throw_if_step_action_was_illegal(
                    game.step(dg.ActionGenerator.go_to_boss())
                )
            elif isinstance(
                game.ctx.action_manager.outstanding_request, dg.PathChoiceRequest
            ):
                tu.throw_if_step_action_was_illegal(
                    game.step(
                        dg.ActionGenerator.pick_any_valid_path(
                            game.ctx.action_manager.outstanding_request
                        )
                    )
                )
            elif isinstance(
                game.ctx.action_manager.outstanding_request, dg.BossChestRequest
            ):
                ...
            else:
                raise ValueError(req)

        self.fail()
