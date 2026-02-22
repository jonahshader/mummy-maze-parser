"""Command-line interface for the Mummy Maze parser."""

import argparse
import sys
from pathlib import Path

from .parser import parse_file, render_maze


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Parse and display Mummy Maze Deluxe .dat level files."
  )
  parser.add_argument(
    "path",
    type=Path,
    help="path to a .dat file, or a directory containing .dat files",
  )
  parser.add_argument(
    "-n",
    "--count",
    type=int,
    default=10,
    help="number of sub-levels to display per file (default: 10)",
  )
  parser.add_argument(
    "-s",
    "--sublevel",
    type=int,
    default=None,
    help="display only this sub-level index",
  )
  parser.add_argument(
    "--header-only",
    action="store_true",
    help="only print file header info, no maze rendering",
  )
  args = parser.parse_args()

  if args.path.is_dir():
    files = sorted(
      args.path.glob("B-*.dat"),
      key=lambda p: int(p.stem.split("-")[1]),
    )
  elif args.path.is_file():
    files = [args.path]
  else:
    print(f"Not found: {args.path}", file=sys.stderr)
    sys.exit(1)

  if not files:
    print(f"No .dat files found in {args.path}", file=sys.stderr)
    sys.exit(1)

  for filepath in files:
    parsed = parse_file(filepath)
    if parsed is None:
      print(f"{filepath.name}: empty or invalid")
      continue

    header = parsed.header
    sublevels = parsed.sublevels
    gs = header.grid_size
    mummy_type = "red" if header.flip else "white"
    print(f"File: {filepath.name}")
    print(f"  Grid: {gs}x{gs}, Mummy type: {mummy_type}")
    print(f"  Sub-levels: {len(sublevels)} ({header.bytes_per_sub} bytes each)")
    print(
      f"  Mummies: {header.mummy_count},"
      f" Key/Gate: {header.key_gate},"
      f" Traps: {header.trap_count},"
      f" Scorpion: {header.scorpion}"
    )

    if args.header_only:
      print()
      continue

    if args.sublevel is not None:
      indices = [args.sublevel] if args.sublevel < len(sublevels) else []
    else:
      indices = list(range(min(args.count, len(sublevels))))

    for i in indices:
      level = sublevels[i]
      ent_parts = [f"{e.type.value}=({e.col},{e.row})" for e in level.entities]
      print()
      print(f"  {'=' * 50}")
      print(f"  Sub-level {i}  |  Exit: {level.exit_side}{level.exit_pos}")
      print(f"    {', '.join(ent_parts)}")
      print(f"  {'=' * 50}")
      for line in render_maze(level, gs).splitlines():
        print(f"  {line}")
    print()


if __name__ == "__main__":
  main()
