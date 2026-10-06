"""Short world-space shot beams the capture frame can actually see.

Hitscan weapons are not entities. Each pellet is a server trace, and
`bullet_impact` is where that trace landed. A beam from the shooter's eyes to
that point is the collision test, so a hit ends on the hitbox and a miss ends
on the world.

The beam is an `env_beam` using an unlit texture, not a debug overlay.
`DebugDrawLine` only exists on the listen host and is not part of the image a
vision pipeline samples. The tracer colour is kept off the infected table so a
pixel of that RGB is a shot, and a neighbouring class colour is a hit.

Grenades, molotovs, pipe bombs and bile jars leave the same kind of beam while
they fly. Every beam is removed in under a second.
"""

from __future__ import annotations

from . import config, manifest, vtf

# Bump when the shipped script or tracer material changes.
GENERATOR_VERSION = "3"

SCRIPT_REL = "scripts/vscripts/mapspawn_addon.nut"
TRACER_VMT = "materials/sprites/cv_tracer.vmt"
TRACER_VTF = "materials/sprites/cv_tracer.vtf"
TRACER_TEXTURE = "sprites/cv_tracer"

SHOTLINES_NUT = r"""// cv_infected shot beams.
//
// One beam per server bullet trace, from the eyes (the start of the collision
// test) to the impact. Colour is sprites/cv_tracer, which is not an infected
// class, so a capture can score a hit when this colour meets a class colour.
// Beams are removed in under a second.
//
//   script CVShotLinesEnabled <- false
//   script CVShotLinesEnabled <- true

::CVShotLinesEnabled <- true
::CVShotLinesTime <- __TIME__

::CVProjectileClasses <- [
	"grenade_launcher_projectile",
	"molotov_projectile",
	"pipe_bomb_projectile",
	"vomitjar_projectile"
]

::CVProjLast <- {}
::CVShotLinesThinking <- false
::CVCaptureLeft <- 0
::CVCaptureAt <- 0.0

function CV_Life() {
	local life = ::CVShotLinesTime
	if (life < 0.05)
		return 0.05
	if (life > 0.95)
		return 0.95
	return life
}

function CV_Eye(player) {
	try {
		return player.EyePosition()
	} catch (err) {
		local origin = player.GetOrigin()
		local view = NetProps.GetPropVector(player, "m_vecViewOffset[0]")
		return Vector(origin.x + view.x, origin.y + view.y, origin.z + view.z)
	}
}

function CV_Draw(a, b) {
	local dx = b.x - a.x
	local dy = b.y - a.y
	local dz = b.z - a.z
	if ((dx * dx) + (dy * dy) + (dz * dz) < 1.0)
		return
	local life = CV_Life()
	local name = UniqueString("cv_shot")
	local startName = name + "_a"
	local endName = name + "_b"
	SpawnEntityFromTable("info_target", { targetname = startName, origin = a })
	SpawnEntityFromTable("info_target", { targetname = endName, origin = b })
	local beam = SpawnEntityFromTable("env_beam", {
		targetname = name,
		origin = a,
		LightningStart = startName,
		LightningEnd = endName,
		rendercolor = "255 255 255",
		renderamt = "255",
		rendermode = "0",
		BoltWidth = "4",
		life = life.tostring(),
		texture = "sprites/cv_tracer",
		TextureScroll = "0",
		framestart = "0",
		StrikeTime = "0",
		spawnflags = "1",
		TouchType = "0",
		damage = "0"
	})
	if (beam != null && NetProps.HasProp(beam, "m_nRenderMode"))
		NetProps.SetPropInt(beam, "m_nRenderMode", 0)
	EntFire(name, "TurnOn")
	EntFire(name, "Kill", "", life)
	EntFire(startName, "Kill", "", life)
	EntFire(endName, "Kill", "", life)
}

function CV_Owner(ent) {
	if (NetProps.HasProp(ent, "m_hThrower")) {
		local thrower = NetProps.GetPropEntity(ent, "m_hThrower")
		if (thrower != null)
			return thrower
	}
	if (NetProps.HasProp(ent, "m_hOwnerEntity"))
		return NetProps.GetPropEntity(ent, "m_hOwnerEntity")
	return null
}

function CV_IsSurvivor(ent) {
	if (ent == null)
		return false
	try {
		return ent.IsSurvivor()
	} catch (err) {
		return false
	}
}

function OnGameEvent_bullet_impact(params) {
	if (!::CVShotLinesEnabled)
		return
	local player = GetPlayerFromUserID(params.userid)
	if (!CV_IsSurvivor(player))
		return
	CV_Draw(CV_Eye(player), Vector(params.x, params.y, params.z))
}

function CV_TrackProjectiles() {
	local seen = {}
	foreach (cls in ::CVProjectileClasses) {
		local ent = null
		while (ent = Entities.FindByClassname(ent, cls)) {
			local owner = CV_Owner(ent)
			if (owner != null && !CV_IsSurvivor(owner))
				continue
			local id = ent.GetEntityIndex()
			local pos = ent.GetOrigin()
			seen[id] <- true
			if (id in ::CVProjLast) {
				local prev = ::CVProjLast[id]
				CV_Draw(prev, pos)
				::CVProjLast[id] = pos
			} else {
				if (CV_IsSurvivor(owner))
					CV_Draw(CV_Eye(owner), pos)
				::CVProjLast[id] <- pos
			}
		}
	}
	local stale = []
	foreach (id, prev in ::CVProjLast) {
		if (!(id in seen))
			stale.append(id)
	}
	foreach (id in stale)
		delete ::CVProjLast[id]
}

function CV_Set(name, value) {
	try {
		Convars.SetValue(name, value)
	} catch (err) {
	}
	local cmd = name + " " + value
	SendToServerConsole(cmd)
	SendToConsole(cmd)
}

function CV_ApplyCapture() {
__CAPTURE_CALLS__
	printl("[cv_infected] capture settings applied")
}

function CV_QueueCapture() {
	CV_ApplyCapture()
	::CVCaptureLeft = 1
	::CVCaptureAt = Time() + 1.0
}

function CV_ShotLineThink() {
	if (::CVShotLinesEnabled)
		CV_TrackProjectiles()
	if (::CVCaptureLeft > 0 && Time() >= ::CVCaptureAt) {
		CV_ApplyCapture()
		::CVCaptureLeft = 0
	}
	return 0.05
}

function CV_StartShotLines() {
	if (::CVShotLinesThinking)
		return
	AddThinkToEnt(self, "CV_ShotLineThink")
	::CVShotLinesThinking = true
}

function OnGameEvent_round_start(params) {
	CV_StartShotLines()
	CV_QueueCapture()
}

__CollectEventCallbacks(this, "OnGameEvent_", "GameEventCallbacks", RegisterScriptGameEventListener)
try {
	CV_StartShotLines()
} catch (err) {
	printl("[cv_infected] shot beams will start on round_start (" + err + ")")
}
try {
	CV_QueueCapture()
} catch (err) {
	printl("[cv_infected] capture settings will apply on round_start (" + err + ")")
}

printl("[cv_infected] shot beams " + CV_Life() + "s, rgb __R__ __G__ __B__. Disable: script CVShotLinesEnabled <- false")
"""


