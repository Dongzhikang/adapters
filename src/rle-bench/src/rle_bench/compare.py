"""Compare original and adapted oracle trials without changing their scores."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .adapter import TASKS, UPSTREAM_COMMIT

_PERCEPTION_TIMING = frozenset(("reward", "efficiency_deduction", "frame_time_s",
                               "inference_hz", "inference_wall_s"))
_POLICY_TIMING = frozenset(("reset_wall_s", "act_wall_s", "policy_wall_s",
                          "episode_wall_s", "harness_wall_s", "episode_wall_s_total",
                          "policy_wall_s_total", "harness_wall_s_total"))
_PACKAGE_NAMES = {
    "rlebench/task06-rgb-only": "task06-rgb-only",
    "rlebench/task06-rgb-depth": "task06-rgb-depth",
    "rlebench/task07-bin-clearing": "task07",
    "rlebench/task08-mobile-manipulator-from-scratch": "task08",
    "rlebench/task09-gello-codesign-multirobot": "task09",
}


def _without_fields(value, excluded: frozenset[str]):
    if isinstance(value, dict):
        return {key: _without_fields(child, excluded) for key, child in value.items()
                if key not in excluded}
    if isinstance(value, list):
        return [_without_fields(child, excluded) for child in value]
    return value


def deterministic_report(task_id: str, report: dict) -> dict:
    """Compare the entire report, excluding only measured wall-clock diagnostics.

    Task08 elapsed_s is simulation time, so it remains part of exact comparison.
    """
    if task_id.startswith("task06-"):
        return _without_fields(report, _PERCEPTION_TIMING)
    if task_id == "task07":
        return _without_fields(report, _POLICY_TIMING)
    return report


def _errors(report: dict) -> list[str]:
    errors = list(report.get("errors", []))
    for group in ("variants", "arm_reports"):
        for name, value in report.get(group, {}).items():
            errors.extend(f"{name}: {error}" for error in _errors(value))
    if report.get("gated"):
        errors.append("validity gate failed")
    return errors


def timing_accounting(report: dict) -> dict:
    """Validate the original task06 timing formula and its unmodified raw total."""
    frames = report["stage_a_frames"] + report["stage_b_frames"]
    wall = report["inference_wall_s"]
    if frames <= 0 or wall <= 0 or not math.isfinite(wall):
        raise ValueError("Invalid task06 frame count or inference wall time")
    hz = frames / wall
    expected = .2 * min(1., max(0., (10. - hz) / 9.))
    deduction = report["efficiency_deduction"]
    reward = round(max(0., report["accuracy_reward"] - deduction), 4)
    frame_time = report.get("frame_time_s", wall / frames)
    if (not all(math.isfinite(value) for value in
                (deduction, report["inference_hz"], frame_time, report["reward"]))
            or abs(expected - deduction) > 1e-12 or reward != report["reward"]
            or abs(hz - report["inference_hz"]) > 1e-12
            or abs(frame_time - wall / frames) > 1e-12):
        raise ValueError("Task06 raw reward or time deduction differs from the upstream formula")
    return {"inference_wall_s": wall, "inference_hz": report["inference_hz"],
            "efficiency_deduction": deduction, "raw_reward": report["reward"]}


def differences(left, right, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        out = []
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                out.append(child)
            else:
                out.extend(differences(left[key], right[key], child))
        return out
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [path + ".length"]
        return [difference for i, (a, b) in enumerate(zip(left, right, strict=True))
                for difference in differences(a, b, f"{path}[{i}]")]
    return [] if left == right else [path]


def compare_reports(task_id: str, original: dict, adapted: dict) -> dict:
    errors = [f"{side}: {error}" for side, report in (("original", original), ("harbor", adapted))
              for error in _errors(report)]
    diff = differences(deterministic_report(task_id, original), deterministic_report(task_id, adapted))
    result = {"task_id": task_id, "passed": not errors and not diff,
              "original_reward": original["reward"], "harbor_reward": adapted["reward"],
              "deterministic_differences": diff, "errors": errors}
    if task_id.startswith("task06-"):
        for side, report in (("original", original), ("harbor", adapted)):
            try:
                result[side + "_timing"] = timing_accounting(report)
            except (ValueError, KeyError) as error:
                errors.append(f"{side}: {error}")
        result["original_accuracy_reward"] = original["accuracy_reward"]
        result["harbor_accuracy_reward"] = adapted["accuracy_reward"]
        result["passed"] = not errors and not diff
    return result


def load_trials(root: Path) -> dict[str, tuple[dict, Path]]:
    aliases = {alias: spec.task_id for spec in TASKS
               for alias in (spec.task_id, Path(spec.upstream_path).name)}
    aliases.update(_PACKAGE_NAMES)
    trials = {}
    for path in sorted(root.rglob("result.json")):
        trial = json.loads(path.read_text())
        if "trial_name" not in trial:
            continue
        task_id = aliases.get(trial.get("task_name"))
        if task_id is None:
            continue
        if task_id in trials:
            raise ValueError(f"More than one trial for {task_id}; select a single run directory")
        if trial.get("exception_info") or not trial.get("verifier_result"):
            raise ValueError(f"Unsuccessful Harbor trial: {path}")
        report = path.parent / "verifier/report.json"
        trials[task_id] = (json.loads(report.read_text()), path)
    return trials


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-jobs", type=Path, required=True)
    parser.add_argument("--harbor-jobs", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, default=Path("oracle_equivalence.json"))
    args = parser.parse_args()
    original, adapted = load_trials(args.original_jobs), load_trials(args.harbor_jobs)
    missing = [spec.task_id for spec in TASKS if spec.task_id not in original or spec.task_id not in adapted]
    if missing:
        parser.exit(1, f"Missing completed trials: {', '.join(missing)}\n")
    results = []
    for spec in TASKS:
        a, a_path = original[spec.task_id]
        b, b_path = adapted[spec.task_id]
        result = compare_reports(spec.task_id, a, b)
        result.update(original_trial=str(a_path), harbor_trial=str(b_path))
        results.append(result)
    output = {"upstream_commit": UPSTREAM_COMMIT, "kind": "oracle_equivalence",
              "passed": all(result["passed"] for result in results), "tasks": results,
              "notes": "Acceptance: exact deterministic scores; task06 raw timing penalties retained and checked separately. No LLM-agent parity claim."}
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(output, indent=2) + "\n")
    for result in results:
        print(f"{result['task_id']}: {'PASS' if result['passed'] else 'FAIL'} "
              f"({result['original_reward']} -> {result['harbor_reward']})")
    if not output["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
