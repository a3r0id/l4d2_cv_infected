# Infected CV Helper Overrides

Customizable Left 4 Dead 2 addon that modifies the infected models/FX/attacks to make them easier to see.

My initial goal was to make the infected easier to see for a computer vision project, but I've found it's really fun to play with.

### Features
- Infected models are replaced with depth-test ignored hitboxes. (X-Ray)
- Spitter puddles and Smoker tongues are also X-Ray.
- Player projectiles are temporarily annotated with a 3D line.
- Post-processing is optimized to provide a clear view of the scene, all without triggering common server-side checks.

While this does not break TOS and uses the official SDK, this will work in servers that allow custom addons (sv_cheats 1), while also bypassing the infected model integrity checks. In other words, this will work just fine on those custom Chinese servers.

Model overrides directly represent the hitboxes of the infected models.

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
| gibs    | 128, 0, 255   | Severed limbs and gibs (gore chunks)                |
| tracer  | 255, 0, 128   | Each shot, for half a second. Not an infected class |


The color is baked into the texture. L4D2's infected shader still recolors each common unless the material turns that off, which is why some stayed red, blue, or black. These materials set `$disablevariation 1` and `$allowdiffusemodulation 0` on `VertexLitGeneric`, and a white lightwarp keeps the lighting from shifting the RGB.

Colors live in `cvmod/config.py` (`CLASS_COLORS` and `TRACER_COLOR`). After editing them, run `make colors`.

## What gets replaced

1. **Materials.** Every infected VMT is replaced with a flat `VertexLitGeneric` material (`$ignorez`, `$nocull`, `$nofog`, variation disabled). Infected draw through walls and ignore fog.
2. **Meshes.** Each infected model is recompiled as boxes built from its own hitboxes, so the silhouette is the volume bullets actually test. Animations, grabs, and hitboxes are copied from the original model.
3. **Shots.** Each survivor bullet becomes a beam from the eyes to the server impact. A hit ends on the hitbox. A miss ends on the world. Grenades, molotovs, pipe bombs, and bile jars get the same beam while they fly. Beams last 0.5 seconds and use the tracer color, so a frame can score a hit when that color meets a class color.

Models that only exist to play animations, and loose gibs that carry their own sequences, keep their original mesh and get the flat material instead.

L4D1 campaigns and The Sacrifice do not use the base special models. Those maps spawn `hunter_l4d1`, `smoker_l4d1`, `boomer_l4d1`, and `hulk_l4d1`. A few Sacrifice maps spawn `hulk_dlc3` instead. The addon replaces those variants too. Common infected on those campaigns (`common_police_male01`, `common_male01`, `common_military_male01`, and the other L4D1 bodies) are included and colored pink.

## Installation

Build and install with:

```
make
```

That finds the Steam install of Left 4 Dead 2, packs `dist/cv_infected.vpk`, and copies it to that install's `left4dead2/addons/` folder. Enable **CV Infected Override** under Extras, then Add-ons.

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
| `make`                    | Full rebuild: index, materials, models, pack, and deploy                    |
| `make colors`             | Rebuild colours, pack, and deploy. Use this after editing `cvmod/config.py` |
| `make materials`          | Flat colours, the tracer beam, and the map script                           |
| `make models ONLY=hunter` | One proxy mesh                                                              |
| `make pack`               | Write `dist/cv_infected.vpk`                                                |
| `make deploy`             | Copy that VPK into the game's `left4dead2/addons/`                          |
| `make loose`              | Deploy an unpacked `addons/cv_infected/` folder                             |
| `make verify`             | Check the build tree                                                        |
| `make hlmv ONLY=hunter`   | Check the build and open that model in HLMV                                 |
| `make help`               | Print the targets                                                           |


`FORCE=1` rebuilds even when inputs have not changed. `KEEP=1` leaves the generated compile files on disk. Example: `make models ONLY=hunter FORCE=1`.

Unchanged files are skipped. Another addon that ships its own `models/infected/*.mdl` will fight this one. Only one of them wins.

## In game

This is a client addon. It works on public servers that allow addons. Nothing here has to be hosted by you.

Quit the game fully after installing. A running game keeps the addon it loaded at startup. In Extras, then Add-ons, **CV Infected Override** should say version **1.3**.

`make deploy` writes `left4dead2/cfg/cv_client.cfg` and runs it from `autoexec.cfg` and from the end of `valve.rc`. That turns on your own bullet tracers and the flat capture settings the next time the game starts. A config inside the addon cannot do that. The console prints `[cv_infected] client settings applied` when it runs.

Shots use the tracers the game already draws, recolored to **255, 0, 128**, from the muzzle to the impact. First-person tracers are off until `cv_client.cfg` runs.



## Known Issues

- When the spitter plays the spitting animation, it's model lies flat on the ground. Oddly enough, this seems to be true to the hitbox so it might be a win. Similar case with the Jockey when it's riding a survivor.
- Some backdrops make it hard to see infected. Also, proxy textures, like text on walls, usually have a higher priority than the override materials, so they can obscure the infected. The client settings applied at startup turn off the post-processing that makes this worse.

