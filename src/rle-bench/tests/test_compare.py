from copy import deepcopy
import json

import pytest

from rle_bench.compare import compare_reports, load_trials


def perception(wall):
    accuracy = .3
    hz = 700 / wall
    deduction = .2 * min(1, max(0, (10 - hz) / 9))
    return dict(reward=round(accuracy - deduction, 4), raw_total=accuracy,
                accuracy_reward=accuracy, gated=False, errors=[],
                checkpoints={"G.load": 1, "A.pose": 1, "B.pose": 0},
                stage_a_frames=100, stage_b_frames=600,
                inference_wall_s=wall, inference_hz=hz, efficiency_deduction=deduction)


def test_task06_keeps_real_timing_variation_but_requires_equal_accuracy():
    original, adapted = perception(450), perception(470)
    result = compare_reports("task06-rgb-only", original, adapted)
    assert result["passed"]
    assert result["original_reward"] != result["harbor_reward"]
    adapted["accuracy_reward"] += .01
    assert not compare_reports("task06-rgb-only", original, adapted)["passed"]


def test_modified_timing_penalties_cannot_fake_equivalence():
    original, adapted = perception(450), perception(450)
    adapted["efficiency_deduction"] = 0
    adapted["reward"] = adapted["accuracy_reward"]
    result = compare_reports("task06-rgb-depth", original, adapted)
    assert not result["passed"]
    assert any("time deduction" in error for error in result["errors"])


def test_equal_total_does_not_hide_different_bin_clearing_behaviour():
    original = dict(reward=.0572, gated=False, gate={"determinism": True}, errors=[],
                    episodes=[dict(episode_score=.05, parts_cleared=5)])
    adapted = deepcopy(original)
    adapted["episodes"][0]["parts_cleared"] = 4
    result = compare_reports("task07", original, adapted)
    assert not result["passed"]
    assert result["deterministic_differences"] == ["episodes[0].parts_cleared"]


def test_equal_total_does_not_hide_different_shelf_outcomes():
    original = dict(reward=.75, gated=False, errors=[], arm_reports={
        "panda": dict(reward=.75, pick_compat=dict(score=.75, margin_score=.5,
            deterministic=True, bins=[dict(ok=True, action_sha256="same")], margin_bins=[]))})
    adapted = deepcopy(original)
    adapted["arm_reports"]["panda"]["pick_compat"]["bins"][0]["ok"] = False
    assert not compare_reports("task08", original, adapted)["passed"]


def test_reference_reward_does_not_have_to_be_one():
    report = dict(reward=.7154333333333334, variants={
        "franka": dict(reward=.758, gated=False, errors=[], checkpoints={"hold": 1})})
    assert compare_reports("task09", report, deepcopy(report))["passed"]


def test_only_measured_wall_times_are_excluded_from_bin_report():
    original = dict(reward=.05, episodes=[dict(episode_wall_s=400, makespan_s=120)])
    adapted = deepcopy(original)
    adapted["episodes"][0]["episode_wall_s"] = 450
    assert compare_reports("task07", original, adapted)["passed"]
    adapted["episodes"][0]["makespan_s"] = 119
    assert not compare_reports("task07", original, adapted)["passed"]


def test_full_diagnostics_and_nested_arm_errors_are_checked():
    original = dict(reward=.75, arm_reports={"panda": dict(
        reward=.75, model_info=dict(base_mass=30), errors=[])})
    adapted = deepcopy(original)
    adapted["arm_reports"]["panda"]["model_info"]["base_mass"] = 31
    assert not compare_reports("task08", original, adapted)["passed"]
    original["arm_reports"]["panda"]["errors"] = ["controller failed"]
    assert not compare_reports("task08", original, deepcopy(original))["passed"]


def test_registry_names_are_resolved_and_duplicate_attempts_are_rejected(tmp_path):
    trial = tmp_path / "run/trial"
    (trial / "verifier").mkdir(parents=True)
    data = dict(trial_name="task07__one", task_name="rlebench/task07-bin-clearing",
                verifier_result={"rewards": {"reward": .0572}}, exception_info=None)
    (trial / "result.json").write_text(json.dumps(data))
    (trial / "verifier/report.json").write_text(json.dumps(dict(reward=.0572)))
    assert set(load_trials(tmp_path)) == {"task07"}
    duplicate = tmp_path / "duplicate"
    (duplicate / "verifier").mkdir(parents=True)
    (duplicate / "result.json").write_text(json.dumps(data))
    (duplicate / "verifier/report.json").write_text(json.dumps(dict(reward=.0572)))
    with pytest.raises(ValueError, match="More than one trial"):
        load_trials(tmp_path)
