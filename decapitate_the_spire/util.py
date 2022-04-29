from __future__ import annotations

from typing import List

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decapitate_the_spire.card import CardGroup, Card


def flatten(t: List[CardGroup]) -> List[Card]:
    # https://stackoverflow.com/a/952952
    return [item for sublist in t for item in sublist]
