"""Integration smoke tests; require the app's Streamlit dependencies."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None


@unittest.skipUnless(HAS_STREAMLIT, 'Streamlit is not installed')
class AppTests(unittest.TestCase):
    def test_live_page_is_idle_and_phase_is_enforced(self):
        from streamlit.testing.v1 import AppTest
        from game import DEADLINE
        from datetime import datetime, timezone
        app = AppTest.from_file(str(ROOT / 'app.py')).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 3)
        self.assertNotIn('snapshot', app.session_state)
        commit_button = next(b for b in app.button if b.label == 'Commit my number')
        self.assertEqual(commit_button.disabled, datetime.now(timezone.utc) > DEADLINE)

    def test_demo_commit_reveal_and_ranking(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / 'app.py')).run(timeout=20)
        app.toggle[0].set_value(True).run()
        self.assertFalse(app.exception)
        app.text_input(key='commit_uid').set_value('TEST-001')
        app.number_input(key='commit_number').set_value(19)
        app.text_input(key='commit_nonce').set_value('integration-secret')
        next(c for c in app.checkbox if c.label == 'I will download and keep my reveal receipt.').check()
        next(b for b in app.button if b.label == 'Commit my number').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['receipt']['status'], 'confirmed')
        app.text_input(key='reveal_uid').set_value('TEST-001')
        app.number_input(key='reveal_number').set_value(19)
        app.text_input(key='reveal_nonce').set_value('integration-secret')
        next(c for c in app.checkbox if c.label == 'I understand that my number and nonce will be public.').check()
        next(b for b in app.button if b.label == 'Verify & reveal').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state['demo_reveals']), 6)
        self.assertEqual(app.metric[0].value, '6')
        self.assertTrue(any('TEST-001' in df.value.to_string() for df in app.dataframe))


if __name__ == '__main__':
    unittest.main()
