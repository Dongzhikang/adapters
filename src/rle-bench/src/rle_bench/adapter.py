"""Export native RLE-Bench CPU tasks with self-contained Docker build contexts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib

UPSTREAM_URL = "https://github.com/RLE-Bench/RLE-Bench.git"
UPSTREAM_COMMIT = "c6bf572283b5453c0ee76eaa3054f23d691e433d"
DATASET_NAME = "rlebench/rle-bench-cpu"
PROVENANCE = "rle-bench-provenance.json"
ROOT_MARKER = "rle-bench-source.json"
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    upstream_path: str

    @property
    def family(self) -> str:
        return self.upstream_path.split("/")[0]


TASKS = (
    TaskSpec("task06-rgb-only", "task06/rgb-only"),
    TaskSpec("task06-rgb-depth", "task06/rgb-depth"),
    TaskSpec("task07", "task07"),
    TaskSpec("task08", "task08"),
    TaskSpec("task09", "task09"),
)
_SHARED_FILES = ("__init__.py", "core/__init__.py", "core/model.py",
                 "core/scoring.py", "core/media.py")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def portable_config(text: str) -> str:
    """Build bundled Dockerfiles instead of requiring upstream's local :dev images."""
    section = ""
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"\s*\[([^\]]+)\]", line)
        if match:
            section = match[1]
        if section in {"environment", "verifier.environment"} and re.match(
                r"\s*docker_image\s*=", line):
            continue
        if line.startswith("# Prebuilt by `make "):
            continue
        lines.append(line)
    return "".join(lines)


def select_tasks(task_ids: list[str] | None, limit: int | None) -> tuple[TaskSpec, ...]:
    if limit is not None and limit < 1:
        raise ValueError("--limit must be positive")
    aliases = {alias: task for task in TASKS
               for alias in (task.task_id, task.upstream_path)}
    if task_ids:
        unknown = set(task_ids) - aliases.keys()
        if unknown:
            raise ValueError(f"Unknown/non-CPU task IDs: {', '.join(sorted(unknown))}")
        wanted = {aliases[name] for name in task_ids}
        selected = tuple(task for task in TASKS if task in wanted)
    else:
        selected = TASKS
    return selected[:limit] if limit else selected