def _script() -> str:
    r, g, b = config.TRACER_COLOR
    calls = "\n".join(f'\tCV_Set("{name}", {value})' for name, value in config.CAPTURE_COMMANDS)
    return (
        SHOTLINES_NUT.replace("__TIME__", f"{config.TRACER_SECONDS:.2f}")
        .replace("__R__", str(r))
        .replace("__G__", str(g))
        .replace("__B__", str(b))
        .replace("__CAPTURE_CALLS__", calls)
    )


def _tracer_vmt() -> str:
    params = {
        "$basetexture": TRACER_TEXTURE,
        "$ignorez": "1",
        "$nocull": "1",
        "$nofog": "1",
        "$vertexcolor": "0",
        "$vertexalpha": "0",
        "$additive": "0",
        "$translucent": "0",
        "$nodecal": "1",
    }
    width = max(len(key) for key in params)
    lines = ["UnlitGeneric", "{"]
    for key, value in params.items():
        lines.append(f'\t{key.ljust(width)} "{value}"')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write(mani: manifest.Manifest, force: bool = False) -> bool:
    script = _script().encode("utf-8")
    vmt = _tracer_vmt().encode("utf-8")
    texture = vtf.build(config.TRACER_COLOR)
    key = manifest.sha(GENERATOR_VERSION, script, vmt, texture)
    unit = "scripts/shot_beams"
    script_path = config.BUILD / SCRIPT_REL
    vmt_path = config.BUILD / TRACER_VMT
    vtf_path = config.BUILD / TRACER_VTF
    if not force and mani.is_current(unit, key) and script_path.exists() and vmt_path.exists() and vtf_path.exists():
        mani.touch(unit)
        return False
    manifest.write_if_changed(script_path, script)
    manifest.write_if_changed(vmt_path, vmt)
    manifest.write_if_changed(vtf_path, texture)
    mani.record(unit, key, [script_path, vmt_path, vtf_path])
    return True
