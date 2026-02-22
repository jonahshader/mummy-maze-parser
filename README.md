# mummy-maze-parser

Parser for Mummy Maze Deluxe `.dat` level files, reverse-engineered from the original PopCap binary (2002).

Extracts wall layouts, entity positions, and metadata from the game's packed binary format.

## Installation

As a dependency in a uv project:

```sh
uv add mummy-maze-parser --git https://github.com/jonahshader/mummy-maze-parser
```

Or as a local path dependency:

```sh
uv add mummy-maze-parser --path ../mummy-maze-parser
```

The parser has no dependencies beyond the standard library, so `mummy_maze/parser.py` can also be used as a standalone file.

## Usage

```python
from mummy_maze import parse_file, EntityType

parsed = parse_file(Path("B-1.dat"))
header = parsed.header
for level in parsed.sublevels:
    mummies = [e for e in level.entities if e.type == EntityType.MUMMY]
    print(f"Grid: {header.grid_size}x{header.grid_size}, Mummies: {len(mummies)}")
```

### Data types

- **`ParsedFile`** — header + list of sub-levels
- **`Header`** — grid size, flip flag, mummy count, key/gate, traps, scorpion
- **`SubLevel`** — wall edge arrays, exit side/position, entity list, flip flag
- **`Entity`** — type (`EntityType` enum), col, row
- **`EntityType`** — `PLAYER`, `MUMMY`, `SCORPION`, `TRAP`, `KEY`, `GATE`

Walls are stored as two edge arrays (no redundancy):

- `h_walls[r][c]` — horizontal wall on top edge of cell `(r, c)`. Shape: `(N+1) × N`.
- `v_walls[r][c]` — vertical wall on left edge of cell `(r, c)`. Shape: `N × (N+1)`.

Movement checks: north = `not h_walls[r][c]`, south = `not h_walls[r+1][c]`, west = `not v_walls[r][c]`, east = `not v_walls[r][c+1]`.

### CLI

A CLI is included for inspecting `.dat` files:

```sh
mummy-maze-parser /path/to/mazes/          # directory of B-*.dat files
mummy-maze-parser /path/to/B-1.dat         # single file
mummy-maze-parser /path/to/mazes/ -s 42    # specific sub-level
mummy-maze-parser /path/to/mazes/ --header-only
```

### Web editor

A browser-based maze editor for drawing levels and matching them against parsed `.dat` files. Requires the `editor` extra:

```sh
uv sync --extra editor
mummy-maze-editor /path/to/mazes/
```

## .dat file format

Each file contains a 6-byte header followed by 100 sub-levels packed sequentially.

| Byte | Field |
|------|-------|
| 0 | bits 0-3: grid size (6, 8, or 10); bit 4: flip flag (red/white mummies) |
| 1 | number of sub-levels (always 100) |
| 2 | mummy count (1 or 2) |
| 3 | key/gate flag (0 or 1) |
| 4 | trap count (0, 1, or 2) |
| 5 | scorpion flag (0 or 1) |

Sub-level data is variable-length: bit-packed wall data, followed by exit, player, mummy, key/gate, scorpion, and trap position bytes. The flip flag determines which coordinate transform is applied to decode the stored layout into screen coordinates.
