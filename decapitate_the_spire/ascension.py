from __future__ import annotations

import logging
from typing import TypeVar, List, Tuple, Union

logger = logging.getLogger(__name__)


class AscensionManager:
    _V = TypeVar("_V")
    _ascension_level: int = 0

    @classmethod
    def check_ascension(
        cls,
        caller,
        value_if_lt: _V,
        ascension_threshold: int,
        value_if_ge: _V,
        ascension_threshold_2: int = None,
        value_if_ge_2: _V = None,
    ) -> _V:
        assert (ascension_threshold_2 is None) == (value_if_ge_2 is None)
        prefix = f"ASC {cls._ascension_level:2d} check"

        if (
            ascension_threshold_2 is not None
            and cls._ascension_level >= ascension_threshold_2
        ):
            logger.debug(
                f"{prefix}:  {value_if_ge}  |{ascension_threshold_2:2d}| [{value_if_ge_2}]"
            )
            result = value_if_ge_2
        elif cls._ascension_level >= ascension_threshold:
            logger.debug(
                f"{prefix}:  {value_if_lt}  |{ascension_threshold:2d}| [{value_if_ge}]"
            )
            result = value_if_ge
        else:
            logger.debug(
                f"{prefix}: [{value_if_lt}] |{ascension_threshold:2d}|  {value_if_ge} "
            )
            result = value_if_lt

        return result

    @classmethod
    def get_ascension(cls, caller):
        logger.debug(f"ASC {cls._ascension_level} retrieved")
        return cls._ascension_level

    # TODO can't set asc statically like this
    # @classmethod
    # def set_ascension(cls, caller, asc: int):
    #     logger.debug(f'Set ASC to {asc}')
    #     cls._ascension_level = asc


class AscensionDependentValue:
    _V = TypeVar("_V")

    def __init__(self, base: _V, asc_value_pairs: List[Tuple[int, _V]]):
        self.base = base
        self.asc_value_pairs = asc_value_pairs

    @classmethod
    def resolve_adv_or_int(cls, adv_or_int: AscensionDependentValueOrInt):
        if isinstance(adv_or_int, cls):
            return adv_or_int.resolve()
        assert isinstance(adv_or_int, int)
        return adv_or_int

    @classmethod
    def of(cls, base: _V):
        return cls(base, [])

    def with_asc(self, ascension_threshold: int, value_if_ge: _V):
        self.asc_value_pairs.append((ascension_threshold, value_if_ge))
        return self

    def resolve(self, override_ascension=None) -> _V:
        def avp_key(a):
            return a[0]

        self.asc_value_pairs.sort(key=avp_key, reverse=True)

        asc = (
            override_ascension
            if override_ascension is not None
            else AscensionManager.get_ascension(self)
        )
        for ascension_threshold, value in self.asc_value_pairs:
            if asc >= ascension_threshold:
                return value

        return self.base


ADV = AscensionDependentValue
AscensionDependentValueOrInt = ADVOrInt = Union[AscensionDependentValue, int]
