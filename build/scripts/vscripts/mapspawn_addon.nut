// cv_infected shot beams.
//
// One beam per server bullet trace, from the eyes (the start of the collision
// test) to the impact. Colour is sprites/cv_tracer, which is not an infected
// class, so a capture can score a hit when this colour meets a class colour.
// Beams are removed in under a second.
//
//   script CVShotLinesEnabled <- false
//   script CVShotLinesEnabled <- true

if (!("CVShotLinesEnabled" in getroottable()))
	::CVShotLinesEnabled <- true
if (!("CVShotLinesTime" in getroottable()))
	::CVShotLinesTime <- 0.50

::CVProjectileClasses <- [
	"grenade_launcher_projectile",
	"molotov_projectile",
	"pipe_bomb_projectile",
	"vomitjar_projectile"
]

if (!("CVProjLast" in getroottable()))
	::CVProjLast <- {}
if (!("CVShotLinesThinking" in getroottable()))
	::CVShotLinesThinking <- false
if (!("CVCaptureLeft" in getroottable()))
	::CVCaptureLeft <- 0
if (!("CVCaptureAt" in getroottable()))
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
	// Host overlay. This one does not depend on a material being precached.
	DebugDrawLine(a, b, 255, 0, 128, true, life)
	local name = UniqueString("cv_shot")
	local startName = name + "_a"
	local endName = name + "_b"
	SpawnEntityFromTable("info_target", { targetname = startName, origin = a })
	SpawnEntityFromTable("info_target", { targetname = endName, origin = b })
	// Stock beam material, already in the game, so the line is in the frame
	// a capture samples. rendermode 5 is additive, which laserbeam requires.
	local beam = SpawnEntityFromTable("env_beam", {
		targetname = name,
		origin = a,
		LightningStart = startName,
		LightningEnd = endName,
		rendercolor = "255 0 128",
		renderamt = "255",
		rendermode = "5",
		BoltWidth = "2",
		life = life.tostring(),
		texture = "sprites/laserbeam.spr",
		TextureScroll = "0",
		framestart = "0",
		StrikeTime = "0",
		spawnflags = "1",
		TouchType = "0",
		damage = "0"
	})
	if (beam != null && NetProps.HasProp(beam, "m_nRenderMode"))
		NetProps.SetPropInt(beam, "m_nRenderMode", 5)
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
	CV_Set("sv_cheats", 1)
	CV_Set("mat_hdr_level", 0)
	CV_Set("mat_bloomscale", 0)
	CV_Set("mat_disable_bloom", 1)
	CV_Set("mat_colorcorrection", 0)
	CV_Set("mat_motion_blur_enabled", 0)
	CV_Set("mat_grain_scale_override", 0)
	CV_Set("mat_antialias", 0)
	CV_Set("mat_software_aa_strength", 0)
	CV_Set("mat_specular", 0)
	CV_Set("r_dynamic", 0)
	CV_Set("muzzleflash_light", 0)
	CV_Set("fog_override", 1)
	CV_Set("fog_enable", 0)
	CV_Set("r_drawviewmodel", 0)
	CV_Set("cl_drawhud", 0)
	CV_Set("net_graph", 0)
	CV_Set("sv_consistency", 0)
	CV_Set("sv_pure", 0)
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

try {
	__CollectEventCallbacks(this, "OnGameEvent_", "GameEventCallbacks", RegisterScriptGameEventListener)
} catch (err) {
	RegisterScriptGameEventListener("bullet_impact")
	RegisterScriptGameEventListener("round_start")
	printl("[cv_infected] event hook fallback (" + err + ")")
}
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

printl("[cv_infected] shot beams " + CV_Life() + "s, rgb 255 0 128. Disable: script CVShotLinesEnabled <- false")
