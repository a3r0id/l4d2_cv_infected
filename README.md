# Infected Helper Overrides

Customizable Left 4 Dead 2 addon that modifies the infected models to make them easier to see.
Also makes spitter puddles visible through walls and makes tracers easier to see.

Model overrides directly represent the hitboxes of the infected models.

<img width="2560" height="1437" alt="image" src="https://github.com/user-attachments/assets/0ac03cbd-5a4d-46ca-ae2d-054570b95012" />

<img width="2561" height="1438" alt="image" src="https://github.com/user-attachments/assets/d1600b86-c593-4655-8d08-abad61e715ff" />

Special infected are one color per class. Every common infected, including the L4D1 and DLC bodies (police, military, nurse, rural, formal, and the rest), is the same pink.

## Colors

| Class | RGB | Where it shows up |
| --- | --- | --- |
| common | 255, 0, 255 | All common infected |
| hunter | 0, 255, 255 | Hunter, including `hunter_l4d1` |
| smoker | 255, 128, 0 | Smoker, including `smoker_l4d1` |
| tank | 0, 0, 255 | Tank: `hulk`, `hulk_l4d1`, `hulk_dlc3` |
| boomer | 0, 255, 0 | Boomer, boomette, `boomer_l4d1` |
| charger | 255, 0, 0 | Charger |
| jockey | 255, 255, 0 | Jockey |
| spitter | 0, 255, 128 | Spitter |
| witch | 255, 255, 255 | Witch and witch bride |
| gibs | 128, 0, 255 | Severed limbs and gibs |

## Customization

You can easily rebuild the addon with your own colors. The colors are baked into the textures, so you can make them whatever you want.

This can be configured in the config.py file and rebuilt with the `python main.py materials pack deploy` command.

1. **Materials.** Every infected VMT is replaced with an unlit material (`$ignorez`, `$nocull`, `$nofog`). Infected draw through walls and ignore fog.
2. **Meshes.** Each infected model is recompiled as boxes built from its own hitboxes, so the silhouette is the volume bullets actually test. Animations, grabs, and hitboxes are copied from the original model.

## Building your own version

The game install is found through Steam, or from `L4D2_DIR` if you set that to the folder containing `left4dead2.exe`.

From this directory, with the extracted assets in `l4d2/`:

```
python main.py all
```

That rebuilds the material index, writes materials and proxy models, packs `dist/cv_infected.vpk`, and copies it to `left4dead2/addons/`. Unchanged files are skipped.

Useful pieces:

```
python main.py index                  # map models and materials to classes
python main.py materials              # flat colors only
python main.py models --only hunter   # one proxy mesh
python main.py pack deploy            # pack and install
python main.py verify                 # check the build tree
python main.py verify --hlmv --only hunter
```

`--force` rebuilds even when inputs have not changed. `--loose` on `deploy` installs an unpacked `addons/cv_infected/` folder instead of the VPK.

Colors live in `cvmod/config.py` (`CLASS_COLORS`). After editing them, run `python main.py materials pack deploy`.

## In game

Enable **CV Infected Override** under Extras, then Add-ons. Restart the game after installing the addon; a running game keeps the previous VPK loaded. In the console:

```
exec cv_capture
```

That turns off HDR, bloom, color correction, film grain, and fog so the framebuffer stays close to the authored RGB. It also sets `sv_pure 0` and `sv_consistency 0`, which a listen server needs in order to load the addon models.

The addon has to load. If another addon ships its own `models/infected/*.mdl`, only one of them wins.

## Some Notes

- Models that only exist to play animations, and loose gibs that carry their own sequences, keep their original mesh and get the flat material instead.

- L4D1 campaigns and The Sacrifice do not use the base special models. Those maps spawn `hunter_l4d1`, `smoker_l4d1`, `boomer_l4d1`, and `hulk_l4d1`. A few Sacrifice maps spawn `hulk_dlc3` instead. The addon replaces those variants too. Common infected on those campaigns (`common_police_male01`, `common_male01`, `common_military_male01`, and the other L4D1 bodies) are included and colored pink.

## Known Issues

- When the spitter plays the spitting animation, it lies flat on the ground.

- Some backdrops make it hard to see infected. Also, proxy textures, like text on walls, usually have a higher priority than the override materials, so they can obscure the infected. The `cv_capture` console command helps with that.
