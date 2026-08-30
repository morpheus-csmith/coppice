"""Docker backend -- the fallback, and the honest baseline.

This is deliberately NOT a strawman. It emulates ConTree's model as well
as Docker can: `docker commit` turns a finished container into an image,
and running a new container from that image is a fork. A competent
engineer building this project without ConTree would build exactly this.

Where it loses is the part we are trying to measure:
  * every fork pays container create + start (~0.5-1.5s of pure overhead)
  * every commit writes a real layer to disk, so depth costs storage
  * concurrency is bounded by host RAM, not by an API quota

Keep this honest. A benchmark that beats a strawman proves nothing.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid

import docker
from docker.errors import NotFound

from .base import ExecResult

_SHELL = "/bin/sh"


class DockerState:
    """An image id. Forking = running another container from it."""

    __slots__ = ("_ex", "id", "depth", "_ephemeral")

    def __init__(self, ex: "DockerExecutor", image_id: str, depth: int, ephemeral: bool):
        self._ex = ex
        self.id = image_id
        self.depth = depth
        self._ephemeral = ephemeral

    def __repr__(self) -> str:
        return f"<DockerState {self.id[:19]} d={self.depth}>"

    async def run(
        self,
        shell: str,
        *,
        stdin: str | None = None,
        timeout_s: float = 600.0,
    ) -> ExecResult:
        return await asyncio.to_thread(self._run_sync, shell, stdin, timeout_s)

    def _run_sync(self, shell: str, stdin: str | None, timeout_s: float) -> ExecResult:
        # Pipe stdin without docker attach: embed it, base64'd so no quoting
        # rules can corrupt a patch. Patches contain everything.
        if stdin is not None:
            blob = base64.b64encode(stdin.encode()).decode()
            shell = f"printf %s {blob} | base64 -d | ({shell})"

        client = self._ex.client
        t0 = time.perf_counter()
        timed_out = False

        container = client.containers.create(
            self.id,
            command=[_SHELL, "-c", shell],
            working_dir=self._ex.workdir,
            mem_limit=self._ex.mem_limit,
            network_mode=self._ex.network,
            labels={"coppice": self._ex.run_id},
        )
        try:
            container.start()
            try:
                container.wait(timeout=timeout_s)
                exit_code = container.attrs["State"]["ExitCode"]
                container.reload()
                exit_code = container.attrs["State"]["ExitCode"]
            except Exception:
                timed_out = True
                exit_code = 124
                try:
                    container.kill()
                except Exception:
                    pass

            out = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
            err = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")

            image = container.commit(
                repository="coppice-state", tag=uuid.uuid4().hex[:12],
                conf={"Labels": {"coppice": "1"}},
            )
            self._ex._track(image.id)
        finally:
            try:
                container.remove(force=True)
            except NotFound:
                pass

        return ExecResult(
            state=DockerState(self._ex, image.id, self.depth + 1, True),
            stdout=out,
            stderr=err,
            exit_code=exit_code,
            duration_s=time.perf_counter() - t0,
            timed_out=timed_out,
        )


class DockerExecutor:
    name = "docker"

    def __init__(
        self,
        *,
        workdir: str = "/w",
        mem_limit: str = "900m",
        network: str = "bridge",
    ):
        # Default client timeout is 60s; under width>=16 the daemon can
        # take longer to answer create/commit and we lose an instance to
        # a ReadTimeout that has nothing to do with the model.
        self.client = docker.from_env(timeout=300)
        self.workdir = workdir
        self.mem_limit = mem_limit
        self.network = network
        self.run_id = uuid.uuid4().hex[:8]
        self._images: list[str] = []

    def _track(self, image_id: str) -> None:
        self._images.append(image_id)

    async def base(self, image: str) -> DockerState:
        await asyncio.to_thread(self.client.images.pull, image)
        obj = await asyncio.to_thread(self.client.images.get, image)
        # mkdir the workdir so `create` never fails on a missing path
        root = DockerState(self, obj.id, 0, False)
        prepared = await root.run(f"mkdir -p {self.workdir}")
        return prepared.state

    @staticmethod
    def sweep() -> int:
        """Remove every coppice-committed image, including from dead runs.

        aclose() only runs on a clean exit. A crash or Ctrl-C leaks one
        tagged image per branch, and `docker image prune` ignores them
        because they are tagged, not dangling. Hundreds of leaked images
        degrade the daemon and were the likely cause of a
        `double free or corruption` abort under width-16 concurrency.
        """
        client = docker.from_env(timeout=300)
        removed = 0
        for img in client.images.list(name="coppice-state"):
            try:
                client.images.remove(img.id, force=True)
                removed += 1
            except Exception:
                pass
        return removed

    async def aclose(self) -> None:
        """Remove every image this run committed. Skipping this fills the disk."""
        for image_id in reversed(self._images):
            try:
                await asyncio.to_thread(
                    self.client.images.remove, image_id, force=True
                )
            except Exception:
                pass
        self._images.clear()
