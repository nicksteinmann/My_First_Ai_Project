import unittest

from services.tools.turn_handler import (
    _find_narration_policy_violations,
    _find_state_claims,
    _is_non_narrative_placeholder,
    _should_block_direct_reward_tool,
    _unsupported_state_claims,
)


class TurnHandlerGuardTestCase(unittest.TestCase):
    def test_partial_objective_progress_is_not_quest_completion(self):
        claims = _find_state_claims("Quest #1 - 1/6 Ratten erledigt.")

        self.assertNotIn("quest_completion", claims)

    def test_completed_job_claim_requires_structured_reward_tool(self):
        claims = _find_state_claims("Der Auftrag ist erledigt. Du erhaeltst +22 Kupfer.")

        self.assertIn("quest_completion", claims)
        self.assertIn("currency_gain", claims)
        self.assertEqual(
            ["currency_gain", "quest_completion"],
            _unsupported_state_claims(claims, successful_tool_names=[]),
        )
        self.assertEqual(
            [],
            _unsupported_state_claims(claims, successful_tool_names=["turn_in_quest"]),
        )

    def test_already_provided_placeholder_is_rejected(self):
        self.assertTrue(
            _is_non_narrative_placeholder(
                "(Already provided a reply earlier; conversation continues.)"
            )
        )

    def test_direct_currency_tool_is_blocked_for_paid_work_context(self):
        messages = [
            {
                "role": "assistant",
                "content": "Der Wirt bietet dir Arbeit im Keller an und verspricht Lohn.",
            },
            {
                "role": "user",
                "content": "Ich nehme den Job an und will die Bezahlung.",
            },
        ]

        self.assertTrue(
            _should_block_direct_reward_tool(
                "add_currency",
                messages,
                successful_tool_names=[],
            )
        )

    def test_fixed_numeric_job_offer_is_policy_violation_without_quest_context(self):
        violations = _find_narration_policy_violations(
            "Der Wirt bietet dir einen Auftrag an und zahlt 5 Silber.",
            successful_tool_names=[],
        )

        self.assertEqual(["fixed_job_reward_offer"], violations)


if __name__ == "__main__":
    unittest.main()
