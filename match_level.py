"""Match an editor-exported maze against all parsed .dat files.

Usage:
    python match_level.py <maze_dir> [--walls WALL_FLAGS] [--entities ENTITIES]
                                     [--exit EXIT] [--red] [--top N]

Or paste editor output interactively:
    python match_level.py <maze_dir> --interactive
"""

import argparse
import ast
import json
import sys
from pathlib import Path

from mummy_maze import WALL_EAST, WALL_NORTH, WALL_SOUTH, WALL_WEST, parse_file, render_maze


def rotate90(grid, n):
    """Rotate wall flags 90 degrees clockwise."""
    out = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            v = grid[r][c]
            nv = 0
            if v & WALL_NORTH: nv |= WALL_WEST
            if v & WALL_EAST:  nv |= WALL_NORTH
            if v & WALL_SOUTH: nv |= WALL_EAST
            if v & WALL_WEST:  nv |= WALL_SOUTH
            out[c][n - 1 - r] = nv
    return out


def flip_h(grid, n):
    """Flip wall flags horizontally (mirror left-right)."""
    out = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            v = grid[r][c]
            nv = 0
            if v & WALL_NORTH: nv |= WALL_NORTH
            if v & WALL_SOUTH: nv |= WALL_SOUTH
            if v & WALL_EAST:  nv |= WALL_WEST
            if v & WALL_WEST:  nv |= WALL_EAST
            out[r][n - 1 - c] = nv
    return out


def all_transforms(flat, n):
    """Yield all 8 dihedral symmetry transforms as (label, flat_list)."""
    grid = [flat[i * n:(i + 1) * n] for i in range(n)]
    for flip_label, fg in [("id", grid), ("fh", flip_h(grid, n))]:
        cur = [row[:] for row in fg]
        for rot in range(4):
            label = f"{flip_label}_r{rot * 90}"
            yield label, [cur[r][c] for r in range(n) for c in range(n)]
            cur = rotate90(cur, n)


def match_entities(parsed_ents, target_ents):
    """Score entity matches. Mummies matched by position set, not order."""
    score = 0
    total = 0

    if "player" in target_ents:
        total += 1
        if parsed_ents.get("player") == target_ents["player"]:
            score += 1

    target_mummies = {v for k, v in target_ents.items() if "mummy" in k}
    parsed_mummies = {v for k, v in parsed_ents.items() if "mummy" in k}
    total += len(target_mummies)
    score += len(target_mummies & parsed_mummies)

    for key in ("scorpion", "key"):
        if key in target_ents:
            total += 1
            if parsed_ents.get(key) == target_ents[key]:
                score += 1

    target_traps = {v for k, v in target_ents.items() if "trap" in k}
    parsed_traps = {v for k, v in parsed_ents.items() if "trap" in k}
    total += len(target_traps)
    score += len(target_traps & parsed_traps)

    return score, total


def parse_interactive():
    """Parse pasted editor output from stdin."""
    print("Paste editor export, then press Enter twice (or Ctrl+D):", file=sys.stderr)
    lines = []
    blank_count = 0
    try:
        while True:
            line = input()
            if line.strip() == "":
                blank_count += 1
                if blank_count >= 2:
                    break
            else:
                blank_count = 0
            lines.append(line)
    except EOFError:
        pass

    text = "\n".join(lines)
    wall_flags = None
    entities = None
    red = None
    exit_info = None
    grid_size = None

    for line in lines:
        line = line.strip()
        if line.startswith("wall_flags"):
            wall_flags = ast.literal_eval(line.split("=", 1)[1].strip())
        elif line.startswith("entities"):
            raw = json.loads(line.split("=", 1)[1].strip())
            entities = {k: tuple(v) for k, v in raw.items()}
        elif line.startswith("red"):
            val = line.split("=", 1)[1].strip()
            red = val in ("True", "true")
        elif line.startswith("exit_info"):
            val = line.split("=", 1)[1].strip()
            if val != "None":
                exit_info = json.loads(val)
        elif line.startswith("Grid:"):
            grid_size = int(line.split(":")[1].strip().split("x")[0])

    return wall_flags, entities, red, exit_info, grid_size


