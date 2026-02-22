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
"""

from dataclasses import dataclass, field
from pathlib import Path

# Wall flag bits (matching game's internal representation)
WALL_WEST = 0x01
WALL_EAST = 0x02
WALL_SOUTH = 0x04
WALL_NORTH = 0x08


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
  cells: list[list[int]]
  exit_side: str
  exit_pos: int
  entities: dict[str, tuple[int, int]]
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
  gs = header.grid_size
  N = gs
  pos = offset

  # Cell wall flags: cells[row][col]
  cells = [[0] * N for _ in range(N)]

  # Set border walls
  for i in range(N):
    cells[0][i] |= WALL_NORTH
    cells[N - 1][i] |= WALL_SOUTH
    cells[i][0] |= WALL_WEST
    cells[i][N - 1] |= WALL_EAST

  # --- Horizontal walls (as stored in file) ---
  for col in range(N):
    wall_bits = data[pos]
    pos += 1
    if N > 8:
      wall_bits |= data[pos] << 8
      pos += 1
    for row in range(N):
      if wall_bits & (1 << row):
        cells[row][col] |= WALL_NORTH
        if row > 0:
          cells[row - 1][col] |= WALL_SOUTH

  # --- Vertical walls (as stored in file) ---
  for slot in range(N):
    wall_bits = data[pos]
    pos += 1
    if N > 8:
      wall_bits |= data[pos] << 8
      pos += 1
    for row in range(N):
      if wall_bits & (1 << row):
        cells[row][slot] |= WALL_WEST
        if slot > 0:
          cells[row][slot - 1] |= WALL_EAST

  # --- Transform walls based on flip flag ---
  flip = header.flip
  if not flip:
    # flip=False (white mummies): NW-SE transpose
    transposed = [[0] * N for _ in range(N)]
    for r in range(N):
      for c in range(N):
        v = cells[r][c]
        tv = 0
        if v & WALL_NORTH:
          tv |= WALL_WEST
        if v & WALL_SOUTH:
          tv |= WALL_EAST
        if v & WALL_WEST:
          tv |= WALL_NORTH
        if v & WALL_EAST:
          tv |= WALL_SOUTH
        transposed[c][r] = tv
    cells = transposed
  else:
    # flip=True (red mummies): horizontal flip (mirror left-right)
    flipped = [[0] * N for _ in range(N)]
    for r in range(N):
      for c in range(N):
        v = cells[r][c]
        fv = 0
        if v & WALL_NORTH:
          fv |= WALL_NORTH
        if v & WALL_SOUTH:
          fv |= WALL_SOUTH
        if v & WALL_EAST:
          fv |= WALL_WEST
        if v & WALL_WEST:
          fv |= WALL_EAST
        flipped[r][N - 1 - c] = fv
    cells = flipped

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
  if exit_side == "W":
    cells[exit_pos][0] ^= WALL_WEST
  elif exit_side == "N":
    cells[0][exit_pos] ^= WALL_NORTH
  elif exit_side == "S":
    cells[N - 1][exit_pos] ^= WALL_SOUTH
  elif exit_side == "E":
    cells[exit_pos][N - 1] ^= WALL_EAST

  # --- Entities ---
  def read_entity() -> tuple[int, int]:
    nonlocal pos
    col, row = _decode_pos(data[pos])
    pos += 1
    if flip:
      return (N - 1 - row, col)
    return (col, row)

  entities: dict[str, tuple[int, int]] = {
    "player": read_entity(),
    "mummy1": read_entity(),
  }

  if header.mummy_count > 1:
    entities["mummy2"] = read_entity()

  if header.key_gate > 0:
    entities["key"] = read_entity()
    entities["gate"] = read_entity()

  # File stores scorpion bytes before trap bytes
  for t in range(header.scorpion):
    key = f"scorpion{t + 1}" if header.scorpion > 1 else "scorpion"
    entities[key] = read_entity()

  for t in range(header.trap_count):
    key = f"trap{t + 1}" if header.trap_count > 1 else "trap"
    entities[key] = read_entity()

  return SubLevel(
    cells=cells,
    exit_side=exit_side,
    exit_pos=exit_pos,
    entities=entities,
    flip=flip,
  )


def render_maze(level: SubLevel, grid_size: int) -> str:
  """Render maze as ASCII art with entities."""
  cells = level.cells
  entities = level.entities
  N = grid_size
  H = 2 * N + 1
  W = 2 * N + 1
  grid = [[" "] * W for _ in range(H)]

  for r in range(N + 1):
    for c in range(N + 1):
      grid[r * 2][c * 2] = "+"

  for r in range(N):
    for c in range(N):
      if cells[r][c] & WALL_NORTH:
        grid[r * 2][c * 2 + 1] = "-"
      if cells[r][c] & WALL_SOUTH:
        grid[(r + 1) * 2][c * 2 + 1] = "-"
      if cells[r][c] & WALL_WEST:
        grid[r * 2 + 1][c * 2] = "|"
      if cells[r][c] & WALL_EAST:
        grid[r * 2 + 1][(c + 1) * 2] = "|"

  side = level.exit_side
  epos = level.exit_pos
  if side == "N":
    grid[0][epos * 2 + 1] = " "
  elif side == "S":
    grid[N * 2][epos * 2 + 1] = " "
  elif side == "W":
    grid[epos * 2 + 1][0] = " "
  elif side == "E":
    grid[epos * 2 + 1][N * 2] = " "

  markers = {
    "player": "P",
    "mummy1": "M",
    "mummy2": "M",
    "scorpion": "S",
    "scorpion1": "S",
    "scorpion2": "S",
    "trap": "T",
    "trap1": "T",
    "trap2": "T",
    "key": "K",
    "gate": "G",
  }
  for name, (col, row) in entities.items():
    ch = markers.get(name, "?")
    if 0 <= row < N and 0 <= col < N:
      grid[row * 2 + 1][col * 2 + 1] = ch

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
