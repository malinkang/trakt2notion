import unittest
from unittest.mock import Mock, patch

from trakt2notion import sync as trakt_module
from trakt2notion.sync import TraktSync


class TraktHistoryLimitTests(unittest.TestCase):
    @patch.object(trakt_module.NotionHubInternalClient, "from_env")
    @patch.object(trakt_module.NotionHubInternalClient, "is_available", return_value=True)
    def test_paid_sync_refreshes_snapshot_and_embed(self, _available, from_env):
        helper = Mock(heatmap_block_id="heatmap-block")
        from_env.return_value.public_heatmap_url.return_value = "https://i.notionhub.app/heatmap"

        self.assertTrue(trakt_module.refresh_heatmap_after_sync(helper))

        from_env.return_value.refresh_heatmap.assert_called_once_with("trakt", force=True)
        helper.update_heatmap.assert_called_once_with("heatmap-block", "https://i.notionhub.app/heatmap")

    def make_sync(self):
        sync = TraktSync.__new__(TraktSync)
        sync.trakt_access_token = "token"
        sync.headers = {"Authorization": "Bearer token"}
        sync.sync_mode = "incremental"
        return sync

    @patch("trakt2notion.sync.requests.get")
    def test_trial_limit_is_sent_to_trakt(self, request_get):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": index} for index in range(100)]
        request_get.return_value = response

        history = self.make_sync().fetch_history("movies", max_items=40)

        self.assertEqual(len(history), 40)
        self.assertEqual(request_get.call_args.kwargs["params"], {"limit": 40, "page": 1})

    @patch("trakt2notion.sync.requests.get")
    def test_paid_sync_preserves_default_request(self, request_get):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": "one"}]
        request_get.return_value = response

        history = self.make_sync().fetch_history("episodes")

        self.assertEqual(history, [{"id": "one"}])
        self.assertEqual(request_get.call_args.kwargs["params"], {"limit": 100, "page": 1})

    @patch("trakt2notion.sync.requests.get")
    def test_full_sync_paginates_all_history(self, request_get):
        first = Mock(status_code=200, headers={"X-Pagination-Page-Count": "2"})
        first.json.return_value = [{"id": "one"}]
        second = Mock(status_code=200, headers={"X-Pagination-Page-Count": "2"})
        second.json.return_value = [{"id": "two"}]
        request_get.side_effect = [first, second]
        sync = self.make_sync()
        sync.sync_mode = "full"

        history = sync.fetch_history("movies")

        self.assertEqual(history, [{"id": "one"}, {"id": "two"}])
        self.assertEqual(request_get.call_args_list[0].kwargs["params"], {"limit": 100, "page": 1})
        self.assertEqual(request_get.call_args_list[1].kwargs["params"], {"limit": 100, "page": 2})

    @patch("trakt2notion.sync.requests.get")
    def test_zero_limit_skips_upstream_request(self, request_get):
        self.assertEqual(self.make_sync().fetch_history("movies", max_items=0), [])
        request_get.assert_not_called()

    @patch("trakt2notion.sync.requests.get")
    def test_expired_token_fails_instead_of_reporting_empty_success(self, request_get):
        request_get.return_value = Mock(status_code=401)

        with self.assertRaisesRegex(RuntimeError, "授权已过期"):
            self.make_sync().fetch_history("movies", max_items=50)

    @patch("trakt2notion.sync.requests.get")
    def test_upstream_error_fails_instead_of_returning_partial_history(
        self, request_get
    ):
        request_get.return_value = Mock(status_code=503)

        with self.assertRaisesRegex(RuntimeError, r"HTTP 503"):
            self.make_sync().fetch_history("movies")

    def test_missing_token_fails_instead_of_reporting_empty_success(self):
        sync = self.make_sync()
        sync.trakt_access_token = ""

        with self.assertRaisesRegex(RuntimeError, "缺少 TRAKT_ACCESS_TOKEN"):
            sync.fetch_history("movies")

    def test_full_sync_updates_existing_movie(self):
        sync = self.make_sync()
        sync.sync_mode = "full"
        sync.sync_policy = Mock(is_trial=False)
        sync.fetch_history = Mock(return_value=[{"watched_at": "2026-01-01", "movie": {"title": "电影", "year": 2026, "ids": {"trakt": 1, "tmdb": 2, "slug": "movie"}}}])
        sync.tmdb_helper = Mock()
        sync.tmdb_helper.get_movie_details.return_value = {"rating": 8}
        sync.notion_helper = Mock()
        sync.notion_helper.get_movie_by_trakt_id.return_value = {"id": "page-1"}
        progress = Mock()

        stats = sync.sync_movies(progress=progress)

        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["updated"], 1)
        sync.notion_helper.create_movie.assert_not_called()
        sync.notion_helper.update_movie.assert_called_once()
        sync.sync_policy.record_success.assert_called_once_with(
            "history", "movie:1", occurred_at="2026-01-01", heatmap_type="trakt", created=False
        )

    def test_incremental_sync_skips_existing_movie(self):
        sync = self.make_sync()
        sync.sync_policy = Mock(is_trial=False)
        sync.fetch_history = Mock(return_value=[{"watched_at": "2026-01-01", "movie": {"title": "电影", "year": 2026, "ids": {"trakt": 1, "tmdb": 2, "slug": "movie"}}}])
        sync.tmdb_helper = Mock()
        sync.tmdb_helper.get_movie_details.return_value = {"rating": 8}
        sync.notion_helper = Mock()
        sync.notion_helper.get_movie_by_trakt_id.return_value = {"id": "page-1"}

        stats = sync.sync_movies()

        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["updated"], 0)
        sync.notion_helper.create_movie.assert_not_called()
        sync.notion_helper.update_movie.assert_not_called()


if __name__ == "__main__":
    unittest.main()