def _git(directory: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def _snapshot(work: Path, source_dir: Path | None) -> Path:
    source = work / "upstream"
    if source_dir is None:
        source.mkdir()
        _git(source, "init", "--quiet")
        _git(source, "remote", "add", "origin", UPSTREAM_URL)
        _git(source, "fetch", "--quiet", "--depth", "1", "origin", UPSTREAM_COMMIT)
        _git(source, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    else:
        source_dir = source_dir.resolve()
        if _git(source_dir, "rev-parse", "HEAD") != UPSTREAM_COMMIT:
            raise ValueError(f"--source-dir must be checked out at {UPSTREAM_COMMIT}")
        if _git(source_dir, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("--source-dir has tracked modifications; use a clean pinned checkout")
        archive = work / "upstream.tar"
        _git(source_dir, "archive", "--format=tar", "-o", str(archive), UPSTREAM_COMMIT)
        source.mkdir()
        with tarfile.open(archive) as stream:
            stream.extractall(source, filter="data")
    return source


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def export_task(source: Path, spec: TaskSpec, destination: Path) -> None:
    native = source / "tasks" / spec.upstream_path
    original = tomllib.loads((native / "task.toml").read_text())
    if original["environment"].get("gpus", 0):
        raise ValueError(f"Refusing GPU task {spec.upstream_path}")
    destination.mkdir()
    for name in ("instruction.md", "README.md"):
        if (native / name).exists():
            shutil.copy2(native / name, destination / name)
    for name in ("environment", "solution"):
        _copy_tree(native / name, destination / name)

    tests = destination / "tests"
    if spec.family == "task07":
        _copy_tree(native / "tests", tests)
    else:
        # Preserve repository-root COPY paths, so upstream Dockerfiles stay verbatim.
        tests.mkdir()
        context = tests / "tasks" / spec.upstream_path / "tests"
        context.parent.mkdir(parents=True)
        _copy_tree(native / "tests", context)
        for name in ("Dockerfile", "test.sh"):
            shutil.copy2(native / "tests" / name, tests / name)
        for name in _SHARED_FILES:
            target = tests / "rlebench" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / "rlebench" / name, target)

    config = portable_config((native / "task.toml").read_text())
    (destination / "task.toml").write_text(config)
    parsed = tomllib.loads(config)
    for section in (original["environment"], original["verifier"]["environment"]):
        section.pop("docker_image", None)
    if parsed != original:
        raise ValueError(f"Unexpected task configuration changes: {spec.task_id}")

    files = {}
    for root in ("environment", "solution", "tests"):
        for path in sorted((destination / root).rglob("*")):
            if path.is_file():
                files[path.relative_to(destination).as_posix()] = sha256(path)
    files["instruction.md"] = sha256(destination / "instruction.md")
    provenance = {"adapter": "rle-bench", "upstream_url": UPSTREAM_URL,
                  "upstream_commit": UPSTREAM_COMMIT, "upstream_task": spec.upstream_path,
                  "task_id": spec.task_id, "task_name": parsed["task"]["name"],
                  "changes": ["Remove local prebuilt image references; preserve all other config",
                              "Bundle repository-root verifier COPY inputs under tests/"],
                  "file_sha256": files}
    (tests / PROVENANCE).write_text(json.dumps(provenance, indent=2) + "\n")


class RLEBenchAdapter:
    def __init__(self, output_dir: Path, limit: int | None = None, overwrite: bool = False,
                 task_ids: list[str] | None = None, source_dir: Path | None = None):
        self.output_dir = Path(output_dir).resolve()
        self.source_dir = Path(source_dir).resolve() if source_dir else None
        self.tasks = select_tasks(task_ids, limit)
        self.overwrite = overwrite

    def _check_output(self) -> None:
        if self.source_dir and (self.output_dir == self.source_dir
                                or self.source_dir in self.output_dir.parents):
            raise ValueError("Output must be outside the upstream checkout")
        marker = self.output_dir / ROOT_MARKER
        if self.output_dir.exists() and any(self.output_dir.iterdir()):
            owner = json.loads(marker.read_text()) if marker.is_file() else {}
            if owner.get("adapter") != "rle-bench" or owner.get("upstream_commit") != UPSTREAM_COMMIT:
                raise FileExistsError("Refusing non-empty output not owned by this pinned adapter")
        for spec in self.tasks:
            target = self.output_dir / spec.task_id
            if target.exists():
                owned = target / "tests" / PROVENANCE
                if not self.overwrite or not owned.is_file():
                    raise FileExistsError(f"Task already exists: {target}; --overwrite replaces generated tasks only")
                owner = json.loads(owned.read_text())
                if (owner.get("adapter"), owner.get("upstream_commit"), owner.get("task_id")) != (
                        "rle-bench", UPSTREAM_COMMIT, spec.task_id):
                    raise FileExistsError(f"Refusing task with foreign provenance: {target}")

    def run(self) -> list[Path]:
        self._check_output()
        with tempfile.TemporaryDirectory(prefix="rle-bench-source-") as temporary:
            source = _snapshot(Path(temporary), self.source_dir)
            for family in dict.fromkeys(task.family for task in self.tasks):
                subprocess.run([sys.executable, str(source / "tasks" / family / "build_assets.py")],
                               cwd=source, check=True)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / ROOT_MARKER).write_text(json.dumps({
                "adapter": "rle-bench", "upstream_commit": UPSTREAM_COMMIT,
                "upstream_url": UPSTREAM_URL}, indent=2) + "\n")
            for spec in self.tasks:
                with tempfile.TemporaryDirectory(prefix=".rle-bench-export-", dir=self.output_dir) as staging:
                    staged = Path(staging) / spec.task_id
                    export_task(source, spec, staged)
                    destination = self.output_dir / spec.task_id
                    backup = Path(staging) / "previous"
                    if destination.exists():
                        destination.rename(backup)
                    try:
                        staged.rename(destination)
                    except BaseException:
                        if backup.exists():
                            backup.rename(destination)
                        raise
                LOG.info("Generated %s", destination)
            for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                shutil.copy2(source / name, self.output_dir / name)
        self._write_manifest()
        return [self.output_dir / spec.task_id for spec in self.tasks]

    def _write_manifest(self) -> None:
        from harbor.models.dataset.manifest import DatasetFileRef, DatasetInfo, DatasetManifest, DatasetTaskRef
        from harbor.models.task.config import Author
        from harbor.publisher.packager import Packager

        tasks = []
        for spec in TASKS:
            path = self.output_dir / spec.task_id
            if not (path / "tests" / PROVENANCE).is_file():
                continue
            task = tomllib.loads((path / "task.toml").read_text())["task"]
            digest, _ = Packager.compute_content_hash(path)
            tasks.append(DatasetTaskRef(name=task["name"], digest=f"sha256:{digest}"))
        manifest = DatasetManifest(dataset=DatasetInfo(
            name=DATASET_NAME,
            description="Five CPU-only RLE-Bench tasks. Native instructions, baselines, scoring and budgets are preserved.",
            authors=[Author(name="Haitong Ma", email="haitongma@g.harvard.edu"),
                     Author(name="Dongzhikang", email="darrendong@qq.com")],
            keywords=["robotics", "mujoco", "cpu"]), tasks=tasks,
            files=[DatasetFileRef(path=name, digest=f"sha256:{sha256(self.output_dir / name)}")
                   for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", ROOT_MARKER)])
        (self.output_dir / "dataset.toml").write_text(manifest.to_toml())
