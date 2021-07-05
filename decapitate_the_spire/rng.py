import random


class Rng:
    def random_boolean(self, chance: float = None):
        if chance:
            assert 0.0 < chance < 1.0
            return random.random() < chance
        return random.choice([True, False])

    def random(self, start: int, inclusive_end: int):
        return random.randrange(start, inclusive_end + 1)

    def random_from_0_to(self, inclusive_end: int):
        return self.random(0, inclusive_end)

    def random_float(self):
        return random.random()

    def random_float_between(self, start: float, end: float):
        # This is probably wrong in the way that doing anything with floats ends up being wrong, but it's source.
        return start + random.random() * (end - start)
