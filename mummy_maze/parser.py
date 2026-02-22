"""
Mummy Maze Deluxe .dat file parser.

Reverse-engineered from the WinMM.exe binary (PopCap, 2002).

Each .dat file contains a 6-byte header followed by exactly 100 sub-levels
packed sequentially.

Header (6 bytes):
  byte[0]: bits 0-3 = grid_size (6, 8, or 10)
           bit 4 = flip flag (red mummies if set, white if clear)
  byte[1]: num_sublevels (always 0x64 = 100)
  byte[2]: mummy_count (1 or 2)
  byte[3]: key_gate flag (0 or 1)
  byte[4]: trap_count (0, 1, or 2)
  byte[5]: scorpion flag (0 or 1)

Sub-level data (variable-size, sequential):
  bytes_per_sub = wall_bytes + 3 + (mummy_count-1) + 2*key_gate + trap_count + scorpion
  where wall_bytes = grid_size * (2 if grid_size > 8 else 1) * 2

  Per sub-level:
    1. Horizontal wall data (bit-packed, needs coordinate transform)
    2. Vertical wall data (same structure)
    3. Exit opening (1 byte): low nibble = side, high nibble = position
    4. Player position (1 byte): low nibble = col, high nibble = row
    5. Mummy 1 position (1 byte)
    6. Mummy 2 position (1 byte, only if mummy_count > 1)
    7. Key + Gate positions (2 bytes, only if key_gate > 0)
    8. Scorpion position(s) (scorpion bytes)
    9. Trap position(s) (trap_count bytes)

Flip flag determines mummy behavior and coordinate transform:
  flip=False (white mummies, horizontal-first): NW-SE transpose on walls
  flip=True  (red mummies, vertical-first): horizontal mirror on walls,
             entity coords transformed as (col, row) -> (N-1-row, col)

Walls are stored as two edge arrays:
  h_walls[r][c] — horizontal wall on top edge of cell (r, c).
                   Shape: (N+1) x N. Row 0 = north border, row N = south border.
  v_walls[r][c] — vertical wall on left edge of cell (r, c).
                   Shape: N x (N+1). Col 0 = west border, col N = east border.

Movement checks:
  North from (r, c): not h_walls[r][c]
  South from (r, c): not h_walls[r+1][c]
  West from (r, c):  not v_walls[r][c]
  East from (r, c):  not v_walls[r][c+1]
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

Grid = list[list[bool]]


class EntityType(Enum):
  PLAYER = "player"
  MUMMY = "mummy"
  SCORPION = "scorpion"
  TRAP = "trap"
  KEY = "key"
  GATE = "gate"


@dataclass
class Entity:
  type: EntityType
  col: int
  row: int


@dataclass
class Header:
  grid_size: int
  flip: bool
  num_sublevels: int
  mummy_count: int
  key_gate: int
  trap_count: int
  scorpion: int
  wall_bytes: int
  bytes_per_sub: int


@dataclass
class SubLevel:
  h_walls: Grid
  v_walls: Grid
  exit_side: str
  exit_pos: int
  entities: list[Entity]
  flip: bool


@dataclass
class ParsedFile:
  header: Header
  sublevels: list[SubLevel] = field(default_factory=list)


def parse_header(data: bytes) -> Header:
  """Parse the 6-byte file header."""
  grid_size = data[0] & 0x0F
  flip = bool(data[0] & 0x10)
  num_sublevels = data[1]  # always 100
  mummy_count = data[2]
  key_gate = data[3]
  trap_count = data[4]
  scorpion = data[5]

  wall_bytes = grid_size * (2 if grid_size > 8 else 1) * 2
  bytes_per_sub = (
    wall_bytes + 3 + (mummy_count - 1) + 2 * key_gate + trap_count + scorpion
  )

  return Header(
    grid_size=grid_size,
    flip=flip,
    num_sublevels=num_sublevels,
    mummy_count=mummy_count,
    key_gate=key_gate,
    trap_count=trap_count,
    scorpion=scorpion,
    wall_bytes=wall_bytes,
    bytes_per_sub=bytes_per_sub,
  )


def _decode_pos(b: int) -> tuple[int, int]:
  """Decode a position byte: lower nibble = col, upper nibble = row."""
  return b & 0x0F, (b >> 4) & 0x0F


def parse_sublevel(data: bytes, offset: int, header: Header) -> SubLevel:
  """Parse one sub-level from the data stream at the given offset."""
  N = header.grid_size
  pos = offset

  # Edge arrays (pre-transform)
  # h_walls: (N+1) rows x N cols — horizontal edges
  h_walls: Grid = [[False] * N for _ in range(N + 1)]
  # v_walls: N rows x (N+1) cols — vertical edges
  v_walls: Grid = [[False] * (N + 1) for _ in range(N)]

  # Set border walls
  for i in range(N):
    h_walls[0][i] = True  # north border
    h_walls[N][i] = True  # south border
    v_walls[i][0] = True  # west border
    v_walls[i][N] = True  # east border

  # --- Horizontal walls (as stored in file) ---
  # Each bit indicates a horizontal wall on the top edge of a cell.
  for col in range(N):
    wall_bits = data[pos]
    pos += 1
    if N > 8:
      wall_bits |= data[pos] << 8
      pos += 1
    for row in range(N):
      if wall_bits & (1 << row):
        h_walls[row][col] = True

  # --- Vertical walls (as stored in file) ---
  # Each bit indicates a vertical wall on the left edge of a cell.
  for slot in range(N):
    wall_bits = data[pos]
    pos += 1
    if N > 8:
      wall_bits |= data[pos] << 8
      pos += 1
    for row in range(N):
      if wall_bits & (1 << row):
        v_walls[row][slot] = True

  # --- Transform walls based on flip flag ---
  flip = header.flip
  if not flip:
    # flip=False (white mummies): NW-SE transpose
    # Transpose swaps h_walls <-> v_walls and transposes each array.
    new_h: Grid = [[False] * N for _ in range(N + 1)]
    new_v: Grid = [[False] * (N + 1) for _ in range(N)]
    for r in range(N + 1):
      for c in range(N):
        new_v[c][r] = h_walls[r][c]
    for r in range(N):
      for c in range(N + 1):
        new_h[c][r] = v_walls[r][c]
    h_walls = new_h
    v_walls = new_v
  else:
    # flip=True (red mummies): horizontal flip (mirror left-right)
    # Reverse columns of h_walls, reverse columns of v_walls.
    new_h = [[False] * N for _ in range(N + 1)]
    new_v = [[False] * (N + 1) for _ in range(N)]
    for r in range(N + 1):
      for c in range(N):
        new_h[r][c] = h_walls[r][N - 1 - c]
    for r in range(N):
      for c in range(N + 1):
        new_v[r][c] = v_walls[r][N - c]
    h_walls = new_h
    v_walls = new_v

  # --- Exit opening ---
  exit_b = data[pos]
  pos += 1
  exit_side_num = exit_b & 0x0F
  exit_pos = (exit_b >> 4) & 0x0F
  if not flip:
    side_map = {0: "N", 1: "W", 2: "E", 3: "S"}
  else:
    side_map = {0: "W", 1: "N", 2: "S", 3: "E"}
  exit_side = side_map.get(exit_side_num, "?")
  if flip:
    if exit_side in ("N", "S"):
      exit_pos = N - 1 - exit_pos

  # Toggle border wall to create exit passage
  if exit_side == "N":
    h_walls[0][exit_pos] = not h_walls[0][exit_pos]
  elif exit_side == "S":
    h_walls[N][exit_pos] = not h_walls[N][exit_pos]
  elif exit_side == "W":
    v_walls[exit_pos][0] = not v_walls[exit_pos][0]
  elif exit_side == "E":
    v_walls[exit_pos][N] = not v_walls[exit_pos][N]

  # --- Entities ---
  def read_pos() -> tuple[int, int]:
    nonlocal pos
    col, row = _decode_pos(data[pos])
    pos += 1
    if flip:
      return (N - 1 - row, col)
    return (col, row)

  entities: list[Entity] = []

  col, row = read_pos()
  entities.append(Entity(EntityType.PLAYER, col, row))

  for _ in range(header.mummy_count):
    col, row = read_pos()
    entities.append(Entity(EntityType.MUMMY, col, row))

  if header.key_gate > 0:
    col, row = read_pos()
    entities.append(Entity(EntityType.KEY, col, row))
    col, row = read_pos()
    entities.append(Entity(EntityType.GATE, col, row))

  # File stores scorpion bytes before trap bytes
  for _ in range(header.scorpion):
    col, row = read_pos()
    entities.append(Entity(EntityType.SCORPION, col, row))

  for _ in range(header.trap_count):
    col, row = read_pos()
    entities.append(Entity(EntityType.TRAP, col, row))

  return SubLevel(
    h_walls=h_walls,
    v_walls=v_walls,
    exit_side=exit_side,
    exit_pos=exit_pos,
    entities=entities,
    flip=flip,
  )


_ENTITY_MARKERS = {
  EntityType.PLAYER: "P",
  EntityType.MUMMY: "M",
  EntityType.SCORPION: "S",
  EntityType.TRAP: "T",
  EntityType.KEY: "K",
  EntityType.GATE: "G",
}


def render_maze(level: SubLevel, grid_size: int) -> str:
  """Render maze as ASCII art with entities."""
  N = grid_size
  H = 2 * N + 1
  W = 2 * N + 1
  grid = [[" "] * W for _ in range(H)]

  # Corner intersections
  for r in range(N + 1):
    for c in range(N + 1):
      grid[r * 2][c * 2] = "+"

  # Horizontal walls (top edge of each cell + bottom border)
  for r in range(N + 1):
    for c in range(N):
      if level.h_walls[r][c]:
        grid[r * 2][c * 2 + 1] = "-"

  # Vertical walls (left edge of each cell + right border)
  for r in range(N):
    for c in range(N + 1):
      if level.v_walls[r][c]:
        grid[r * 2 + 1][c * 2] = "|"

  # Entities
  for ent in level.entities:
    ch = _ENTITY_MARKERS.get(ent.type, "?")
    if 0 <= ent.row < N and 0 <= ent.col < N:
      grid[ent.row * 2 + 1][ent.col * 2 + 1] = ch

  return "\n".join("".join(row) for row in grid)


def parse_file(filepath: Path) -> ParsedFile | None:
  """Parse an entire .dat file, returning a ParsedFile or None."""
  data = filepath.read_bytes()
  if len(data) < 6:
    return None
  header = parse_header(data)
  sublevels: list[SubLevel] = []
  offset = 6
  for _ in range(header.num_sublevels):
    if offset + header.bytes_per_sub > len(data):
      break
    level = parse_sublevel(data, offset, header)
    sublevels.append(level)
    offset += header.bytes_per_sub
  return ParsedFile(header=header, sublevels=sublevels)
