"""Web-based maze editor with integrated .dat file matching."""

import argparse
import webbrowser
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .match import find_matches
from .parser import Entity, EntityType

app = FastAPI()

# Set by main() before server starts
_dat_dir: Path = Path()

# Map JS entity keys to EntityType
_KEY_TO_TYPE = {
  "player": EntityType.PLAYER,
  "mummy1": EntityType.MUMMY,
  "mummy2": EntityType.MUMMY,
  "scorpion": EntityType.SCORPION,
  "trap": EntityType.TRAP,
  "key": EntityType.KEY,
  "gate": EntityType.GATE,
}


class MatchRequest(BaseModel):
  wall_flags: list[int]
  entities: dict[str, list[int]]
  red: bool
  grid_size: int


def _serialize_result(r: object) -> dict[str, object]:
  """Serialize a MatchResult to a JSON-compatible dict."""
  from .match import MatchResult

  assert isinstance(r, MatchResult)
  return {
    "file_index": r.file_index,
    "sublevel_index": r.sublevel_index,
    "wall_score": r.wall_score,
    "wall_total": r.wall_total,
    "entity_score": r.entity_score,
    "entity_total": r.entity_total,
    "transform": r.transform,
    "flip": r.flip,
    "ascii_render": r.ascii_render,
    "exit_side": r.exit_side,
    "exit_pos": r.exit_pos,
    "entities": [
      {"type": e.type.value, "col": e.col, "row": e.row} for e in r.entities
    ],
  }


@app.get("/")
def index() -> FileResponse:
  static_dir = Path(__file__).parent / "static"
  return FileResponse(static_dir / "index.html")


@app.post("/match")
def match(req: MatchRequest) -> list[dict[str, object]]:
  entities = [
    Entity(_KEY_TO_TYPE[k], v[0], v[1])
    for k, v in req.entities.items()
    if k in _KEY_TO_TYPE
  ]
  results = find_matches(
    wall_flags=req.wall_flags,
    entities=entities,
    grid_size=req.grid_size,
    dat_dir=_dat_dir,
  )
  return [_serialize_result(r) for r in results]


def main() -> None:
  global _dat_dir  # noqa: PLW0603

  parser = argparse.ArgumentParser(
    description="Launch the Mummy Maze web editor with .dat file matching."
  )
  parser.add_argument(
    "dat_dir",
    type=Path,
    help="directory containing B-*.dat files",
  )
  parser.add_argument(
    "--port",
    type=int,
    default=8000,
    help="port to serve on (default: 8000)",
  )
  parser.add_argument(
    "--no-browser",
    action="store_true",
    help="don't open browser automatically",
  )
  args = parser.parse_args()

  _dat_dir = args.dat_dir.resolve()
  if not _dat_dir.is_dir():
    parser.error(f"Not a directory: {_dat_dir}")

  import uvicorn

  if not args.no_browser:
    import threading

    threading.Timer(
      1.0,
      webbrowser.open,
      args=[f"http://localhost:{args.port}"],
    ).start()

  uvicorn.run(app, host="127.0.0.1", port=args.port)
