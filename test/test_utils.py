import decapitate_the_spire.game as dg
from decapitate_the_spire.rng import Rng

default_player_max_health = 52
default_energy_per_turn = 3
default_monster_max_health = 20
default_initial_draw_pile_manifest = {
    dg.Strike.recipe(): 5,
    dg.Defend.recipe(): 5,
    dg.Survivor.recipe(): 1,
    dg.Neutralize.recipe(): 1,
}


def create_game(
    player_hp=default_player_max_health,
    energy_per_turn=default_energy_per_turn,
    monster_hp=default_monster_max_health,
    initial_draw_pile_manifest: dg.Dict[
        dg.Callable[[dg.CCG.Context], dg.Card], int
    ] = None,
    monster: dg.Callable[[dg.CCG.Context], dg.Monster] = None,
    monster_group: dg.Callable[[dg.CCG.Context], dg.MonsterGroup] = None,
    create_monster_group: dg.Callable[[dg.CCG.Context], dg.MonsterGroup] = None,
    relics: dg.Callable[[dg.CCG.Context], dg.List[dg.Relic]] = None,
    potions: dg.Callable[[dg.CCG.Context], dg.List[dg.Potion]] = None,
    create_dungeon: dg.Callable[[dg.CCG.Context], dg.Dungeon] = None,
) -> dg.Game:
    assert not (bool(monster) and bool(monster_group))

    initial_draw_pile = (
        dg.CardGroup.explode_card_group_recipe_manifest(initial_draw_pile_manifest)
        if initial_draw_pile_manifest
        else None
    )

    def create_player(ctx: dg.CCG.Context):
        return dg.TheSilent(ctx, player_hp, energy_per_turn, initial_draw_pile, potions)

    def create_monster_group_default(ctx: dg.CCG.Context):
        if monster:
            return dg.MonsterGroup(ctx, [monster(ctx)])
        elif monster_group:
            return monster_group(ctx)
        return dg.MonsterGroup(ctx, [dg.SimpleMonster(ctx, monster_hp, 8, 6)])

    if create_monster_group is None:
        create_monster_group = create_monster_group_default
    elif monster is not None or monster_group is not None:
        raise Exception("conflicting monster specifiers")

    if not create_dungeon:

        def cd(ctx: dg.CCG.Context):
            return dg.SimpleDungeon(ctx, create_monster_group)

        create_dungeon = cd

    g = dg.Game(create_player, create_dungeon, relics)
    # Hacky af, but lets me keep using old tests with minimal changes.
    if isinstance(g.ctx.d, dg.SimpleDungeon):
        throw_if_step_action_was_illegal(g.step(dg.ActionGenerator.pick_first_path(0)))
    return g


def throw_if_step_action_was_illegal(
    step_output: dg.Tuple[float, bool, dict]
) -> dg.Tuple[float, bool, dict]:
    if "illegal" in step_output[2] and step_output[2]["illegal"] is True:
        raise Exception("step return indicates illegal action")
    return step_output


def throw_if_step_action_was_legal(
    step_output: dg.Tuple[float, bool, dict]
) -> dg.Tuple[float, bool, dict]:
    if not ("illegal" in step_output[2] and step_output[2]["illegal"] is True):
        raise Exception("step return indicates legal action")
    return step_output


V = dg.TypeVar("V")


class SetRestore:
    def __init__(
        self,
        read_func: dg.Callable[[], V],
        write_func: dg.Callable[[V], None],
        replacement_rng: V,
    ):
        self.read_func = read_func
        self.write_func = write_func
        self.replacement_rng = replacement_rng
        self.rng_to_restore: dg.Optional[V] = None

    def __enter__(self):
        self.rng_to_restore = self.read_func()
        self.write_func(self.replacement_rng)

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert self.rng_to_restore is not None
        self.write_func(self.rng_to_restore)


class SetRestoreCardRandomRng(SetRestore):
    def __init__(self, game: dg.Game, replacement_rng: Rng):
        def read():
            return game.ctx.card_random_rng

        def write(rng: Rng):
            game.ctx.card_random_rng = rng

        super().__init__(read, write, replacement_rng)


class SetRestoreEventRng(SetRestore):
    def __init__(self, game: dg.Game, replacement_rng: Rng):
        def read():
            return game.ctx.event_rng

        def write(rng: Rng):
            game.ctx.event_rng = rng

        super().__init__(read, write, replacement_rng)


class SetRestorePotionRng(SetRestore):
    def __init__(self, game: dg.Game, replacement_rng: Rng):
        def read():
            return game.ctx.potion_rng

        def write(rng: Rng):
            game.ctx.potion_rng = rng

        super().__init__(read, write, replacement_rng)


class SetRestoreAiRng(SetRestore):
    def __init__(self, game: dg.Game, replacement_rng: Rng):
        def read():
            return game.ctx.ai_rng

        def write(rng: Rng):
            game.ctx.ai_rng = rng

        super().__init__(read, write, replacement_rng)


