# Committed results

`runs/` is scratch and gitignored — it fills with hundreds of files and gets
overwritten constantly. These are the specific artefacts the README and the
findings refer to, kept so every claim in this repository can be checked
against the data that produced it.

| file | what it is |
|---|---|
| `demo-pylint7993.jsonl` | One run against SWE-bench Lite `pylint-dev__pylint-7993`: 16 proposals, 13 applied, 2 turned the suite green, $0.0397. Feed it to `viz/build_replay.py`. |
| `width-curve-nebius.json` | The headline benchmark. 10 instances, 16 samples each, Nemotron 3 Super on Nebius Token Factory. Feed it to `bench/analyze.py`. |
| `width-curve-nvidia-build.json` | The same benchmark run earlier against NVIDIA Build's free tier, kept for comparison. |

```bash
python bench/analyze.py results/width-curve-nebius.json
python viz/build_replay.py results/demo-pylint7993.jsonl -o viz/replay.html
```
