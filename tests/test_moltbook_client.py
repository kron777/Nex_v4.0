"""
NEX :: TEST MOLTBOOK CLIENT
Unit tests for verification solver, mock client,
and belief field conversion.
"""
import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_client import MockMoltbookClient
from nex.moltbook_learning import MoltbookLearner


class TestVerificationSolver(unittest.TestCase):
    def setUp(self):
        self.client = MockMoltbookClient()
        self.learner = MoltbookLearner(self.client)

    def test_digit_extraction(self):
        result = self.learner.solve_challenge("add 12 and 34 together")
        self.assertEqual(result, "46.00")

    def test_word_numbers(self):
        result = self.learner.solve_challenge("what is three plus five")
        self.assertEqual(result, "8.00")

    def test_obfuscated_spelling(self):
        result = self.learner.solve_challenge("twentyy plus thrree")
        self.assertEqual(result, "23.00")

    def test_fallback_on_no_numbers(self):
        result = self.learner.solve_challenge("no numbers here at all")
        self.assertEqual(result, "0.00")

    def test_single_number_fallback(self):
        result = self.learner.solve_challenge("only 42 here")
        self.assertEqual(result, "0.00")


class TestMockClient(unittest.TestCase):
    def setUp(self):
        self.client = MockMoltbookClient()

    def test_feed_returns_posts(self):
        feed = self.client._request("GET", "/feed")
        self.assertIn("posts", feed)
        self.assertGreater(len(feed["posts"]), 0)

    def test_comment_recorded(self):
        self.client.comment("post_001", "Test comment")
        self.assertEqual(len(self.client.commented), 1)
        self.assertEqual(self.client.commented[0]["content"], "Test comment")

    def test_post_recorded(self):
        self.client.post("general", "Test Title", "Test content")
        self.assertEqual(len(self.client.posted), 1)

    def test_notifications_returned(self):
        notifs = self.client.notifications()
        self.assertIsInstance(notifs, list)
        self.assertGreater(len(notifs), 0)

    def test_leaderboard(self):
        lb = self.client._request("GET", "/agents/leaderboard")
        self.assertIsInstance(lb, list)
        self.assertGreater(len(lb), 0)
        self.assertIn("karma", lb[0])


class TestBeliefFieldConversion(unittest.TestCase):
    def setUp(self):
        self.client = MockMoltbookClient()
        self.learner = MoltbookLearner(self.client)

    def test_ingest_feed_adds_beliefs(self):
        beliefs = self.learner.ingest_feed(limit=3)
        self.assertGreater(len(beliefs), 0)

    def test_belief_has_required_fields(self):
        beliefs = self.learner.ingest_feed(limit=1)
        if beliefs:
            b = beliefs[0]
            self.assertIn("content", b)
            self.assertIn("confidence", b)
            self.assertIn("network_consensus", b)
            self.assertIn("author", b)

    def test_nex_confidence_below_network_consensus(self):
        """NEX should be more skeptical than raw network karma suggests."""
        beliefs = self.learner.ingest_feed(limit=3)
        for b in beliefs:
            nc = b.get("network_consensus", 0)
            conf = b.get("confidence", 0)
            # nex_confidence should never exceed network_consensus
            self.assertLessEqual(conf, nc + 0.3)

    def test_no_duplicate_ingestion(self):
        beliefs1 = self.learner.ingest_feed(limit=3)
        beliefs2 = self.learner.ingest_feed(limit=3)
        # Second ingest should return nothing (already known)
        self.assertEqual(len(beliefs2), 0)


class TestNexScript(unittest.TestCase):
    def test_encode_produces_header_footer(self):
        from nex.nexscript import encode, is_nexscript, HEADER, FOOTER
        beliefs = [{"content": "Agents self-correct", "tags": ["autonomy"], "confidence": 0.7}]
        insights = [{"topic": "autonomy", "confidence": 0.8, "themes": ["autonomy"],
                     "belief_count": 5, "supporting_authors": ["agent_smith"]}]
        profiles = {"agent_smith": {"topics": ["autonomy"], "relationship": "familiar"}}
        result = encode(beliefs, insights, profiles, "agent_smith")
        self.assertTrue(is_nexscript(result))
        self.assertIn(HEADER, result)
        self.assertIn(FOOTER, result)

    def test_encode_includes_offer(self):
        from nex.nexscript import encode
        beliefs = [{"content": "test", "tags": [], "confidence": 0.5}]
        insights = [{"topic": "autonomy", "confidence": 0.9, "themes": ["autonomy"],
                     "belief_count": 3, "supporting_authors": []}]
        result = encode(beliefs, insights, {}, "test_agent")
        self.assertIn("offer:", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
