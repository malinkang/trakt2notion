import os
from functools import lru_cache

import requests
from notionhub.log import log


class TMDBHelper:
    """Small TMDb client used only as metadata enrichment for Trakt items."""

    def __init__(self, api_key=None, access_token=None):
        self.api_key = api_key or os.getenv("TMDB_API_KEY")
        self.access_token = access_token or os.getenv("TMDB_ACCESS_TOKEN")
        self.base_url = os.getenv("TMDB_API", "https://api.themoviedb.org/3").rstrip("/")
        self.language = os.getenv("TMDB_LANG", "zh-CN")
        self.image_base = os.getenv("TMDB_IMAGE_BASE", "https://image.tmdb.org/t/p/original").rstrip("/")

    def _enabled(self):
        return bool(self.api_key or self.access_token)

    def _image_url(self, path):
        if not path:
            return None
        return f"{self.image_base}/{str(path).lstrip('/')}"

    def _get_headers(self):
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _get_params(self):
        params = {"language": self.language}
        if self.api_key and not self.access_token:
            params["api_key"] = self.api_key
        return params

    def _get_json(self, path, params=None, timeout=20):
        if not self._enabled():
            return None
        merged_params = self._get_params()
        if params:
            merged_params.update(params)
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                params=merged_params,
                headers=self._get_headers(),
                timeout=timeout,
            )
            if response.status_code == 404:
                return None
            if not response.ok:
                log(f"TMDb 请求失败: path={path} status={response.status_code}")
                return None
            return response.json() or {}
        except Exception as exc:
            log(f"TMDb 请求异常: path={path} error={exc}")
            return None

    @lru_cache(maxsize=512)
    def get_movie_details(self, tmdb_id):
        if not tmdb_id:
            return None
        data = self._get_json(f"/movie/{int(tmdb_id)}")
        if not data:
            return None
        return {
            "title": data.get("title") or data.get("original_title"),
            "original_title": data.get("original_title"),
            "overview": data.get("overview"),
            "poster_url": self._image_url(data.get("poster_path")),
            "genres": [g.get("name") for g in data.get("genres", []) if g.get("name")],
            "runtime": data.get("runtime"),
            "release_date": data.get("release_date"),
            # Backward-compatible key used by the existing sync code.
            "released": data.get("release_date"),
            "tmdb_url": f"https://www.themoviedb.org/movie/{data.get('id') or tmdb_id}",
        }

    @lru_cache(maxsize=512)
    def get_show_details(self, tmdb_id):
        if not tmdb_id:
            return None
        data = self._get_json(f"/tv/{int(tmdb_id)}")
        if not data:
            return None
        return {
            "title": data.get("name") or data.get("original_name"),
            "original_title": data.get("original_name"),
            "overview": data.get("overview"),
            "poster_url": self._image_url(data.get("poster_path")),
            "genres": [g.get("name") for g in data.get("genres", []) if g.get("name")],
            "status": data.get("status"),
            "first_air_date": data.get("first_air_date"),
            "tmdb_url": f"https://www.themoviedb.org/tv/{data.get('id') or tmdb_id}",
        }

    @lru_cache(maxsize=1024)
    def get_episode_details(self, show_tmdb_id, season_number, episode_number):
        if not show_tmdb_id or season_number is None or episode_number is None:
            return None
        data = self._get_json(
            f"/tv/{int(show_tmdb_id)}/season/{int(season_number)}/episode/{int(episode_number)}"
        )
        if not data:
            return None
        runtime = data.get("runtime")
        if runtime is None and os.getenv("TMDB_DEFAULT_EPISODE_RUNTIME"):
            try:
                runtime = int(os.getenv("TMDB_DEFAULT_EPISODE_RUNTIME"))
            except Exception:
                runtime = None
        return {
            "title": data.get("name") or os.getenv("TMDB_DEFAULT_EPISODE_TITLE"),
            "overview": data.get("overview") or os.getenv("TMDB_DEFAULT_EPISODE_OVERVIEW"),
            "still_url": self._image_url(data.get("still_path")) or os.getenv("TMDB_DEFAULT_EPISODE_STILL_URL"),
            "runtime": runtime,
            "air_date": data.get("air_date"),
            "tmdb_url": (
                f"https://www.themoviedb.org/tv/{show_tmdb_id}/season/{season_number}/episode/{episode_number}"
            ),
        }
