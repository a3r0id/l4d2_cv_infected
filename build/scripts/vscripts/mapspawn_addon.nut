// cv_infected shot lines.
//
// Draws the path of every survivor shot for a few seconds so the spread can be
// compared with the hitbox meshes. Hitscan pellets are lines from the eyes to
// the server impact. Thrown and launched projectiles leave a trail.
//
// Listen-server host only (engine debug overlay). Toggle from the console:
//   script CVShotLinesEnabled <- false
//   script CVShotLinesEnabled <- true
//   script CVShotLinesTime <- 6

::CVShotLinesEnabled <- true
::CVShotLinesTime <- 6.0

// Unused by the class colour table, so a line crossing an infected is obvious.
::CVShotLineR <- 255
::CVShotLineG <- 0
::CVShotLineB <- 128

::CVProjectileClasses <- [
	"grenade_launcher_projectile",
	"molotov_projectile",
	"pipe_bomb_projectile",
	"vomitjar_projectile"
]

::CVProjLast <- {}
::CVShotLinesThinking <- false

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
	DebugDrawLine(a, b, ::CVShotLineR, ::CVShotLineG, ::CVShotLineB, true, ::CVShotLinesTime)
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
				local dx = pos.x - prev.x
				local dy = pos.y - prev.y
				local dz = pos.z - prev.z
				if ((dx * dx) + (dy * dy) + (dz * dz) > 1.0)
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

function CV_ShotLineThink() {
	if (::CVShotLinesEnabled)
		CV_TrackProjectiles()
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
}

__CollectEventCallbacks(this, "OnGameEvent_", "GameEventCallbacks", RegisterScriptGameEventListener)
try {
	CV_StartShotLines()
} catch (err) {
	printl("[cv_infected] shot lines will start on round_start (" + err + ")")
}

printl("[cv_infected] shot lines on for " + ::CVShotLinesTime + "s. Disable: script CVShotLinesEnabled <- false")
