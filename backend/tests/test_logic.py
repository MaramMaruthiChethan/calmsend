import unittest

from app.logic import CalmSendEngine, LABEL_CAUTION, LABEL_HIGH_RISK, LABEL_SAFE


class CalmSendEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = CalmSendEngine()

    def test_safe_message_can_send(self) -> None:
        result = self.engine.analyze(
            "I want to discuss this calmly tomorrow when we both have time.",
            "Alex",
            "whatsapp",
            "chat",
            "smart",
        )
        self.assertEqual(result.label, LABEL_SAFE)
        self.assertTrue(result.can_send_now)

    def test_high_risk_message_triggers_cooldown(self) -> None:
        result = self.engine.analyze(
            "YOU NEVER LISTEN!!! what the hell is wrong with you",
            "Alex",
            "instagram",
            "chat",
            "strict",
        )
        self.assertEqual(result.label, LABEL_HIGH_RISK)
        self.assertGreaterEqual(result.cooldown_seconds, 160)
        self.assertIn("send_until_cooldown_finishes", result.blocked_features)

    def test_caution_message_rewrite_is_supportive(self) -> None:
        result = self.engine.analyze(
            "I'm annoyed and this keeps bothering me.",
            "Jordan",
            "gmail",
            "email",
            "smart",
        )
        self.assertIn(result.label, {LABEL_CAUTION, LABEL_HIGH_RISK, LABEL_SAFE})
        self.assertIn("Jordan", result.rewritten_message)
        self.assertEqual(result.source_app, "gmail")

    def test_delay_mode_off_disables_hold(self) -> None:
        result = self.engine.analyze(
            "Please send me the update when you can.",
            "Casey",
            "generic",
            "chat",
            "off",
        )
        self.assertEqual(result.cooldown_seconds, 0)

    def test_supported_integrations_are_exposed(self) -> None:
        integrations = self.engine.supported_integrations()
        self.assertTrue(any(item["id"] == "whatsapp" for item in integrations))

    def test_rewrite_removes_dangerous_phrase(self) -> None:
        result = self.engine.analyze(
            "it hurts me more fuck off",
            "Jordan",
            "whatsapp",
            "chat",
            "strict",
        )
        self.assertNotIn("fuck off", result.rewritten_message.lower())
        self.assertNotIn("fuck", result.rewritten_message.lower())
        self.assertIn("need", result.rewritten_message.lower())

    def test_fused_profanity_is_escalated_and_rephrased(self) -> None:
        result = self.engine.analyze(
            "fuckoff",
            "Jordan",
            "whatsapp",
            "chat",
            "smart",
        )
        self.assertIn(result.label, {LABEL_CAUTION, LABEL_HIGH_RISK})
        self.assertGreaterEqual(result.risk_score, 60)
        self.assertNotEqual(result.rewritten_message.strip().lower(), "fuckoff")
        self.assertNotIn("fuckoff", result.rewritten_message.lower())


if __name__ == "__main__":
    unittest.main()
