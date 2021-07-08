import logging
import sys
from typing import List

from decapitate_the_spire import game as dg


def without_all_false_rows_at_end(mask: List[List[bool]]):
    last_row_to_include = None
    for i in reversed(range(len(mask))):
        if any(mask[i]):
            last_row_to_include = i
            break

    return mask[: (last_row_to_include + 1)]


def pretty_print_action_mask(mask: List[List[bool]]):
    for row in mask:
        for col in row:
            print(f"{repr(col): <8}", end="")
        print()


def main():
    logger = logging.getLogger("dts")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(levelname)-8s - %(funcName)-16s - %(message)s"
        )
    )
    logger.addHandler(handler)

    max_health = 80
    energy_per_turn = 3

    def create_player(ctx):
        return dg.TheSilent(ctx, max_health, energy_per_turn)

    # monster_list = [
    #     AcidSlimeS,
    #     JawWorm,
    #     Cultist,
    #     FungiBeast,
    # ]
    # monster_type = random.choice(monster_list)
    #
    # def create_monster_group(ctx):
    #     # monster_name = self.config['monster']
    #     # if monster_name == 'AcidSlimeS':
    #     #     return sg.MonsterGroup(ctx, [sg.AcidSlimeS(ctx)])
    #     # raise Exception(f'Unknown monster: {monster_name}')
    #     return MonsterGroup(ctx, [monster_type(ctx)])

    game = dg.Game(create_player, create_dungeon=dg.Exordium)
    # game = Game(create_player, create_dungeon=lambda ctx: dg.SimpleDungeon(ctx, create_monster_group))
    is_terminal = False

    while not is_terminal:
        action_mask = game.generate_action_mask()

        if isinstance(
            game.ctx.action_manager.outstanding_request,
            (dg.PathChoiceRequest, dg.FirstPathChoiceRequest),
        ):
            print(dg.MapGenerator.to_string(game.ctx.d.mapp, True))
        print(game.ctx.action_manager.outstanding_request)
        print()
        pretty_print_action_mask(without_all_false_rows_at_end(action_mask))

        while True:
            action_0 = int(input("Action[0]: "))
            valid_actions_1 = [i for i, b in enumerate(action_mask[action_0]) if b]

            if not valid_actions_1:
                print(f"No possible valid actions with {action_0=}")
                continue

            if len(valid_actions_1) == 1:
                action_1 = valid_actions_1[0]
                print(f"Autopicked action[1] as {action_1}")
            else:
                action_1 = int(input("Action[1]: "))

            if not action_mask[action_0][action_1]:
                print(f"({action_0}, {action_1}) is invalid, try again")
            else:
                break

        # action_1 = spiregame.game.MAX_NUM_MONSTERS_IN_GROUP if len(action_1_raw) == 0 else int(action_1_raw)
        _, is_terminal, _ = game.step((action_0, action_1))
        # obs, reward, is_terminal, _ = env.step(action_0 * 6 + action_1)
        # obs = GameAdapter.observe(game)
        # print(f'Reward: {reward}')
    print("Game over")


if __name__ == "__main__":
    main()
