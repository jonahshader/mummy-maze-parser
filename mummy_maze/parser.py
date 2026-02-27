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
    7. Gate + Key positions (2 bytes, only if key_gate > 0)
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


def _read_wall_bits(data: bytes, pos: int, n: int) -> tuple[int, int]:
  """Read one or two bytes of wall bits depending on grid size."""
  bits = data[pos]
  pos += 1
  if n > 8:
    bits |= data[pos] << 8
    pos += 1
  return bits, pos


def parse_sublevel(data: bytes, offset: int, header: Header) -> SubLevel:
  """Parse one sub-level from the data stream at the given offset.

  Direct port of the C parser (csolver/src/parse.c), which is itself a
  direct port of the binary's FUN_0040e1d0.  Loads walls into per-cell
  bitmasks first, then converts to edge arrays.
  """
  N = header.grid_size
  flip = header.flip
  pos = offset
  _S = 10  # stride, matching binary's walls[col + row * 10]

  # --- Per-cell bitmask array (C layout: walls[col + row * 10]) ---
  walls = [0] * (_S * _S)

  # Border walls
  for col in range(N):
    for row in range(N):
      idx = col + row * _S
      if row == 0:
        walls[idx] |= 8  # WALL_N
      if row == N - 1:
        walls[idx] |= 4  # WALL_S
      if col == 0:
        walls[idx] |= 1  # WALL_W
      if col == N - 1:
        walls[idx] |= 2  # WALL_E

  # --- Load wall bytes (flip-dependent) ---
  if not flip:
    # flip=0: first loop = N/S walls, second loop = W/E walls
    for col in range(N):
      bits, pos = _read_wall_bits(data, pos, N)
      for row in range(N):
        if bits & (1 << row):
          walls[col + row * _S] |= 8  # WALL_N
          if row > 0:
            walls[col + (row - 1) * _S] |= 4  # WALL_S

    for col in range(N):
      bits, pos = _read_wall_bits(data, pos, N)
      for row in range(N):
        if bits & (1 << row):
          walls[col + row * _S] |= 1  # WALL_W
          if col > 0:
            walls[col - 1 + row * _S] |= 2  # WALL_E
  else:
    # flip=1: first loop = W/E walls, second loop = S/N walls
    for i10 in range(N):
      bits, pos = _read_wall_bits(data, pos, N)
      for i8 in range(N):
        if bits & (1 << i8):
          idx = i8 + (N - i10) * _S
          walls[idx - _S] |= 1  # WALL_W
          if i8 > 0:
            walls[idx - _S - 1] |= 2  # WALL_E

    for i10 in range(N):
      bits, pos = _read_wall_bits(data, pos, N)
      for i8 in range(N):
        if bits & (1 << i8):
          idx = i8 + (N - i10) * _S
          walls[idx - _S] |= 4  # WALL_S
          if i10 > 0:
            walls[idx] |= 8  # WALL_N

  # --- Exit (flip-dependent) ---
  exit_b = data[pos]
  pos += 1
  side = exit_b & 0x0F
  p = (exit_b >> 4) & 0x0F

  if not flip:
    if side == 0:  # West
      walls[0 + p * _S] |= 0x10
      walls[0 + p * _S] ^= 1
      exit_row, exit_col, exit_mask = p, 0, 0x10
    elif side == 1:  # North
      walls[p] |= 0x80
      walls[p] ^= 8
      exit_row, exit_col, exit_mask = 0, p, 0x80
    elif side == 2:  # South
      walls[p + (N - 1) * _S] |= 0x40
      walls[p + (N - 1) * _S] ^= 4
      exit_row, exit_col, exit_mask = N - 1, p, 0x40
    elif side == 3:  # East
      walls[(N - 1) + p * _S] |= 0x20
      walls[(N - 1) + p * _S] ^= 2
      exit_row, exit_col, exit_mask = p, N - 1, 0x20
    else:
      exit_row, exit_col, exit_mask = -1, -1, 0
  else:
    if side == 0:  # South
      walls[p + (N - 1) * _S] |= 0x40
      walls[p + (N - 1) * _S] ^= 4
      exit_row, exit_col, exit_mask = N - 1, p, 0x40
    elif side == 1:  # West
      walls[0 + (N - p - 1) * _S] |= 0x10
      walls[0 + (N - p - 1) * _S] ^= 1
      exit_row, exit_col, exit_mask = N - p - 1, 0, 0x10
    elif side == 2:  # East
      walls[(N - 1) + (N - 1 - p) * _S] |= 0x20
      walls[(N - 1) + (N - 1 - p) * _S] ^= 2
      exit_row, exit_col, exit_mask = N - 1 - p, N - 1, 0x20
    elif side == 3:  # North
      walls[p] |= 0x80
      walls[p] ^= 8
      exit_row, exit_col, exit_mask = 0, p, 0x80
    else:
      exit_row, exit_col, exit_mask = -1, -1, 0

  # --- Convert bitmask to edge arrays ---
  h_walls: Grid = [[False] * N for _ in range(N + 1)]
  v_walls: Grid = [[False] * (N + 1) for _ in range(N)]

  for row in range(N):
    for col in range(N):
      w = walls[col + row * _S]
      if w & 8:  # WALL_N → top edge of (row, col)
        h_walls[row][col] = True
      if w & 4:  # WALL_S → bottom edge of (row, col)
        h_walls[row + 1][col] = True
      if w & 1:  # WALL_W → left edge of (row, col)
        v_walls[row][col] = True
      if w & 2:  # WALL_E → right edge of (row, col)
        v_walls[row][col + 1] = True

  # --- Convert exit to side string + position ---
  _mask_to_side = {0x80: "N", 0x40: "S", 0x10: "W", 0x20: "E"}
  exit_side = _mask_to_side.get(exit_mask, "?")
  exit_pos = exit_col if exit_side in ("N", "S") else exit_row

  # --- Entity positions (C byte order and coordinate transforms) ---
  def read_entity() -> tuple[int, int]:
    """Return (row, col) in the binary's coordinate system."""
    nonlocal pos
    b = data[pos]
    pos += 1
    col_raw = b & 0x0F
    row_raw = (b >> 4) & 0x0F
    if flip:
      return (N - row_raw - 1, col_raw)
    return (col_raw, row_raw)

  entities: list[Entity] = []

  erow, ecol = read_entity()
  entities.append(Entity(EntityType.PLAYER, ecol, erow))

  for _ in range(header.mummy_count):
    erow, ecol = read_entity()
    entities.append(Entity(EntityType.MUMMY, ecol, erow))

  # Binary byte order: scorpion, traps, gate+key (NOT gate+key first)
  for _ in range(header.scorpion):
    erow, ecol = read_entity()
    entities.append(Entity(EntityType.SCORPION, ecol, erow))

  for _ in range(header.trap_count):
    erow, ecol = read_entity()
    entities.append(Entity(EntityType.TRAP, ecol, erow))

  if header.key_gate > 0:
    erow, ecol = read_entity()
    entities.append(Entity(EntityType.GATE, ecol, erow))
    erow, ecol = read_entity()
    entities.append(Entity(EntityType.KEY, ecol, erow))

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
    if ent.type == EntityType.GATE:
      # Gate is a wall on the east edge of its cell
      if 0 <= ent.row < N and 0 <= ent.col < N:
        grid[ent.row * 2 + 1][(ent.col + 1) * 2] = ch
    elif 0 <= ent.row < N and 0 <= ent.col < N:
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
