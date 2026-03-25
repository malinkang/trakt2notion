import requests
import os
from notionhub.log import log

class TMDBHelper:
    def __init__(self, api_key=None, access_token=None):
        self.api_key = api_key or os.getenv("TMDB_API_KEY")
        self.access_token = access_token or os.getenv("TMDB_ACCESS_TOKEN")
        self.base_url = "https://api.themoviedb.org/3"
        self.language = "zh-CN"

    def _get_headers(self):
        headers = {
            "Content-Type": "application/json;charset=utf-8"
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _get_params(self):
        params = {
            "language": self.language
        }
        if self.api_key and not self.access_token:
            params["api_key"] = self.api_key
        return params

    def get_movie_details(self, tmdb_id):
        if not tmdb_id:
            return None
        url = f"{self.base_url}/movie/{tmdb_id}"
        try:
            response = requests.get(url, params=self._get_params(), headers=self._get_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "title": data.get("title"),
                    "overview": data.get("overview"),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else None,
                    "genres": [g.get("name") for g in data.get("genres", [])],
                    "released": data.get("release_date")
                }
            return None
        except Exception as e:
            log(f"Error fetching TMDB movie details: {e}")
            return None

    def get_show_details(self, tmdb_id):
        if not tmdb_id:
            return None
        url = f"{self.base_url}/tv/{tmdb_id}"
        try:
            response = requests.get(url, params=self._get_params(), headers=self._get_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "title": data.get("name"),
                    "overview": data.get("overview"),
                    "poster_url": f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else None,
                    "genres": [g.get("name") for g in data.get("genres", [])],
                    "status": data.get("status")
                }
            return None
        except Exception as e:
            log(f"Error fetching TMDB show details: {e}")
            return None

    def get_episode_details(self, show_tmdb_id, season_number, episode_number):
        if not show_tmdb_id:
            return None
        url = f"{self.base_url}/tv/{show_tmdb_id}/season/{season_number}/episode/{episode_number}"
        try:
            response = requests.get(url, params=self._get_params(), headers=self._get_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "title": data.get("name"),
                    "overview": data.get("overview"),
                    "still_url": f"https://image.tmdb.org/t/p/w500{data.get('still_path')}" if data.get('still_path') else None,
                    "air_date": data.get("air_date")
                }
            return None
        except Exception as e:
            log(f"Error fetching TMDB episode details: {e}")
            return None
