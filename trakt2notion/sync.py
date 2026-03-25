import os
import sys
import json
import requests
from trakt2notion.notion_helper import NotionHelper
from trakt2notion.tmdb_helper import TMDBHelper
from notionhub.log import log

class TraktSync:
    def __init__(self, config=None):
        if config:
            self.trakt_client_id = config.get("TRAKT_CLIENT_ID", "95e9b98a7a84ddda7e4a47f909162a68293234c15ec96a0887ce9a6688e6f032")
            self.tmdb_api_key = config.get("TMDB_API_KEY")
            self.tmdb_access_token = config.get("TMDB_ACCESS_TOKEN")
            token_data = config.get("token")
            # ... existing token logic ...
            if isinstance(token_data, str):
                try:
                    token_data = json.loads(token_data)
                except:
                    pass
            
            if isinstance(token_data, dict):
                self.trakt_access_token = token_data.get("accessToken")
            else:
                self.trakt_access_token = os.getenv("TRAKT_ACCESS_TOKEN")
            
            # Setup notion env for notion_helper
            notion_config = config.get("notion", {})
            os.environ["NOTION_TOKEN"] = notion_config.get("access_token", "")
            os.environ["MOVIE_DATABASE_ID"] = notion_config.get("movie_database_id", "")
            os.environ["SHOW_DATABASE_ID"] = notion_config.get("show_database_id", "")
            os.environ["EPISODE_DATABASE_ID"] = notion_config.get("episode_database_id", "")
        else:
            self.trakt_client_id = os.getenv("TRAKT_CLIENT_ID")
            self.trakt_access_token = os.getenv("TRAKT_ACCESS_TOKEN")
            self.tmdb_api_key = os.getenv("TMDB_API_KEY")
            self.tmdb_access_token = os.getenv("TMDB_ACCESS_TOKEN")
            
        self.notion_helper = NotionHelper()
        self.tmdb_helper = TMDBHelper(api_key=self.tmdb_api_key, access_token=self.tmdb_access_token)
        self.headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': self.trakt_client_id,
            'Authorization': f'Bearer {self.trakt_access_token}'
        }

    def fetch_history(self, type='movies'):
        url = f'https://api.trakt.tv/users/me/history/{type}'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            return response.json()
        else:
            log(f"Failed to fetch {type} history: {response.status_code}")
            return []

    def sync_movies(self):
        movies = self.fetch_history('movies')
        for item in movies:
            movie = item.get('movie')
            trakt_id = movie.get('ids', {}).get('trakt')
            tmdb_id = movie.get('ids', {}).get('tmdb')
            if not trakt_id:
                continue
            
            existing_movie = self.notion_helper.get_movie_by_trakt_id(trakt_id)
            if not existing_movie:
                log(f"Creating movie: {movie.get('title')}")
                movie_data = {
                    'title': movie.get('title'),
                    'trakt_id': trakt_id,
                    'year': movie.get('year'),
                    'watched_at': item.get('watched_at'),
                    'url': f"https://trakt.tv/movies/{movie.get('ids', {}).get('slug')}"
                }
                
                # Fetch Chinese details from TMDB
                tmdb_details = self.tmdb_helper.get_movie_details(tmdb_id)
                if tmdb_details:
                    movie_data.update(tmdb_details)
                
                self.notion_helper.create_movie(movie_data)
            else:
                log(f"Movie already exists: {movie.get('title')}")

    def sync_shows(self):
        episodes = self.fetch_history('episodes')
        for item in episodes:
            show = item.get('show')
            episode = item.get('episode')
            show_trakt_id = show.get('ids', {}).get('trakt')
            show_tmdb_id = show.get('ids', {}).get('tmdb')
            episode_trakt_id = episode.get('ids', {}).get('trakt')
            
            if not show_trakt_id or not episode_trakt_id:
                continue
            
            # Ensure show exists
            show_page = self.notion_helper.get_show_by_trakt_id(show_trakt_id)
            if not show_page:
                log(f"Creating show: {show.get('title')}")
                show_data = {
                    'title': show.get('title'),
                    'trakt_id': show_trakt_id,
                    'year': show.get('year'),
                    'url': f"https://trakt.tv/shows/{show.get('ids', {}).get('slug')}"
                }
                # Fetch Chinese show details
                tmdb_show_details = self.tmdb_helper.get_show_details(show_tmdb_id)
                if tmdb_show_details:
                    show_data.update(tmdb_show_details)
                show_page = self.notion_helper.create_show(show_data)
            
            show_page_id = show_page.get('id') if isinstance(show_page, dict) else show_page
            
            # Ensure episode exists
            existing_episode = self.notion_helper.get_episode_by_trakt_id(episode_trakt_id)
            if not existing_episode:
                log(f"Creating episode: {show.get('title')} S{episode.get('season')}E{episode.get('number')}")
                episode_data = {
                    'title': episode.get('title'),
                    'trakt_id': episode_trakt_id,
                    'season': episode.get('season'),
                    'number': episode.get('number'),
                    'watched_at': item.get('watched_at')
                }
                # Fetch Chinese episode details
                tmdb_episode_details = self.tmdb_helper.get_episode_details(show_tmdb_id, episode.get('season'), episode.get('number'))
                if tmdb_episode_details:
                    episode_data.update(tmdb_episode_details)
                
                self.notion_helper.create_episode(episode_data, show_page_id)

    def run(self):
        log("Starting Trakt sync...")
        self.sync_movies()
        self.sync_shows()
        log("Trakt sync finished.")

if __name__ == '__main__':
    config = None
    if len(sys.argv) > 1:
        try:
            config = json.loads(sys.argv[1])
        except:
            pass
    sync = TraktSync(config)
    sync.run()
