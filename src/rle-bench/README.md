# RLE-Bench CPU → Harbor

## Overview

This adapter exports five CPU tasks from RLE-Bench into independently buildable
Harbor task directories. It preserves native instructions, reference submissions,
verifier code, numeric scoring, hidden scenarios and resource budgets.

- Upstream: [RLE-Bench/RLE-Bench](https://github.com/RLE-Bench/RLE-Bench).
- Source revision: `c6bf572283b5453c0ee76eaa3054f23d691e433d`.
- Harness: `harbor==0.21.0`, matching that upstream revision.
- Dataset identifier: `rlebench/rle-bench-cpu` (not yet published).
- Status: CPU oracle equivalence validated; GPU testing is work in progress.
  This contribution currently contains CPU tasks and CPU results only.

## What is RLE-Bench?

RLE-Bench evaluates coding agents acting as robotics engineers. Agents develop
perception algorithms, robot policies, mechanical designs and controllers;
simulators evaluate their submitted behavior. This adapter selects five CPU tasks
from the nine-family, 51-task upstream matrix. GPU tasks are deferred.

| Exported task ID | Native selector | Agent work | Native oracle |
| --- | --- | --- | --- |
| `task06-rgb-only` | `task06/rgb-only` | Estimate shape and planar pose from RGB | RGB reference estimator |
| `task06-rgb-depth` | `task06/rgb-depth` | Estimate shape and pose from RGB-D | Fused reference estimator |
| `task07` | `task07` | Clear a bin with a magnet-tipped Panda | Public depth baseline policy |
| `task08` | `task08` | Design a common mobile base and shelf controller | Reference chassis and controller |
| `task09` | `task09` | Co-design three GELLO lead arms and compensation | Three pinned hardware/software submissions |

## Adapter Features

- Fetches an exact source commit, or reads a clean checkout at that commit.
  Asset generation runs in an owned temporary snapshot; the supplied checkout is
  never used as a staging directory.
- Copies instructions, oracle payloads, verifier code and Dockerfiles verbatim.
  A per-task SHA-256 manifest records the copied files.
- Removes only the two local prebuilt-image references from each `task.toml`.
  Harbor builds the supplied agent and verifier Dockerfiles instead.
- Preserves upstream verifier Dockerfile `COPY` paths by bundling the necessary
  repository-root files inside the task's `tests/` build context.
- Preserves separate verification, original artifact paths, CPU limits, memory,
  timeouts, image dimensions, episode counts and `reward.json` metrics.
- Uses standard Harbor agents; no new agent implementation is introduced.
- Rejects GPU selectors and protects non-generated output directories.

## Generated Task Structure

```text
datasets/rle-bench-cpu/
├── dataset.toml
├── rle-bench-source.json
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── task06-rgb-only/
├── task06-rgb-depth/
├── task07/
├── task08/
└── task09/
    ├── task.toml
    ├── instruction.md
    ├── environment/          # original Dockerfile and public assets
    ├── solution/             # original solve.sh and generated payload
    └── tests/                # independent verifier Docker build context
        ├── Dockerfile
        ├── test.sh
        ├── rle-bench-provenance.json
        ├── rlebench/         # original shared verifier utilities
        └── tasks/task09/tests/
            ├── harness/
            ├── models/
            ├── score_task.py
            └── test.sh
```

Task07 already has a self-contained verifier build context and retains its native
`tests/` layout. The other four tasks use the nested layout above. Private verifier
files stay outside `environment/`. The package's `task-template/` contains the
representative native task08 layout for adapter tooling; each exported task uses
its own pinned upstream files and generated assets.

## Run Evaluation / Harness

Registry execution will be available after publication. Until then, generate the
tasks and run them locally from this adapter directory:

```bash
uv run harbor run -c run_rle-bench.yaml

# One task, with the original scoring and resource limits:
uv run harbor run -p datasets/rle-bench-cpu/task08 -a oracle -n 1 \
  --ve RLEBENCH_MEDIA=0 --yes

# All five tasks:
uv run harbor run -p datasets/rle-bench-cpu -a oracle -n 5 \
  -o jobs/harbor --job-name oracle --ve RLEBENCH_MEDIA=0 --yes
```

Oracle execution needs no model API key. The media switch disables informational
recordings; sensor observations and scoring remain unchanged. Each task writes
`verifier/reward.json` and the detailed `verifier/report.json`.

For model agents, provide credentials and match upstream's provider configuration.
For example, the native default Codex API lane uses `OPENAI_API_KEY` and these
installation/API hosts:

```bash
uv run harbor run -p datasets/rle-bench-cpu/task08 \
  -a codex -m "openai/MODEL_ID" \
  --allow-environment-host deb.debian.org \
  --allow-environment-host raw.githubusercontent.com \
  --allow-environment-host github.com \
  --allow-environment-host objects.githubusercontent.com \
  --allow-environment-host nodejs.org \
  --allow-environment-host registry.npmjs.org \
  --allow-environment-host api.openai.com \
  --allow-environment-host auth.openai.com \
  --ak web_search=disabled
```

Replace `MODEL_ID` with an available model. Other providers need the corresponding
credentials and host allowlists from upstream `rlebench/providers.py`. Model-agent
evaluations have not been run as part of this oracle-only validation.

## Usage: Create Task Directories

```bash
cd src/rle-bench
uv sync --locked --group dev

# Fetch the pinned source and generate all five CPU tasks:
uv run rle-bench --output-dir datasets/rle-bench-cpu

# Reuse a clean checkout at the pinned commit without modifying that checkout:
uv run rle-bench --source-dir /path/to/RLE-Bench \
  --output-dir datasets/rle-bench-cpu

# Select individual tasks, limit the selection, or regenerate owned task folders:
uv run rle-bench --list
uv run rle-bench --task-ids task06/rgb-only task09 --limit 1 \
  --output-dir datasets/small
uv run rle-bench --overwrite --output-dir datasets/rle-bench-cpu
```

Native selectors and exported task IDs are accepted. Selection order is stable.
`--overwrite` replaces only selected, provenance-marked tasks and preserves
unrelated files at the output root. Dataset manifests include all existing owned
CPU tasks in that output directory, with Harbor's content digests.

## Comparison with Original Benchmark (Parity)

This release validates **oracle equivalence**, with one complete native run and
one complete adapted run per task. It does not claim LLM-agent parity or estimate
sample SEM from a single run. Organizer coordination reported by the contributor
on 2026-11-16 permits upstream baseline/reference oracles without requiring full
reward. The acceptance criterion is preservation of the original measurement.

All five tasks passed the agreed equivalence criterion. Single observations are
shown below; sample SEM is undefined for `n=1`. The complete comparison is in
[oracle_equivalence.json](oracle_equivalence.json).

| Agent | Model | Metric | Runs per side | Dataset Size | Original observation | Harbor observation |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| oracle@harbor-0.21.0 | None | task06/rgb-only accuracy_reward | 1 | 1 | 0.2974174159335837 | 0.2974174159335837 |
| oracle@harbor-0.21.0 | None | task06/rgb-depth accuracy_reward | 1 | 1 | 0.292222651588023 | 0.292222651588023 |
| oracle@harbor-0.21.0 | None | task07 reward | 1 | 1 | 0.0572 | 0.0572 |
| oracle@harbor-0.21.0 | None | task08 reward | 1 | 1 | 0.7564 | 0.7564 |
| oracle@harbor-0.21.0 | None | task09 reward | 1 | 1 | 0.7154333333333334 | 0.7154333333333334 |

Raw verifier rewards (task06 includes its original real-time deduction):

| Task | Native reward | Native accuracy reward | Adapted oracle |
| --- | ---: | ---: | --- |
| task06/rgb-only | 0.1081 | 0.2974174159335837 | 0.1082; deterministic metrics matched |
| task06/rgb-depth | 0.0964 | 0.292222651588023 | 0.0966; deterministic metrics matched |
| task07 | 0.0572 | — | 0.0572; deterministic metrics matched |
| task08 | 0.7564 | — | 0.7564; full report matched |
| task09 | 0.7154333333333334 | — | 0.7154333333333334; full report matched |

Reproduce the original side in a separate checkout after `make install`. From this
adapter directory, `bash scripts/prepare_native_cpu.sh /path/to/RLE-Bench` prepares
only the five CPU tasks. It runs the native asset builders and original Dockerfiles;
it does not build task06's CUDA variants.

```bash
# From the original RLE-Bench checkout, with its environment activated:
rlebench run task06/rgb-only task06/rgb-depth task07 task08 task09 \
  -a oracle --device cpu --jobs 5 -o /path/to/original-jobs \
  -- --ve RLEBENCH_MEDIA=0 --yes -n 1

# From this adapter directory, after generation:
uv run harbor run -p datasets/rle-bench-cpu -a oracle -n 5 \
  -o /path/to/harbor-jobs --job-name oracle --ve RLEBENCH_MEDIA=0 --yes

uv run rle-bench-compare --original-jobs /path/to/original-jobs \
  --harbor-jobs /path/to/harbor-jobs --output-file oracle_equivalence.json
```

The comparator requires exact equality of complete reports after excluding only
measured wall-clock diagnostics. This includes task07's eight episode outcomes,
task08's controller outcomes, simulation times and action digests, and task09's
per-variant diagnostics. Task08 and task09 reports matched in full. For task06 it
compares accuracy and all other deterministic metrics exactly, then independently
checks the original inference-time deduction and raw reward arithmetic. It never
overrides or normalizes a verifier reward.

No upstream fork is required: both sides use the original Harbor-compatible
oracles. Adapter submission: [harbor-index/adapters#15](https://github.com/harbor-index/adapters/pull/15)
(draft). Registry and experiment publication remain pending.

## Notes & Caveats

- Scope is the five CPU tasks listed above. Task01–05 and task06's
  `rgb-depth-model-training` and `method-agnostic` variants are excluded.
  GPU testing remains work in progress; no GPU execution or passing GPU result
  is claimed by this CPU adapter.
- These oracles are reference implementations and baselines, not optimal answers.
  Low valid rewards are preserved. In the native run, task08's base passes the
  dynamics battery but its controller misses some shelf targets; task06's moving,
  occluded scenes and inference-time deduction limit the reference score.
- Task06 scores contain real wall-clock inference measurements. Its Gaussian
  accuracy kernels award full credit only at zero error. Native runs can produce
  different total rewards even with identical deterministic predictions. The
  contributor explicitly accepted exact deterministic-score matching with timing
  accounting checked separately.
- Harbor 0.21.0 and the source commit are pinned. Later Harbor/RLE-Bench upgrades
  can change networking, sandbox behavior and GPU handling and require new checks.
- Dockerfiles retain the original `python:3.12-slim` base declaration and exact
  numerical package pins. Record actual image digests for long-term reproduction;
  the base tag and transitive dependencies can change across builds.
- No benchmark instructions, scoring formulas, hidden seeds, budgets or oracle
  algorithms have been patched. The local prebuilt image references are removed
  only to enable builds from the exported directories.
- Oracle equivalence is separate from model-agent parity. Paid model experiments
  and registry/Hugging Face publication are outside the current validation.
- Upstream MIT and third-party notices are copied into the generated dataset;
  vendored robot assets retain their original license files.

## Installation / Prerequisites

- Linux, Git, Python 3.12, uv and a running Docker daemon with Compose support.
- Internet access for the initial source/dependency/image downloads. No NVIDIA
  runtime or GPU is needed for these five tasks.
- Per task, native CPU environments request four CPUs and 4–6 GiB RAM. Running
  five tasks concurrently needs resources for their combined containers.
- Install with `uv sync --locked --group dev`; the lock includes Harbor 0.21.0
  and the original numerical library versions used to generate assets.

## Troubleshooting

- **Wrong source revision / dirty checkout:** use a clean checkout at the pinned
  commit, or omit `--source-dir` to fetch an owned snapshot automatically.
- **Non-empty unowned output:** choose a new output directory. `--overwrite`
  intentionally does not erase unrelated research directories.
- **Missing Docker COPY input:** regenerate the complete task; copied verifier
  contexts include their original repository-relative input paths.
- **Model API cannot be reached:** supply provider credentials and the matching
  upstream host allowlist. Keep verifier isolation and scoring unchanged.
- **Small task06 total-score differences:** inspect accuracy, inference wall time
  and deduction separately with `rle-bench-compare`.
- **Long oracle run:** task07 performs eight fully rendered hidden episodes;
  task08 evaluates three arms and their shelf targets. Keep original budgets for
  fidelity and inspect the trial logs before interpreting a timeout as a score.

Run adapter tests with `uv run pytest -q`. Validate the adapter structure from the
adapters repository root with `python scripts/validate_adapter.py rle-bench`.

## Citation

```bibtex
@article{ma2026rle,
  title={RLE-Bench: A Qualifying Exam for Coding Agents as Robot Learning Engineers},
  author={Ma, Haitong and Gao, Chenxiao and Qiang, Rushi and Li, Na and Dai, Bo},
  journal={arXiv preprint arXiv:2609.34210},
  year={2026}
}
```

## Authors & Contributions

RLE-Bench and its reference implementations are the work of Haitong Ma and the
RLE-Bench contributors. The adapter preserves upstream task author attribution.
Adapter packaging and validation: Dongzhikang (darrendong@qq.com).
