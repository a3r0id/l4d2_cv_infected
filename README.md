# Infected CV Helper Overrides

Customizable Left 4 Dead 2 addon that modifies the infected models/FX/attacks to make them easier to see.

My initial goal was to make the infected easier to see for a computer vision project, but I've found it's really fun to play with.

### Features

| Feature | Flag | Regular server | Addon server | `sv_cheats 1` |
| ------- | ---- | :------------: | :----------: | :-----------: |
| Infected hitbox X-ray (color per class) | core | ✗ | ✓ | ✓ |
| Spitter puddles and smoker tongue X-ray | core | ✗ | ✓ | ✓ |
| Consumable pickups X-ray (stock textures, brightened) | `--feat-override-consumables` | ✗ | ✓ | ✓ |
| Recolored client bullet tracers + capture HUD/view settings | `--feat-trace` | ✗ | ✓ | ✓ |
| Scripted 3D shot beams (`mapspawn_addon.nut`) | `--feat-trace` | ✗ | ✗ | ✓ |
| Cap ragdolls/decals; C clears clutter | `--feat-cleanup` | ✓ | ✓ | ✓ |
| Custom sound replacements from `config.json` | `--feat-sounds` | ✓ | ✓ | ✓ |

**Regular server** = official or stock public server that blocks client addons. 
**Addon server** = allows custom client VPKs (many custom/community servers). 
**`sv_cheats 1`** = listen/local host where cheat convars and addon VScript can run.

*This does not break Valve TOS and uses the official SDK. Model/material overrides need a server that allows addons. Scripted shot beams need a host with `sv_cheats 1`. Cleanup and custom sounds are loose client files, so they still run on regular servers. Cheaters suck — please don't use this to achieve some imaginary competitive edge; This is just for fun, mess around with it in expert mode!*

