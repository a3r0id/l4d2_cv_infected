"""Build the Left 4 Dead 2 computer-vision infected override addon.

Examples:
    python main.py index                 # map every infected material to a class
    python main.py materials             # phase 1: flat x-ray colours
    python main.py models --only hunter  # phase 2: hitbox proxy mesh for one model
    python main.py all                   # index + materials + models + pack + deploy
    python main.py deploy --loose        # fast iteration, no VPK repack
    python main.py verify --only hunter  # open the result in HLMV
"""

from __future__ import annotations

import argparse
import sys
import time

from cvmod import config, index as index_mod, manifest


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def cmd_index(args: argparse.Namespace) -> int:
    _print_header("index")
    idx = index_mod.build()
    index_mod.save(idx)
    print(index_mod.report(idx))
    print(f"wrote {config.INDEX_JSON}")
    print(f"wrote {config.INDEX_REPORT}")
    return 0


def cmd_materials(args: argparse.Namespace) -> int:
    from cvmod import materials

    _print_header("materials (phase 1)")
    idx = index_mod.load()
    mani = manifest.Manifest.load()
    result = materials.build(idx, mani, force=args.force, only=args.only)
    mani.save()
    manifest.remove_empty_dirs(config.BUILD)
    print(result.summary())
    return 1 if result.stats.failed else 0


def cmd_models(args: argparse.Namespace) -> int:
    from cvmod import proxy

    _print_header("models (phase 2)")
    idx = index_mod.load()
    mani = manifest.Manifest.load()
    result = proxy.build(idx, mani, force=args.force, only=args.only, keep_work=args.keep_work)
    mani.save()
    manifest.remove_empty_dirs(config.BUILD)
    print(result.summary())
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    from cvmod import pack

    _print_header("pack")
    path = pack.build_vpk()
    print(f"wrote {path} ({path.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    from cvmod import pack

    _print_header("deploy")
    try:
        targets = pack.deploy(loose=args.loose)
    except PermissionError as exc:
        print(exc, file=sys.stderr)
        return 1
    for target in targets:
        print(f"deployed {target}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from cvmod import pack, verify

    _print_header("verify")
    idx = index_mod.load()
    report = verify.run(idx)
    print(report)
    print("\ncolour assignment:")
    print(verify.color_table(idx))
    if args.hlmv:
        pack.open_hlmv(args.only or "hunter")
    return 0 if report.ok else 1


def cmd_all(args: argparse.Namespace) -> int:
    steps = [cmd_index, cmd_materials, cmd_models, cmd_pack, cmd_deploy]
    for step in steps:
        code = step(args)
        if code:
            return code
    return 0


COMMANDS = {
    "index": cmd_index,
    "materials": cmd_materials,
    "models": cmd_models,
    "pack": cmd_pack,
    "deploy": cmd_deploy,
    "verify": cmd_verify,
    "all": cmd_all,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "commands",
        nargs="+",
        choices=sorted(COMMANDS),
        help="one or more pipeline stages, run in the order given",
    )
    parser.add_argument("--only", help="limit to models/materials whose name contains this")
    parser.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    parser.add_argument("--loose", action="store_true", help="deploy an unpacked addon folder instead of a VPK")
    parser.add_argument("--keep-work", action="store_true", help="keep generated QC/SMD and studiomdl logs")
    parser.add_argument("--hlmv", action="store_true", help="also open the model viewer during verify")
    args = parser.parse_args(argv)

    if not config.SRC.exists():
        print(f"error: extracted game assets not found at {config.SRC}", file=sys.stderr)
        return 2

    start = time.monotonic()
    for name in args.commands:
        code = COMMANDS[name](args)
        if code:
            return code
    print(f"\ndone in {time.monotonic() - start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