# class SetRestoreAscension(SetRestore):
#     def __init__(self, replacement_asc: int):
#         def read():
#             return AscensionManager.get_ascension(self)
#
#         def write(asc: int):
#             AscensionManager.set_ascension(self, asc)
#
#         super().__init__(read, write, replacement_asc)


class ValueChangeMonitor(dg.ABC):
    def __init__(
        self, expected_change: dg.Union[int, dg.Tuple[int, int]], negate=False
    ):
        self.expected_change = expected_change
        self.negate = negate

    @dg.abstractmethod
    def read_value(self):
        ...

    def __enter__(self):
        self.value_on_enter = self.read_value()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            actual_value = self.read_value()
            if isinstance(self.expected_change, int):
                if self.negate:
                    self.expected_change *= -1

                expected_value = self.value_on_enter + self.expected_change

                if expected_value != actual_value:
                    raise AssertionError(
                        f"Expected {self.value_on_enter} + {self.expected_change} = {expected_value}, "
                        f"actual {actual_value}"
                    )

            elif isinstance(self.expected_change, dg.Tuple):
                if self.negate:
                    # Having an exclusive upper bound gets wonky when negating a range. Pretty sure this is right.
                    low_delta = -(self.expected_change[1] + 1)
                    high_delta = -(self.expected_change[0] - 1)
                else:
                    low_delta = self.expected_change[0]
                    high_delta = self.expected_change[1]
                low = self.value_on_enter + low_delta
                high = self.value_on_enter + high_delta
                if not (low <= actual_value < high):
                    raise AssertionError(f"Expected {low} <= {actual_value} < {high}")

            else:
                raise ValueError(self.expected_change)


class CharacterHealthChangeMonitor(ValueChangeMonitor):
    def __init__(
        self,
        character: dg.dts.game.Character,
        amount: dg.Union[int, dg.Tuple[int, int]],
        negate=False,
    ):
        super().__init__(amount, negate)
        self.character = character

    def read_value(self):
        return self.character.current_health


class FirstMonsterDamageMonitor(CharacterHealthChangeMonitor):
    def __init__(
        self,
        game: dg.dts.game.Game,
        damage: dg.Union[int, dg.Tuple[int, int]],
    ):
        super().__init__(
            game.ctx.d.get_curr_room().monster_group[0], damage, negate=True
        )


class PlayerDamageMonitor(CharacterHealthChangeMonitor):
    def __init__(
        self,
        game: dg.dts.game.Game,
        damage: dg.Union[int, dg.Tuple[int, int]],
    ):
        super().__init__(game.ctx.player, damage, negate=True)


class PlayerGoldMonitor(ValueChangeMonitor):
    def __init__(
        self,
        game: dg.dts.game.Game,
        change: dg.Union[int, dg.Tuple[int, int]],
    ):
        super().__init__(change)
        self.game = game

    def read_value(self):
        return self.game.ctx.player.gold


class HandSizeChangeMonitor(ValueChangeMonitor):
    def __init__(
        self,
        game: dg.dts.game.Game,
        amount: dg.Union[int, dg.Tuple[int, int]],
    ):
        super().__init__(amount)
        self.game = game

    def read_value(self):
        return len(self.game.ctx.player.hand)


class EnergyChangeMonitor(ValueChangeMonitor):
    def __init__(
        self,
        game: dg.dts.game.Game,
        amount: dg.Union[int, dg.Tuple[int, int]],
    ):
        super().__init__(amount)
        self.game = game

    def read_value(self):
        return self.game.ctx.player.energy_manager.player_current_energy


class CardGoesToDiscardMonitor:
    def __init__(
        self,
        game: dg.dts.game.Game,
        card_index: dg.Union[int, dg.List[int]],
    ):
        self.game = game
        if isinstance(card_index, int):
            self.card_indexes = [card_index]
        elif isinstance(card_index, dg.List):
            self.card_indexes = card_index
        else:
            raise ValueError(card_index)

    def __enter__(self):
        self.cards = [self.game.ctx.player.hand[i] for i in self.card_indexes]

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            for card in self.cards:
                if card not in self.game.ctx.player.discard_pile:
                    raise AssertionError(f"Expected {card} to be in discard pile")
                if card in self.game.ctx.player.hand:
                    raise AssertionError(f"Expected {card} to not still be in hand")


class FixedRng(Rng):
    def __init__(self, random_returns=None, random_bool_returns: bool = None):
        self.random_bool_returns = random_bool_returns
        self.random_returns = random_returns

    def random(self, start: int, inclusive_end: int):
        if self.random_returns is not None:
            assert start <= self.random_returns <= inclusive_end
            return self.random_returns

        return super().random(start, inclusive_end)

    def random_boolean(self, chance: float = None):
        if self.random_bool_returns is not None:
            return self.random_bool_returns

        return super().random_boolean(chance)


class FixedRngRandomFloat(Rng):
    def __init__(self, random_float_returns: float):
        assert 0 <= random_float_returns < 1
        self.random_float_returns = random_float_returns

    def random_float(self):
        return self.random_float_returns