[Clip: CV Override Initial Test](https://medal.tv/games/left-4-dead-2/clips/nFNBhWZWYpHmz7Ptk?invite=cr-MSx0N2MsMTczMjc5NzQ3)

![image](https://github.com/user-attachments/assets/0ac03cbd-5a4d-46ca-ae2d-054570b95012)

![image](https://github.com/user-attachments/assets/d1600b86-c593-4655-8d08-abad61e715ff)

Special infected are one color per class. Every common infected, including the L4D1 and DLC bodies (police, military, nurse, rural, formal, and the rest), is the same pink.

## Colors


| Class   | RGB           | Where it shows up                                   |
| ------- | ------------- | --------------------------------------------------- |
| common  | 255, 0, 255   | All common infected                                 |
| hunter  | 0, 255, 255   | Hunter, including `hunter_l4d1`                     |
| smoker  | 255, 128, 0   | Smoker, including `smoker_l4d1` and the tongue      |
| tank    | 0, 0, 255     | Tank: `hulk`, `hulk_l4d1`, `hulk_dlc3`              |
| boomer  | 0, 255, 0     | Boomer, boomette, `boomer_l4d1`                     |
| charger | 255, 0, 0     | Charger                                             |
| jockey  | 255, 255, 0   | Jockey                                              |
| spitter | 0, 255, 128   | Spitter                                             |
| witch   | 255, 255, 255 | Witch and witch bride                               |
| gibs    | 0, 0, 0       | Severed limbs and gibs (gore chunks)                |
| consumable | stock + brighten | Medkits, pills, adrenaline, defibs, molotovs, pipe bombs, bile, incendiary ammo |
| explosive ammo | 255, 200, 0 | Explosive ammo packs — flat bright gold (tunable via `explosive_ammo_color`) |
| tracer  | 255, 0, 128   | Each shot, for half a second. Not an infected class |


The color is baked into the texture. These materials set `$disablevariation 1` and `$allowdiffusemodulation 0` on `VertexLitGeneric`, and `$selfillum 1` so shadows do not dim them.

Colors and other tunables live in `config.json` (`class_colors`, `tracer_color`, commands, material lists). After editing them, run `make colors`.

## What gets replaced

1. **Materials.** Every infected VMT is replaced with a flat `VertexLitGeneric` material (`$ignorez`, `$nocull`, `$nofog`, variation disabled, self-illuminated). They draw through walls and ignore fog. With `--feat-override-consumables`, most pickup materials keep their stock textures, get `$ignorez`, and are brightened via `consumable_brightness`; explosive ammo packs become flat bright gold (`explosive_ammo_color`).
2. **Meshes.** The stock infected mesh is kept. Servers consistency-check `models/infected/*.mdl` and disconnect if the file differs (`hunter_l4d1.mdl` and the rest). The flat materials are what recolor that stock mesh. Proxy hitbox meshes are still built locally for checks, and they are not packed into the addon.
3. **Shots.** With `--feat-trace`, each survivor bullet becomes a beam from the eyes to the server impact. A hit ends on the hitbox. A miss ends on the world. Grenades, molotovs, pipe bombs, and bile jars get the same beam while they fly. Beams last 0.5 seconds and use the tracer color.

Models that only exist to play animations, and loose gibs that carry their own sequences, keep their original mesh and get the flat material instead.

L4D1 campaigns and The Sacrifice spawn `hunter_l4d1`, `smoker_l4d1`, `boomer_l4d1`, and `hulk_l4d1` (some Sacrifice maps use `hulk_dlc3`). Their materials are recolored the same way. The model files themselves are not replaced, so a consistency check on those names does not fail.

## Installation

*If you only need the core overrides then simply move [the VPK addon](https://github.com/a3r0id/l4d2_cv_infected/blob/main/dist/cv_infected.vpk) to path/to/your/L4D2/addons/cv_infected.vpk.*

Build and install the core infected overrides with:

```
make
```

Optional features:

```
make CONSUMABLES=1
make TRACE=1
make CLEANUP=1
make SOUNDS=1
make CONSUMABLES=1 TRACE=1 CLEANUP=1 SOUNDS=1
```

Or with `main.py`:

```
python main.py all --feat-override-consumables
python main.py all --feat-trace
python main.py all --feat-cleanup
python main.py all --feat-sounds
python main.py all --feat-override-consumables --feat-trace --feat-cleanup --feat-sounds
```

That finds the Steam install of Left 4 Dead 2, packs `dist/cv_infected.vpk`, and copies it to that install's `left4dead2/addons/` folder. Each deploy overwrites the previous addon and removes loose client cfg hooks / custom sounds that the selected features do not need. Enable **CV Infected Override** under Extras, then Add-ons.

Close the game before deploying. A running game locks the VPK, and it keeps whatever addon it loaded at startup. Quit fully, then launch again.

## Building

First, you'll need to extract the assets from the game.

```
python extract.py
```

This will create a `l4d2` folder with the extracted assets.

Then, you can build the addon.

Run these from this directory. `make help` prints the same list.


| Command                   | What it does                                                                |
| ------------------------- | --------------------------------------------------------------------------- |
| `make`                    | Full rebuild: index, materials, models, pack, and deploy (infected only)    |
| `make colors`             | Rebuild colours, pack, and deploy. Use this after editing `config.json`     |
| `make materials`          | Flat colours for the selected features                                      |
| `make models ONLY=hunter` | One proxy mesh                                                              |
| `make pack`               | Write `dist/cv_infected.vpk`                                                |
| `make deploy`             | Fresh-install that VPK into the game's `left4dead2/addons/`                 |
| `make loose`              | Deploy an unpacked `addons/cv_infected/` folder                             |
| `make verify`             | Check the build tree for the selected features                              |
| `make hlmv ONLY=hunter`   | Check the build and open that model in HLMV                                 |
| `make help`               | Print the targets                                                           |


`FORCE=1` rebuilds even when inputs have not changed. `KEEP=1` leaves the generated compile files on disk. `CONSUMABLES=1`, `TRACE=1`, `CLEANUP=1`, and `SOUNDS=1` enable the optional features. Example: `make models ONLY=hunter FORCE=1`.

Unchanged files are skipped. The packed addon does not contain `models/infected/*.mdl`, so it does not trip the server consistency check on those files.

## In game

This is a client addon. It works on public servers that allow addons. Nothing here has to be hosted by you.

Quit the game fully after installing. A running game keeps the addon it loaded at startup. In Extras, then Add-ons, **CV Infected Override** should say version **1.8**.

With `TRACE=1` / `--feat-trace`, deploy also writes `left4dead2/cfg/cv_client.cfg` and runs it from `autoexec.cfg` and from the end of `valve.rc`. Without that flag, deploy removes those hooks. A config inside the addon cannot be exec'd. The console prints `[cv_infected] client settings applied` when the client cfg runs.

With `CLEANUP=1` / `--feat-cleanup`, deploy writes `left4dead2/cfg/cv_cleanup.cfg` and execs it from `autoexec.cfg` and `valve.rc`. It keeps `MOUSE1` on `+attack` (required for the "Press [key] to play as ..." glyph), leaves scope on `MOUSE3`, caps ragdolls/decals, and binds `C` to clear clutter on demand. Without the flag, deploy removes that cfg and restores stock `MOUSE1`/`MOUSE3`/`C` binds.

With `SOUNDS=1` / `--feat-sounds`, deploy converts each entry under `custom_sound_generator` in `config.json` (MP3 via ffmpeg) to 16-bit 44.1 kHz WAV and writes the listed destinations under the game install. Without the flag, those loose overrides are deleted so the stock VPK sounds return. Needs `ffmpeg` on PATH.

Shots use the tracers the game already draws, recolored to **255, 0, 128**, from the muzzle to the impact. First-person tracers are off until `cv_client.cfg` runs.



## Known Issues

- When the spitter plays the spitting animation, it's model lies flat on the ground. Oddly enough, this seems to be true to the hitbox so it might be a win. Similar case with the Jockey when it's riding a survivor.
- Some backdrops make it hard to see infected. Also, proxy textures, like text on walls, usually have a higher priority than the override materials, so they can obscure the infected. The client settings applied at startup turn off the post-processing that makes this worse.
- Map corpse props use the body-pile materials (`bp*`, including `bp_body_include` / `bp_head_include`). Those stay stock. Live commons use `cim_*` / `cif_*` and stay flat.

