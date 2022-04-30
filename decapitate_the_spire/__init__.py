import logging

import decapitate_the_spire.card
import decapitate_the_spire.character
import decapitate_the_spire.game
import decapitate_the_spire.power
import decapitate_the_spire.relic

logging._defaultFormatter = logging.Formatter(u"%(message)s")
SILENT_CARD_UNIVERSE = [
    decapitate_the_spire.card.Strike,
    decapitate_the_spire.card.DebugStrike,
    decapitate_the_spire.card.Defend,
    decapitate_the_spire.card.Backstab,
    decapitate_the_spire.card.Footwork,
    decapitate_the_spire.card.Survivor,
    decapitate_the_spire.card.Neutralize,
    decapitate_the_spire.card.Alchemize,
    decapitate_the_spire.card.Concentrate,
    decapitate_the_spire.card.AllOutAttack,
    decapitate_the_spire.card.Skewer,
    decapitate_the_spire.card.GlassKnife,
    decapitate_the_spire.card.Acrobatics,
    decapitate_the_spire.card.Backflip,
    decapitate_the_spire.card.Bane,
    decapitate_the_spire.card.DeadlyPoison,
    decapitate_the_spire.card.BladeDance,
    decapitate_the_spire.card.CloakAndDagger,
    decapitate_the_spire.card.DaggerSpray,
    decapitate_the_spire.card.DaggerThrow,
    decapitate_the_spire.card.Deflect,
    decapitate_the_spire.card.DodgeAndRoll,
    decapitate_the_spire.card.FlyingKnee,
    decapitate_the_spire.card.Outmaneuver,
    decapitate_the_spire.card.PiercingWail,
    decapitate_the_spire.card.PoisonedStab,
    decapitate_the_spire.card.Prepared,
    decapitate_the_spire.card.QuickSlash,
    decapitate_the_spire.card.Slice,
    decapitate_the_spire.card.SneakyStrike,
    decapitate_the_spire.card.SuckerPunch,
    decapitate_the_spire.card.Slimed,
    decapitate_the_spire.card.Wound,
    decapitate_the_spire.card.Dazed,
    decapitate_the_spire.card.Smite,
    decapitate_the_spire.card.Shiv,
    decapitate_the_spire.card.AscendersBane,
    decapitate_the_spire.card.Regret,
    decapitate_the_spire.card.CurseOfTheBell,
    decapitate_the_spire.card.Necronomicurse,
    decapitate_the_spire.card.Burn,
]

CARD_TYPE_TO_UNIVERSE_INDEX = {
    card_type: index for index, card_type in enumerate(SILENT_CARD_UNIVERSE)
}

SILENT_POWER_UNIVERSE = [
    decapitate_the_spire.power.DexterityPower,
    decapitate_the_spire.power.WeakPower,
    decapitate_the_spire.power.VigorPower,
    decapitate_the_spire.power.MinionPower,
    decapitate_the_spire.power.PoisonPower,
    decapitate_the_spire.power.FrailPower,
    decapitate_the_spire.power.SporeCloudPower,
    decapitate_the_spire.power.VulnerablePower,
    decapitate_the_spire.power.AngryPower,
    decapitate_the_spire.power.MetallicizePower,
    decapitate_the_spire.power.ThieveryPower,
    decapitate_the_spire.power.EntangledPower,
    decapitate_the_spire.power.SharpHidePower,
    decapitate_the_spire.power.ModeShiftPower,
    decapitate_the_spire.power.AngerPower,
    decapitate_the_spire.power.RitualPower,
    decapitate_the_spire.power.CurlUpPower,
    decapitate_the_spire.power.StrengthPower,
    decapitate_the_spire.power.SplitPower,
    decapitate_the_spire.power.GainStrengthPower,
    decapitate_the_spire.power.NextTurnBlockPower,
    decapitate_the_spire.power.EnergizedPower,
]

POWER_TYPE_TO_UNIVERSE_INDEX = {
    power_type: index for index, power_type in enumerate(SILENT_POWER_UNIVERSE)
}

SILENT_RELIC_UNIVERSE = [
    decapitate_the_spire.relic.Circlet,
    decapitate_the_spire.relic.RedCirclet,
    decapitate_the_spire.relic.Akabeko,
    decapitate_the_spire.relic.SnakeRing,
    decapitate_the_spire.relic.GamblingChip,
    decapitate_the_spire.relic.OddlySmoothStone,
    decapitate_the_spire.relic.Anchor,
    decapitate_the_spire.relic.AncientTeaSet,
    decapitate_the_spire.relic.ArtOfWar,
    decapitate_the_spire.relic.GoldenIdol,
]

RELIC_TYPE_TO_UNIVERSE_INDEX = {
    relic_type: index for index, relic_type in enumerate(SILENT_RELIC_UNIVERSE)
}

MONSTER_UNIVERSE = [
    decapitate_the_spire.character.AcidSlimeS,
    decapitate_the_spire.character.AcidSlimeM,
    decapitate_the_spire.character.AcidSlimeL,
    decapitate_the_spire.character.SpikeSlimeS,
    decapitate_the_spire.character.SpikeSlimeM,
    decapitate_the_spire.character.SpikeSlimeL,
    decapitate_the_spire.character.Cultist,
    decapitate_the_spire.character.JawWorm,
    decapitate_the_spire.character.AlwaysAttackMonster,
    decapitate_the_spire.character.SimpleMonster,
    decapitate_the_spire.character.AlwaysWeakenMonster,
    decapitate_the_spire.character.Reptomancer,
    decapitate_the_spire.character.SnakeDagger,
    decapitate_the_spire.character.LouseDefensive,
    decapitate_the_spire.character.LouseNormal,
    decapitate_the_spire.character.FungiBeast,
    decapitate_the_spire.character.GremlinFat,
    decapitate_the_spire.character.GremlinTsundere,
    decapitate_the_spire.character.GremlinThief,
    decapitate_the_spire.character.GremlinWarrior,
    decapitate_the_spire.character.GremlinWizard,
    decapitate_the_spire.character.Lagavulin,
    decapitate_the_spire.character.Looter,
    decapitate_the_spire.character.Sentry,
    decapitate_the_spire.character.SlaverBlue,
    decapitate_the_spire.character.SlaverRed,
    decapitate_the_spire.character.SlimeBoss,
    decapitate_the_spire.character.TheGuardian,
    decapitate_the_spire.character.GremlinNob,
    decapitate_the_spire.character.Hexaghost,
]

MONSTER_TO_UNIVERSE_INDEX = {
    monster: index for index, monster in enumerate(MONSTER_UNIVERSE)
}