def main():
    parser = argparse.ArgumentParser(description="Match editor maze against .dat files.")
    parser.add_argument("maze_dir", type=Path, help="directory containing B-*.dat files")
    parser.add_argument("--walls", type=str, help="wall_flags as Python list literal")
    parser.add_argument("--entities", type=str, help="entities as JSON dict")
    parser.add_argument("--exit", type=str, help='exit info as JSON, e.g. {"side":"N","pos":3}')
    parser.add_argument("--red", action="store_true", help="level uses red mummies")
    parser.add_argument("--top", type=int, default=5, help="number of top matches to show")
    parser.add_argument("--interactive", "-i", action="store_true", help="paste editor output")
    args = parser.parse_args()

    if args.interactive:
        wall_flags, entities, red, exit_info, grid_size = parse_interactive()
    else:
        wall_flags = ast.literal_eval(args.walls) if args.walls else None
        entities = {k: tuple(v) for k, v in json.loads(args.entities).items()} if args.entities else {}
        red = args.red
        exit_info = json.loads(args.exit) if args.exit else None
        grid_size = None

    if wall_flags is None:
        print("No wall_flags provided.", file=sys.stderr)
        sys.exit(1)

    # Infer grid size from wall_flags length
    n_cells = len(wall_flags)
    if grid_size is None:
        for gs in (6, 8, 10):
            if gs * gs == n_cells:
                grid_size = gs
                break
    if grid_size is None:
        print(f"Cannot infer grid size from {n_cells} cells.", file=sys.stderr)
        sys.exit(1)

    N = grid_size
    if entities is None:
        entities = {}

    # Collect matches
    best = []
    dat_files = sorted(args.maze_dir.glob("B-*.dat"), key=lambda p: int(p.stem.split("-")[1]))

    for filepath in dat_files:
        result = parse_file(filepath)
        if result is None:
            continue
        header, sublevels = result
        if header["grid_size"] != N:
            continue

        fi = int(filepath.stem.split("-")[1])

        for si, level in enumerate(sublevels):
            cells_flat = [level["cells"][r][c] for r in range(N) for c in range(N)]
            ent_score, ent_total = match_entities(level["entities"], entities)

            for tlabel, tflat in all_transforms(wall_flags, N):
                wall_match = sum(1 for a, b in zip(tflat, cells_flat) if a == b)
                best.append((wall_match, ent_score, ent_total, fi, si, tlabel, header["flip"]))

    best.sort(key=lambda x: (-x[0], -x[1]))

    print(f"Searched {len(dat_files)} files, {len(best) // 8} sub-levels")
    print(f"Target: {N}x{N}, {'red' if red else 'white'} mummies, {len(entities)} entities")
    print()

    shown = set()
    count = 0
    for wall_match, ent_score, ent_total, fi, si, tlabel, flip in best:
        if count >= args.top:
            break
        key = (fi, si)
        if key in shown:
            continue
        shown.add(key)
        count += 1

        pct = wall_match * 100 // (N * N)
        flip_str = "red" if flip else "white"
        print(f"B-{fi} sub-{si}: {wall_match}/{N*N} walls ({pct}%), "
              f"entities={ent_score}/{ent_total}, transform={tlabel}, type={flip_str}")

        result = parse_file(args.maze_dir / f"B-{fi}.dat")
        _, sublevels = result
        level = sublevels[si]
        print(f"  Exit: {level['exit_side']}{level['exit_pos']}")
        for name, pos in level["entities"].items():
            print(f"  {name}: {pos}")
        for line in render_maze(level, N).splitlines():
            print(f"  {line}")
        print()


if __name__ == "__main__":
    main()
