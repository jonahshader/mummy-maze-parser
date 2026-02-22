"""Maze matching: find .dat sub-levels that match editor-drawn wall patterns."""

from dataclasses import dataclass
from pathlib import Path

from .parser import (
  Entity,
  EntityType,
  Grid,
  SubLevel,
  parse_file,
  render_maze,
)

WallPair = tuple[Grid, Grid]


@dataclass
class MatchResult:
  file_index: int
  sublevel_index: int
  wall_score: int
  wall_total: int
  entity_score: int
  entity_total: int
  transform: str
  flip: bool
  ascii_render: str
  exit_side: str
  exit_pos: int
  entities: list[Entity]


def bitmask_to_edges(flat: list[int], n: int) -> WallPair:
  """Convert flat per-cell bitmasks (old format) to (h_walls, v_walls) edge arrays.

  Bitmask flags: NORTH=0x08, SOUTH=0x04, EAST=0x02, WEST=0x01.
  """
  h_walls: Grid = [[False] * n for _ in range(n + 1)]
  v_walls: Grid = [[False] * (n + 1) for _ in range(n)]

  for r in range(n):
    for c in range(n):
      v = flat[r * n + c]
      if v & 0x08:  # NORTH
        h_walls[r][c] = True
      if v & 0x04:  # SOUTH
        h_walls[r + 1][c] = True
      if v & 0x01:  # WEST
        v_walls[r][c] = True
      if v & 0x02:  # EAST
        v_walls[r][c + 1] = True

  return h_walls, v_walls


def rotate90(walls: WallPair, n: int) -> WallPair:
  """Rotate wall edges 90 degrees clockwise.

  Cell (r, c) maps to (c, N-1-r).
  Top edge -> right edge, left edge -> top edge.
  """
  old_h, old_v = walls
  new_h: Grid = [[False] * n for _ in range(n + 1)]
  new_v: Grid = [[False] * (n + 1) for _ in range(n)]

  for r in range(n + 1):
    for c in range(n):
      new_v[c][n - r] = old_h[r][c]

  for r in range(n):
    for c in range(n + 1):
      new_h[c][n - 1 - r] = old_v[r][c]

  return new_h, new_v


def flip_h(walls: WallPair, n: int) -> WallPair:
  """Flip wall edges horizontally (mirror left-right).

  Cell (r, c) maps to (r, N-1-c).
  """
  old_h, old_v = walls
  new_h: Grid = [[False] * n for _ in range(n + 1)]
  new_v: Grid = [[False] * (n + 1) for _ in range(n)]

  for r in range(n + 1):
    for c in range(n):
      new_h[r][c] = old_h[r][n - 1 - c]

  for r in range(n):
    for c in range(n + 1):
      new_v[r][c] = old_v[r][n - c]

  return new_h, new_v


def _flatten_walls(walls: WallPair) -> list[bool]:
  """Flatten (h_walls, v_walls) into a single list for comparison."""
  h, v = walls
  flat: list[bool] = []
  for row in h:
    flat.extend(row)
  for row in v:
    flat.extend(row)
  return flat


def all_transforms(walls: WallPair, n: int) -> list[tuple[str, list[bool]]]:
  """Return all 8 dihedral symmetry transforms as (label, flat_list)."""
  results: list[tuple[str, list[bool]]] = []
  for flip_label, fw in [("id", walls), ("fh", flip_h(walls, n))]:
    cur = fw
    for rot in range(4):
      label = f"{flip_label}_r{rot * 90}"
      results.append((label, _flatten_walls(cur)))
      cur = rotate90(cur, n)
  return results


def _positions_of(entities: list[Entity], etype: EntityType) -> set[tuple[int, int]]:
  """Get the set of (col, row) positions for a given entity type."""
  return {(e.col, e.row) for e in entities if e.type == etype}


def match_entities(
  parsed: list[Entity],
  target: list[Entity],
) -> tuple[int, int]:
  """Score entity matches. Entities of the same type matched by position set."""
  score = 0
  total = 0

  for etype in EntityType:
    parsed_positions = _positions_of(parsed, etype)
    target_positions = _positions_of(target, etype)
    total += len(target_positions)
    score += len(target_positions & parsed_positions)

  return score, total


def find_matches(
  wall_flags: list[int],
  entities: list[Entity],
  grid_size: int,
  dat_dir: Path,
  top: int = 5,
) -> list[MatchResult]:
  """Search all .dat files for sub-levels matching the given wall pattern.

  wall_flags is a flat list of per-cell bitmasks (from the editor JS).
  """
  N = grid_size
  dat_files = sorted(
    dat_dir.glob("B-*.dat"),
    key=lambda p: int(p.stem.split("-")[1]),
  )

  # Convert editor bitmasks to edge arrays, then compute all transforms
  input_walls = bitmask_to_edges(wall_flags, N)
  input_transforms = all_transforms(input_walls, N)

  wall_total = (N + 1) * N + N * (N + 1)  # total edge count

  # Collect all candidates with scores
  candidates: list[tuple[int, int, int, int, int, str, bool, SubLevel]] = []

  for filepath in dat_files:
    parsed = parse_file(filepath)
    if parsed is None:
      continue
    if parsed.header.grid_size != N:
      continue

    fi = int(filepath.stem.split("-")[1])

    for si, level in enumerate(parsed.sublevels):
      level_flat = _flatten_walls((level.h_walls, level.v_walls))
      ent_score, ent_total = match_entities(level.entities, entities)

      for tlabel, tflat in input_transforms:
        wall_match = sum(1 for a, b in zip(tflat, level_flat) if a == b)
        candidates.append(
          (wall_match, ent_score, ent_total, fi, si, tlabel, parsed.header.flip, level)
        )

  candidates.sort(key=lambda x: (-x[0], -x[1]))

  # Deduplicate by (file, sublevel), take top N
  seen: set[tuple[int, int]] = set()
  results: list[MatchResult] = []
  for wall_match, ent_score, ent_total, fi, si, tlabel, flip, level in candidates:
    if len(results) >= top:
      break
    key = (fi, si)
    if key in seen:
      continue
    seen.add(key)
    results.append(
      MatchResult(
        file_index=fi,
        sublevel_index=si,
        wall_score=wall_match,
        wall_total=wall_total,
        entity_score=ent_score,
        entity_total=ent_total,
        transform=tlabel,
        flip=flip,
        ascii_render=render_maze(level, N),
        exit_side=level.exit_side,
        exit_pos=level.exit_pos,
        entities=level.entities,
      )
    )

  return results
