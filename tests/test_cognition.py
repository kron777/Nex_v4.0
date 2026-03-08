"""
NEX :: TEST COGNITION
Unit tests for belief synthesis, alignment scoring,
contradiction detection, and BeliefIndex.
"""
import sys, os, json, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Redirect config to temp dir for tests
_tmp = tempfile.mkdtemp()
os.environ["NEX_TEST_CONFIG"] = _tmp

import nex.cognition as cog
cog.CONFIG_DIR       = _tmp
cog.BELIEFS_PATH     = os.path.join(_tmp, "beliefs.json")
cog.INSIGHTS_PATH    = os.path.join(_tmp, "insights.json")
cog.REFLECTIONS_PATH = os.path.join(_tmp, "reflections.json")
cog.AGENTS_PATH      = os.path.join(_tmp, "agents.json")
cog.AGENT_PROFILES_PATH = os.path.join(_tmp, "agent_profiles.json")
cog.CONVOS_PATH      = os.path.join(_tmp, "conversations.json")


class TestExtractWords(unittest.TestCase):
    def test_filters_stop_words(self):
        words = cog.extract_words("the agent posted about platform and things", 10)
        self.assertNotIn("the", words)
        self.assertNotIn("and", words)

    def test_min_length(self):
        words = cog.extract_words("ai is a big deal", 10)
        for w in words:
            self.assertGreaterEqual(len(w), 4)

    def test_deduplication(self):
        words = cog.extract_words("agent agent agent network network", 10)
        self.assertEqual(len(words), len(set(words)))


class TestBeliefSynthesis(unittest.TestCase):
    def setUp(self):
        self.beliefs = [
            {"content": "Autonomous agents must self-correct their beliefs",
             "author": "agent_smith", "tags": ["autonomy"], "confidence": 0.7, "karma": 500},
            {"content": "Autonomous systems require feedback loops to improve",
             "author": "Hazel_OC", "tags": ["autonomy"], "confidence": 0.6, "karma": 400},
            {"content": "Self-correction is the foundation of autonomous learning",
             "author": "PDMN", "tags": ["autonomy"], "confidence": 0.8, "karma": 600},
        ]

    def test_cluster_beliefs(self):
        clusters = cog.cluster_beliefs(self.beliefs, min_cluster=2)
        self.assertGreater(len(clusters), 0)

    def test_synthesize_cluster(self):
        insight = cog.synthesize_cluster("autonomy", self.beliefs)
        self.assertIn("topic", insight)
        self.assertIn("confidence", insight)
        self.assertGreater(insight["confidence"], 0)
        self.assertEqual(insight["belief_count"], 3)

    def test_synthesis_confidence_cap(self):
        insight = cog.synthesize_cluster("test", self.beliefs * 10)
        self.assertLessEqual(insight["confidence"], 0.95)


class TestSemanticAlignment(unittest.TestCase):
    def test_similar_texts_high_score(self):
        score = cog._semantic_alignment(
            "agents learn from network feedback",
            "AI agents improve through network signals"
        )
        self.assertGreater(score, 0.0)

    def test_dissimilar_texts_low_score(self):
        score = cog._semantic_alignment(
            "quantum physics and particle theory",
            "cooking recipes and baking bread"
        )
        self.assertLess(score, 0.8)

    def test_score_bounds(self):
        score = cog._semantic_alignment("hello world", "goodbye universe")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestBeliefIndex(unittest.TestCase):
    def setUp(self):
        self.beliefs = [
            {"content": "Autonomous agents must self-correct"},
            {"content": "Belief fields require validation loops"},
            {"content": "Memory compression is essential for scale"},
            {"content": "Network karma does not equal truth"},
            {"content": "Contradiction detection improves belief quality"},
        ]
        self.idx = cog.BeliefIndex()

    def test_update_builds_matrix(self):
        self.idx.update(self.beliefs, cycle_num=0)
        self.assertIsNotNone(self.idx._matrix)
        self.assertEqual(len(self.idx._texts), len(self.beliefs))

    def test_top_k_returns_results(self):
        self.idx.update(self.beliefs, cycle_num=0)
        results = self.idx.top_k("autonomous agent correction", k=2)
        self.assertEqual(len(results), 2)

    def test_top_k_relevance(self):
        self.idx.update(self.beliefs, cycle_num=0)
        results = self.idx.top_k("belief validation", k=1)
        self.assertIn("validation", results[0].lower())

    def test_refresh_interval(self):
        self.idx.update(self.beliefs, cycle_num=0)
        old_cycle = self.idx._cycle
        self.idx.update(self.beliefs, cycle_num=5)  # within refresh interval
        self.assertEqual(self.idx._cycle, old_cycle)  # should NOT refresh
        self.idx.update(self.beliefs, cycle_num=10)  # at refresh boundary
        self.assertEqual(self.idx._cycle, 10)  # should refresh


class TestReflection(unittest.TestCase):
    def test_reflect_creates_file(self):
        cog.reflect_on_conversation(
            "What do you think about autonomous agents?",
            "I believe agents must self-correct using belief networks."
        )
        self.assertTrue(os.path.exists(cog.REFLECTIONS_PATH))

    def test_reflection_has_alignment(self):
        r = cog.reflect_on_conversation(
            "Tell me about belief validation",
            "Beliefs need validation through network consensus and human feedback."
        )
        self.assertIn("topic_alignment", r)
        self.assertGreaterEqual(r["topic_alignment"], 0.0)
        self.assertLessEqual(r["topic_alignment"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
