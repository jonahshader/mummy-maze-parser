"""Maze matching: find .dat sub-levels that match editor-drawn wall patterns."""

from dataclasses import dataclass
from pathlib import Path

from .parser import (
  WALL_EAST,
  WALL_NORTH,
  WALL_SOUTH,
  WALL_WEST,
  Entity,
  EntityType,
  SubLevel,
  parse_file,
  render_maze,
)

Grid = list[list[int]]


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


def rotate90(grid: Grid, n: int) -> Grid:
  """Rotate wall flags 90 degrees clockwise."""
  out: Grid = [[0] * n for _ in range(n)]
  for r in range(n):
    for c in range(n):
      v = grid[r][c]
      nv = 0
      if v & WALL_NORTH:
        nv |= WALL_WEST
      if v & WALL_EAST:
        nv |= WALL_NORTH
      if v & WALL_SOUTH:
        nv |= WALL_EAST
      if v & WALL_WEST:
        nv |= WALL_SOUTH
      out[c][n - 1 - r] = nv
  return out


def flip_h(grid: Grid, n: int) -> Grid:
  """Flip wall flags horizontally (mirror left-right)."""
  out: Grid = [[0] * n for _ in range(n)]
  for r in range(n):
    for c in range(n):
      v = grid[r][c]
      nv = 0
      if v & WALL_NORTH:
        nv |= WALL_NORTH
      if v & WALL_SOUTH:
        nv |= WALL_SOUTH
      if v & WALL_EAST:
        nv |= WALL_WEST
      if v & WALL_WEST:
        nv |= WALL_EAST
      out[r][n - 1 - c] = nv
  return out


def all_transforms(flat: list[int], n: int) -> list[tuple[str, list[int]]]:
  """Return all 8 dihedral symmetry transforms as (label, flat_list)."""
  grid: Grid = [flat[i * n : (i + 1) * n] for i in range(n)]
  results: list[tuple[str, list[int]]] = []
  for flip_label, fg in [("id", grid), ("fh", flip_h(grid, n))]:
    cur = [row[:] for row in fg]
    for rot in range(4):
      label = f"{flip_label}_r{rot * 90}"
      results.append(
        (
          label,
          [cur[r][c] for r in range(n) for c in range(n)],
        )
      )
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
  """Search all .dat files for sub-levels matching the given wall pattern."""
  N = grid_size
  dat_files = sorted(
    dat_dir.glob("B-*.dat"),
    key=lambda p: int(p.stem.split("-")[1]),
  )

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
      cells_flat = [level.cells[r][c] for r in range(N) for c in range(N)]
      ent_score, ent_total = match_entities(level.entities, entities)

      for tlabel, tflat in all_transforms(wall_flags, N):
        wall_match = sum(1 for a, b in zip(tflat, cells_flat) if a == b)
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
        wall_total=N * N,
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
