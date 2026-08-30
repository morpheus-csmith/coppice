"""Reclaim Docker state leaked by crashed or interrupted runs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coppice.executor.docker_exec import DockerExecutor  # noqa: E402

if __name__ == "__main__":
    print(f"removed {DockerExecutor.sweep()} coppice-state images")
