"""Render a run's event log as a self-contained replay page.

The event log was designed on day one to be the thing both the benchmark
and the UI read (see events.py). This is the UI half: it turns
runs/<run>.jsonl into one HTML file with the data embedded, so it opens
anywhere with no server, no build step, and no network.

    python viz/build_replay.py runs/search-latest.jsonl -o viz/replay.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def build_model(events: list[dict]) -> dict:
    """Flatten the log into what the page needs: meta, nodes, edges, frames."""
    meta, nodes, edges, frames = {}, [], [], []
    gen_of: dict[str, int] = {}
    root_id = "root"

    for e in events:
        kind, t = e["kind"], e.get("t", 0.0)

        if kind == "run.start":
            meta.update({k: e.get(k) for k in
                         ("task", "width", "beam", "depth", "backend", "provider")})
        elif kind == "setup.done":
            frames.append({"t": t, "type": "note",
                           "text": f"environment prepared in {e.get('seconds')}s"})
        elif kind == "baseline":
            nodes.append({"id": root_id, "gen": 0, "state": "root",
                          "label": e.get("outcome", ""), "score": None})
            gen_of[root_id] = 0
            frames.append({"t": t, "type": "node", "id": root_id})
            frames.append({"t": t, "type": "note",
                           "text": f"baseline {e.get('outcome')} — this is what must go green"})
        elif kind == "propose":
            frames.append({"t": t, "type": "propose", "gen": e.get("gen"),
                           "asked": e.get("asked", 0), "applied": e.get("applied", 0),
                           "rejected": e.get("rejected", 0),
                           "repaired": e.get("repaired", 0)})
        elif kind == "proposal.rejected":
            frames.append({"t": t, "type": "rejected", "reason": e.get("reason", "")})
        elif kind == "branch":
            nid = e.get("id") or f"err{len(nodes)}"
            parent = e.get("parent", root_id)
            gen = e.get("gen", 1)
            state = "pass" if e.get("verdict") == "PASS" else "fail"
            nodes.append({"id": nid, "gen": gen, "state": state,
                          "label": e.get("tests", ""), "score": e.get("score"),
                          "seconds": e.get("seconds"), "diff": e.get("diff")})
            edges.append({"from": parent, "to": nid})
            gen_of[nid] = gen
            frames.append({"t": t, "type": "node", "id": nid})
        elif kind == "gen.prune":
            frames.append({"t": t, "type": "prune", "gen": e.get("gen"),
                           "kept": e.get("kept"), "discarded": e.get("discarded")})
        elif kind == "solved":
            frames.append({"t": t, "type": "solved", "id": e.get("id"),
                           "of": e.get("of_candidates"),
                           "count": e.get("solved_branches"),
                           "cost": e.get("cost")})
        elif kind == "run.end":
            frames.append({"t": t, "type": "end", "cost": e.get("cost"),
                           "branches": e.get("branches_run")})

    frames.sort(key=lambda f: f["t"])
    return {"meta": meta, "nodes": nodes, "edges": edges, "frames": frames}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("viz/replay.html"))
    args = ap.parse_args()

    model = build_model(load(args.log))
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(model, separators=(",", ":"))
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    n = len(model["nodes"])
    solved = sum(1 for x in model["nodes"] if x["state"] == "pass")
    print(f"{args.out}  —  {n} nodes, {solved} solved, {len(model['frames'])} frames")


if __name__ == "__main__":
    main()
