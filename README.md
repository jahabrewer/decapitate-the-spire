# Decapitate the Spire

[![PyPI][pypi-image]][pypi-url]

> A headless clone of Mega Crit's _Slay the Spire_.

Have you ever wanted to play _Slay the Spire_, but with no graphics, an inscrutable TUI, and lots of bugs? Probably not. Computers like it, though.

![Demo][demo-image]

## Installation

```sh
pip install decapitate-the-spire
```

## Usage example

To play in a console:

```sh
python3 -m decapitate_the_spire
```

If you want to control the game from your own code, start with a core loop like this:

```python
import decapitate_the_spire.dungeon
import decapitate_the_spire.character
import decapitate_the_spire.map
from decapitate_the_spire import game as dg


def main():
    # Also consider dg.SimpleDungeon and dg.MiniDungeon for testing.
    game = dg.Game(decapitate_the_spire.character.TheSilent, decapitate_the_spire.dungeon.Exordium)

    is_terminal = False
    while not is_terminal:
        # You'll be determining the actions; this is a placeholder. See the
        # wiki for details on the action space.
        action_0, action_1 = (0, 0)
        # This is the core gameplay loop.
        _, is_terminal, _ = game.step((action_0, action_1))
```

## Current state

This is _very much_ a work in progress. The code is littered with TODOs and bugs. I'm focused on getting Exordium playable with Silent and with full content.

- [ ] Characters
    - [x] Silent
        - [x] Relics
        - [x] Cards
    - [ ] Ironclad
    - [ ] Defect
    - [ ] Watcher
- [ ] Dungeons
    - [x] Mechanics (map, room traversal, etc.)
    - [ ] Content
        - [ ] Exordium
            - [x] Monsters
            - [ ] Events
            - [ ] Shops
        - [ ] The City
        - [ ] The Beyond

## Development setup

```sh
# If you don't have pipenv, get it.
pip install pipenv

# Clone this repo.
# git clone ...

# Enter the new repo dir.
cd decapitate-the-spire

# Start pipenv. It'll pick up the Pipfile in the repo. Notice that you're in a
# new shell after this.
pipenv shell

# Install dev dependencies.
pipenv install --dev

# Run tests to verify.
pytest
```

## Contributing

Pull requests are very welcome. I'm focused on completing Exordium and gaining confidence in my cloning of the original game. Tests are required when practical.

1. Fork it (<https://github.com/jahabrewer/decapitate-the-spire/fork>)
2. Create your feature branch (`git checkout -b feature/fooBar`)
3. Commit your changes (`git commit -am 'Add some fooBar'`)
4. Push to the branch (`git push origin feature/fooBar`)
5. Create a new Pull Request

## Motivation
A while back, I was watching [jorbs](https://www.twitch.tv/jorbs) and got jealous because he plays so well. I knew I could never best his play with _my_ brain, so I decided to try my hand at creating an [agent](https://en.wikipedia.org/wiki/Intelligent_agent) that could beat jorbs _for_ me.

I opted to use reinforcement learning to create the agent, inspired by its success with, well, everything lately (especially [SC2LE](https://arxiv.org/abs/1708.04782)). Reinforcement learning is great in that you don't need to tell the agent how the game works; it _learns_ the game. The problem/tradeoff is that it needs to play the game **a whoooole lot** before it's smart at all.

Initially, I hooked up a reinforcement learning trainer to _Slay the Spire_ via ForgottenArbiter's very cool [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod/). This worked... but at human speed. It was obvious that I needed a fast, headless version of the game.

aaaaaand here we are.

<!-- Markdown link & img dfn's -->
[pypi-image]: https://img.shields.io/pypi/v/decapitate-the-spire
[pypi-url]: https://pypi.org/project/decapitate-the-spire/
[demo-image]: assets/demo.png
[wiki]: https://github.com/yourname/yourproject/wiki

## Credits
Very big thanks to Mega Crit for allowing me to release this publicly.

This package was created with Cookiecutter and the [sourcery-ai/python-best-practices-cookiecutter](https://github.com/sourcery-ai/python-best-practices-cookiecutter) project template.
