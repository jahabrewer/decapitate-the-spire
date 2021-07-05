import decapitate_the_spire.game

SILENT_CARD_UNIVERSE = [
    decapitate_the_spire.game.Strike,
    decapitate_the_spire.game.DebugStrike,
    decapitate_the_spire.game.Defend,
    decapitate_the_spire.game.Backstab,
    decapitate_the_spire.game.Footwork,
    decapitate_the_spire.game.Survivor,
    decapitate_the_spire.game.Neutralize,
    decapitate_the_spire.game.Alchemize,
    decapitate_the_spire.game.Concentrate,
    decapitate_the_spire.game.AllOutAttack,
    decapitate_the_spire.game.Skewer,
    decapitate_the_spire.game.GlassKnife,
    decapitate_the_spire.game.Acrobatics,
    decapitate_the_spire.game.Backflip,
    decapitate_the_spire.game.Bane,
    decapitate_the_spire.game.DeadlyPoison,
    decapitate_the_spire.game.BladeDance,
    decapitate_the_spire.game.CloakAndDagger,
    decapitate_the_spire.game.DaggerSpray,
    decapitate_the_spire.game.DaggerThrow,
    decapitate_the_spire.game.Deflect,
    decapitate_the_spire.game.DodgeAndRoll,
    decapitate_the_spire.game.FlyingKnee,
    decapitate_the_spire.game.Outmaneuver,
    decapitate_the_spire.game.PiercingWail,
    decapitate_the_spire.game.PoisonedStab,
    decapitate_the_spire.game.Prepared,
    decapitate_the_spire.game.QuickSlash,
    decapitate_the_spire.game.Slice,
    decapitate_the_spire.game.SneakyStrike,
    decapitate_the_spire.game.SuckerPunch,
    decapitate_the_spire.game.Slimed,
    decapitate_the_spire.game.Wound,
    decapitate_the_spire.game.Dazed,
    decapitate_the_spire.game.Smite,
    decapitate_the_spire.game.Shiv,
    decapitate_the_spire.game.AscendersBane,
    decapitate_the_spire.game.Regret,
    decapitate_the_spire.game.CurseOfTheBell,
    decapitate_the_spire.game.Necronomicurse,
    decapitate_the_spire.game.Burn,
]

CARD_TYPE_TO_UNIVERSE_INDEX = {
    card_type: index for index, card_type in enumerate(SILENT_CARD_UNIVERSE)
}

SILENT_POWER_UNIVERSE = [
    decapitate_the_spire.game.DexterityPower,
    decapitate_the_spire.game.WeakPower,
    decapitate_the_spire.game.VigorPower,
    decapitate_the_spire.game.MinionPower,
    decapitate_the_spire.game.PoisonPower,
    decapitate_the_spire.game.FrailPower,
    decapitate_the_spire.game.SporeCloudPower,
    decapitate_the_spire.game.VulnerablePower,
    decapitate_the_spire.game.AngryPower,
    decapitate_the_spire.game.MetallicizePower,
    decapitate_the_spire.game.ThieveryPower,
    decapitate_the_spire.game.EntangledPower,
    decapitate_the_spire.game.SharpHidePower,
    decapitate_the_spire.game.ModeShiftPower,
    decapitate_the_spire.game.AngerPower,
    decapitate_the_spire.game.RitualPower,
    decapitate_the_spire.game.CurlUpPower,
    decapitate_the_spire.game.StrengthPower,
    decapitate_the_spire.game.SplitPower,
    decapitate_the_spire.game.GainStrengthPower,
    decapitate_the_spire.game.NextTurnBlockPower,
    decapitate_the_spire.game.EnergizedPower,
]

POWER_TYPE_TO_UNIVERSE_INDEX = {
    power_type: index for index, power_type in enumerate(SILENT_POWER_UNIVERSE)
}

SILENT_RELIC_UNIVERSE = [
    decapitate_the_spire.game.Circlet,
    decapitate_the_spire.game.RedCirclet,
    decapitate_the_spire.game.Akabeko,
    decapitate_the_spire.game.SnakeRing,
    decapitate_the_spire.game.GamblingChip,
    decapitate_the_spire.game.OddlySmoothStone,
    decapitate_the_spire.game.Anchor,
    decapitate_the_spire.game.AncientTeaSet,
    decapitate_the_spire.game.ArtOfWar,
    decapitate_the_spire.game.GoldenIdol,
]

RELIC_TYPE_TO_UNIVERSE_INDEX = {
    relic_type: index for index, relic_type in enumerate(SILENT_RELIC_UNIVERSE)
}

MONSTER_UNIVERSE = [
    decapitate_the_spire.game.AcidSlimeS,
    decapitate_the_spire.game.AcidSlimeM,
    decapitate_the_spire.game.AcidSlimeL,
    decapitate_the_spire.game.SpikeSlimeS,
    decapitate_the_spire.game.SpikeSlimeM,
    decapitate_the_spire.game.SpikeSlimeL,
    decapitate_the_spire.game.Cultist,
    decapitate_the_spire.game.JawWorm,
    decapitate_the_spire.game.AlwaysAttackMonster,
    decapitate_the_spire.game.SimpleMonster,
    decapitate_the_spire.game.AlwaysWeakenMonster,
    decapitate_the_spire.game.Reptomancer,
    decapitate_the_spire.game.SnakeDagger,
    decapitate_the_spire.game.LouseDefensive,
    decapitate_the_spire.game.LouseNormal,
    decapitate_the_spire.game.FungiBeast,
    decapitate_the_spire.game.GremlinFat,
    decapitate_the_spire.game.GremlinTsundere,
    decapitate_the_spire.game.GremlinThief,
    decapitate_the_spire.game.GremlinWarrior,
    decapitate_the_spire.game.GremlinWizard,
    decapitate_the_spire.game.Lagavulin,
    decapitate_the_spire.game.Looter,
    decapitate_the_spire.game.Sentry,
    decapitate_the_spire.game.SlaverBlue,
    decapitate_the_spire.game.SlaverRed,
    decapitate_the_spire.game.SlimeBoss,
    decapitate_the_spire.game.TheGuardian,
    decapitate_the_spire.game.GremlinNob,
    decapitate_the_spire.game.Hexaghost,
]

MONSTER_TO_UNIVERSE_INDEX = {
    monster: index for index, monster in enumerate(MONSTER_UNIVERSE)
}
