import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_FILE = Path(__file__).resolve()
PROJECT_ROOT = TEST_FILE.parent.parent if TEST_FILE.parent.name == "tools" else TEST_FILE.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import auto_solver_refactored as solver


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class TransitionStateTests(unittest.TestCase):
    def test_changed_question_number_is_success(self):
        evidence = solver._evaluate_transition_observation(
            {"page_state": "question", "q_num": "第24题"},
            "第23题",
            "旧题目",
        )
        self.assertEqual(solver.TRANSITION_SUCCESS, evidence["status"])

    def test_same_question_without_feedback_is_not_immediate_wrong(self):
        evidence = solver._evaluate_transition_observation(
            {"page_state": "question", "q_num": "第23题"},
            "第23题",
            "旧题目",
        )
        self.assertEqual(solver.TRANSITION_UNKNOWN, evidence["status"])
        self.assertTrue(evidence["same_question"])

    def test_changed_question_number_wins_over_feedback_words(self):
        evidence = solver._evaluate_transition_observation(
            {
                "page_state": "question",
                "q_num": "第24题",
                "feedback_detected": True,
            },
            "第23题",
            "旧题目",
        )
        self.assertEqual(solver.TRANSITION_SUCCESS, evidence["status"])

    def test_six_second_uia_gap_can_still_reach_next_question(self):
        clock = FakeClock()

        def marker():
            if clock.now >= 7.2:
                return {"page_state": "question", "q_num": "第24题"}
            return None

        with (
            patch.object(solver.time, "monotonic", clock.monotonic),
            patch.object(solver.time, "sleep", clock.sleep),
            patch.object(solver, "_get_uia_page_marker", side_effect=marker),
            patch.object(solver, "get_clipboard_data_robust", return_value=None),
        ):
            result = solver.wait_for_next_question("第23题", "旧题目")

        self.assertEqual(solver.TRANSITION_SUCCESS, result)
        self.assertGreaterEqual(clock.now, 7.2)

    def test_missing_evidence_returns_unknown_after_grace_period(self):
        clock = FakeClock()
        with (
            patch.multiple(
                solver,
                QUESTION_TRANSITION_TIMEOUT=2.0,
                QUESTION_TRANSITION_GRACE_TIMEOUT=2.0,
            ),
            patch.object(solver.time, "monotonic", clock.monotonic),
            patch.object(solver.time, "sleep", clock.sleep),
            patch.object(solver, "_get_uia_page_marker", return_value=None),
            patch.object(solver, "get_clipboard_data_robust", return_value=None),
        ):
            result = solver.wait_for_next_question("第23题", "旧题目")

        self.assertEqual(solver.TRANSITION_UNKNOWN, result)

    def test_explicit_feedback_returns_wrong(self):
        clock = FakeClock()
        observation = {
            "page_state": "question",
            "q_num": "第23题",
            "feedback_detected": True,
            "feedback_action": "确定",
        }
        with (
            patch.object(solver.time, "monotonic", clock.monotonic),
            patch.object(solver.time, "sleep", clock.sleep),
            patch.object(
                solver, "_get_uia_page_marker", return_value=observation
            ),
            patch.object(solver, "_click_uia_button", return_value=True),
        ):
            result = solver.wait_for_next_question("第23题", "旧题目")

        self.assertEqual(solver.TRANSITION_WRONG, result)

    def test_same_question_with_visual_popup_returns_wrong(self):
        clock = FakeClock()
        observation = {
            "page_state": "question",
            "q_num": "第23题",
        }
        with (
            patch.object(solver.time, "monotonic", clock.monotonic),
            patch.object(solver.time, "sleep", clock.sleep),
            patch.object(
                solver, "_get_uia_page_marker", return_value=observation
            ),
            patch.object(
                solver, "dismiss_answer_feedback", return_value=True
            ),
        ):
            result = solver.wait_for_next_question("第23题", "旧题目")

        self.assertEqual(solver.TRANSITION_WRONG, result)

    def test_stale_question_context_is_rejected(self):
        with self.assertRaises(solver.StaleQuestionContext):
            solver._assert_question_context(
                {"q_num": "第23题"},
                {"page_state": "question", "q_num": "第24题"},
                "点击前",
            )

    def test_unknown_transition_does_not_try_next_single_option(self):
        q_info = {
            "q_num": "第23题",
            "q_type": "单选题",
            "q_text": "旧题目",
            "options": {"A": "甲", "B": "乙"},
        }
        with (
            patch.object(solver, "verify_and_click", return_value=True) as verify,
            patch.object(solver, "click_submit_button", return_value=True),
            patch.object(
                solver,
                "wait_for_next_question",
                return_value=solver.TRANSITION_UNKNOWN,
            ),
        ):
            with self.assertRaises(solver.TransitionEvidenceInsufficient):
                solver.solve_single_choice(
                    q_info, {"A": (1, 1), "B": (2, 2)}, None
                )

        self.assertEqual(1, verify.call_count)


if __name__ == "__main__":
    unittest.main()
