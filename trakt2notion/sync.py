import json
import os
import sys

import requests
from notionhub.log import log, sync_notification
from notionhub.sync_policy import current_sync_policy
from trakt2notion.notion_helper import NotionHelper
from trakt2notion.tmdb_helper import TMDBHelper


DEFAULT_TRAKT_CLIENT_ID = "95e9b98a7a84ddda7e4a47f909162a68293234c15ec96a0887ce9a6688e6f032"


class TraktSync:
    def __init__(self, config=None):
        config = config or {}
        self.trakt_client_id = self._get_config_value(config, "TRAKT_CLIENT_ID", "trakt_client_id") or os.getenv(
            "TRAKT_CLIENT_ID"
        ) or DEFAULT_TRAKT_CLIENT_ID
        self.tmdb_api_key = self._get_config_value(config, "TMDB_API_KEY", "tmdb_api_key") or os.getenv("TMDB_API_KEY")
        self.tmdb_access_token = self._get_config_value(config, "TMDB_ACCESS_TOKEN", "tmdb_access_token") or os.getenv(
            "TMDB_ACCESS_TOKEN"
        )
        self.trakt_access_token = self._get_access_token(config) or os.getenv("TRAKT_ACCESS_TOKEN")
        self.sync_policy = current_sync_policy()
        self.sync_mode = (os.getenv("SYNC_MODE") or "incremental").strip().lower()

        self._setup_notion_env(config.get("notion") or {})

        self.notion_helper = NotionHelper()
        self.tmdb_helper = TMDBHelper(api_key=self.tmdb_api_key, access_token=self.tmdb_access_token)
        self.headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.trakt_client_id,
        }
        if self.trakt_access_token:
            self.headers["Authorization"] = f"Bearer {self.trakt_access_token}"

    @staticmethod
    def _get_config_value(config, *keys):
        for key in keys:
            value = config.get(key)
            if value:
                return value
        return None

    @staticmethod
    def _set_env_if_value(name, value):
        if value is not None:
            os.environ[name] = str(value)

    def _setup_notion_env(self, notion_config):
        self._set_env_if_value("NOTION_TOKEN", notion_config.get("access_token") or notion_config.get("token"))
        self._set_env_if_value("MOVIE_DATABASE_ID", notion_config.get("movie_database_id"))
        self._set_env_if_value("SHOW_DATABASE_ID", notion_config.get("show_database_id"))
        self._set_env_if_value("EPISODE_DATABASE_ID", notion_config.get("episode_database_id"))
        self._set_env_if_value("MOVIE_DATA_SOURCE_ID", notion_config.get("movie_data_source_id"))
        self._set_env_if_value("SHOW_DATA_SOURCE_ID", notion_config.get("show_data_source_id"))
        self._set_env_if_value("EPISODE_DATA_SOURCE_ID", notion_config.get("episode_data_source_id"))
        self._set_env_if_value("NOTION_PAGE", notion_config.get("duplicated_template_id") or notion_config.get("page_id"))

    def _get_access_token(self, config):
        token_data = config.get("token") or config.get("trakt") or {}
        if isinstance(token_data, str):
            try:
                token_data = json.loads(token_data)
            except Exception:
                return token_data
        if isinstance(token_data, dict):
            token = (
                token_data.get("access_token")
                or token_data.get("accessToken")
                or token_data.get("TRAKT_ACCESS_TOKEN")
                or token_data.get("trakt_access_token")
            )
            if token:
                return token
        return self._get_config_value(config, "TRAKT_ACCESS_TOKEN", "trakt_access_token", "access_token", "accessToken")

    @staticmethod
    def _trakt_url(kind, slug):
        if not slug:
            return None
        return f"https://trakt.tv/{kind}/{slug}"

    @classmethod
    def _episode_url(cls, show_slug, season, number):
        show_url = cls._trakt_url("shows", show_slug)
        if not show_url or season is None or number is None:
            return None
        return f"{show_url}/seasons/{season}/episodes/{number}"

    def is_full_sync(self):
        return self.sync_mode == "full"

    def fetch_history(self, type="movies", max_items=None):
        if not self.trakt_access_token:
            raise RuntimeError("缺少 TRAKT_ACCESS_TOKEN，请重新连接 Trakt 后再同步。")
        if max_items is not None and max_items <= 0:
            return []
        url = f"https://api.trakt.tv/users/me/history/{type}"
        per_page = min(100, max_items) if max_items is not None else 100
        should_paginate = self.is_full_sync() and max_items is None
        history = []
        page = 1
        page_count = 1
        log(f"读取 Trakt {type} 历史：模式={'全量同步' if should_paginate else '增量同步'}")
        while page <= page_count:
            params = {"limit": per_page, "page": page}
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            if response.status_code == 200:
                items = response.json() or []
                history.extend(items)
                if max_items is not None and len(history) >= max_items:
                    return history[:max_items]
                if not should_paginate:
                    return history
                page_count = int(response.headers.get("X-Pagination-Page-Count") or page)
                log(f"Trakt {type} 历史读取进度：第 {page}/{page_count} 页，累计 {len(history)} 条")
                if not items:
                    break
                page += 1
                continue
            if response.status_code in (401, 403):
                raise RuntimeError("Trakt 授权已过期，请重新授权后再同步。")
            raise RuntimeError(
                f"读取 Trakt {type} 历史失败: HTTP {response.status_code}"
            )
        return history

    def sync_movies(self, progress=None):
        trial_fetch_limit = None
        if self.sync_policy.is_trial:
            trial_fetch_limit = self.sync_policy.remaining("history") * 2
        movies = self.fetch_history("movies", max_items=trial_fetch_limit)
        created_movies = 0
        updated_movies = 0
        for item in movies:
            if self.sync_policy.is_trial and self.sync_policy.remaining("history") <= 0:
                break
            movie = item.get("movie") or {}
            ids = movie.get("ids") or {}
            trakt_id = ids.get("trakt")
            tmdb_id = ids.get("tmdb")
            movie_url = self._trakt_url("movies", ids.get("slug"))
            if not trakt_id and not movie_url:
                continue
            item_id = f"movie:{trakt_id or movie_url}"

            existing_movie = self.notion_helper.get_movie_by_trakt_id(trakt_id, movie_url)
            movie_data = {
                "title": movie.get("title"),
                "trakt_id": trakt_id,
                "year": movie.get("year"),
                "watched_at": item.get("watched_at"),
                "url": movie_url,
            }
            tmdb_details = self.tmdb_helper.get_movie_details(tmdb_id)
            if tmdb_details:
                movie_data.update(tmdb_details)
            if not existing_movie:
                if not self.sync_policy.can_create("history", item_id):
                    continue
                log(f"正在新增 Trakt 电影: {movie.get('title')}")
                page = self.notion_helper.create_movie(movie_data)
                created_movies += 1
                self.sync_policy.record_success(
                    "history", item_id, occurred_at=item.get("watched_at"), created=True
                )
                if progress:
                    progress.add(movie.get("title"), page_id=page.get("id"), status="已新增电影")
            elif self.is_full_sync():
                log(f"正在更新 Trakt 电影: {movie.get('title')}")
                self.notion_helper.update_movie(existing_movie.get("id"), movie_data)
                updated_movies += 1
                self.sync_policy.record_success(
                    "history", item_id, occurred_at=item.get("watched_at"), created=False
                )
                if progress:
                    progress.add(movie.get("title"), page_id=existing_movie.get("id"), status="已更新电影")
            else:
                log(f"Trakt 电影已存在: {movie.get('title')}")
        return {
            "total": len(movies),
            "created": created_movies,
            "updated": updated_movies,
        }

    def sync_shows(self, progress=None):
        trial_fetch_limit = None
        if self.sync_policy.is_trial:
            trial_fetch_limit = self.sync_policy.remaining("history") * 2
        episodes = self.fetch_history("episodes", max_items=trial_fetch_limit)
        created_shows = 0
        created_episodes = 0
        updated_shows = 0
        updated_episodes = 0
        for item in episodes:
            if self.sync_policy.is_trial and self.sync_policy.remaining("history") <= 0:
                break
            show = item.get("show") or {}
            episode = item.get("episode") or {}
            show_ids = show.get("ids") or {}
            episode_ids = episode.get("ids") or {}
            show_trakt_id = show_ids.get("trakt")
            show_tmdb_id = show_ids.get("tmdb")
            episode_trakt_id = episode_ids.get("trakt")
            show_url = self._trakt_url("shows", show_ids.get("slug"))
            episode_url = self._episode_url(show_ids.get("slug"), episode.get("season"), episode.get("number"))

            if (not show_trakt_id and not show_url) or (not episode_trakt_id and not episode_url):
                continue
            item_id = f"episode:{episode_trakt_id or episode_url}"

            existing_episode = self.notion_helper.get_episode_by_trakt_id(episode_trakt_id, episode_url)
            if existing_episode and not self.is_full_sync():
                continue
            if not existing_episode and not self.sync_policy.can_create("history", item_id):
                break

            show_page = self.notion_helper.get_show_by_trakt_id(show_trakt_id, show_url)
            show_data = {
                "title": show.get("title"),
                "trakt_id": show_trakt_id,
                "year": show.get("year"),
                "url": show_url,
            }
            tmdb_show_details = self.tmdb_helper.get_show_details(show_tmdb_id)
            if tmdb_show_details:
                show_data.update(tmdb_show_details)
            if not show_page:
                log(f"正在新增 Trakt 剧集: {show.get('title')}")
                show_page = self.notion_helper.create_show(show_data)
                created_shows += 1
                if progress:
                    progress.add(show.get("title"), page_id=show_page.get("id"), status="已新增剧集")
            elif self.is_full_sync():
                log(f"正在更新 Trakt 剧集: {show.get('title')}")
                self.notion_helper.update_show(show_page.get("id"), show_data)
                updated_shows += 1
                if progress:
                    progress.add(show.get("title"), page_id=show_page.get("id"), status="已更新剧集")

            show_page_id = show_page.get("id") if isinstance(show_page, dict) else show_page

            action = "更新" if existing_episode else "新增"
            log(f"正在{action} Trakt 单集: {show.get('title')} S{episode.get('season')}E{episode.get('number')}")
            episode_data = {
                "title": episode.get("title"),
                "trakt_id": episode_trakt_id,
                "season": episode.get("season"),
                "number": episode.get("number"),
                "watched_at": item.get("watched_at"),
                "url": episode_url,
            }
            tmdb_episode_details = self.tmdb_helper.get_episode_details(
                show_tmdb_id, episode.get("season"), episode.get("number")
            )
            if tmdb_episode_details:
                episode_data.update(tmdb_episode_details)

            if existing_episode:
                episode_page = self.notion_helper.update_episode(existing_episode.get("id"), episode_data, show_page_id)
                updated_episodes += 1
            else:
                episode_page = self.notion_helper.create_episode(episode_data, show_page_id)
                created_episodes += 1
            self.sync_policy.record_success(
                "history", item_id, occurred_at=item.get("watched_at"), created=not bool(existing_episode)
            )
            if progress:
                progress.add(
                    f"{show.get('title')} S{episode.get('season')}E{episode.get('number')}",
                    page_id=episode_page.get("id") if isinstance(episode_page, dict) else existing_episode.get("id"),
                    status="已更新单集" if existing_episode else "已新增单集",
                )
        return {
            "total": len(episodes),
            "shows_created": created_shows,
            "shows_updated": updated_shows,
            "episodes_created": created_episodes,
            "episodes_updated": updated_episodes,
        }

    def run(self, progress=None):
        log(f"开始同步 Trakt，当前模式：{'全量同步' if self.is_full_sync() else '增量同步'}。")
        movie_stats = self.sync_movies(progress=progress)
        show_stats = self.sync_shows(progress=progress)
        if progress:
            progress.flush()
        log("Trakt 同步完成。")
        return {
            "movies": movie_stats,
            "shows": show_stats,
        }


if __name__ == "__main__":
    config = None
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
        except Exception:
            pass
    with sync_notification("Trakt") as notification:
        sync = TraktSync(config)
        progress = notification.progress("同步", batch_size=10)
        stats = sync.run(progress=progress)
        sync.sync_policy.write_report(status="success")
        notification.set_summary(
            "同步了 {movies} 条电影历史，新增 {new_movies} 部电影，更新 {updated_movies} 部电影；"
            "同步了 {episodes} 条剧集历史，新增 {new_shows} 部剧集，更新 {updated_shows} 部剧集，"
            "新增 {new_episodes} 集，更新 {updated_episodes} 集".format(
                movies=stats["movies"]["total"],
                new_movies=stats["movies"]["created"],
                updated_movies=stats["movies"].get("updated", 0),
                episodes=stats["shows"]["total"],
                new_shows=stats["shows"]["shows_created"],
                updated_shows=stats["shows"].get("shows_updated", 0),
                new_episodes=stats["shows"]["episodes_created"],
                updated_episodes=stats["shows"].get("episodes_updated", 0),
            )
        )
