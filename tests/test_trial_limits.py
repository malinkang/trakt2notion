import unittest
from unittest.mock import Mock, patch

from trakt2notion.sync import TraktSync


class TraktHistoryLimitTests(unittest.TestCase):
    def make_sync(self):
        sync = TraktSync.__new__(TraktSync)
        sync.trakt_access_token = "token"
        sync.headers = {"Authorization": "Bearer token"}
        return sync

    @patch("trakt2notion.sync.requests.get")
    def test_trial_limit_is_sent_to_trakt(self, request_get):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": index} for index in range(100)]
        request_get.return_value = response

        history = self.make_sync().fetch_history("movies", max_items=40)

        self.assertEqual(len(history), 40)
        self.assertEqual(request_get.call_args.kwargs["params"], {"limit": 40})

    @patch("trakt2notion.sync.requests.get")
    def test_paid_sync_preserves_default_request(self, request_get):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": "one"}]
        request_get.return_value = response

        history = self.make_sync().fetch_history("episodes")

        self.assertEqual(history, [{"id": "one"}])
        self.assertIsNone(request_get.call_args.kwargs["params"])

    @patch("trakt2notion.sync.requests.get")
    def test_zero_limit_skips_upstream_request(self, request_get):
        self.assertEqual(self.make_sync().fetch_history("movies", max_items=0), [])
        request_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
