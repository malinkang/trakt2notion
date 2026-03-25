import os
from notionhub.client import NotionHelperBase
from notionhub.utils import get_relation, get_title, get_date, get_rich_text, get_select, get_number, get_url
from notionhub.log import log

class NotionHelper(NotionHelperBase):
    def __init__(self):
        super().__init__()
        self.movie_database_id = os.getenv("MOVIE_DATABASE_ID")
        self.show_database_id = os.getenv("SHOW_DATABASE_ID")
        self.episode_database_id = os.getenv("EPISODE_DATABASE_ID")
        
        # Mapping names to IDs if NOTION_PAGE is provided
        notion_page = os.getenv("NOTION_PAGE")
        if notion_page and not self.movie_database_id:
            self.page_id = self.extract_page_id(notion_page)
            self.search_database(self.page_id)
            self.movie_database_id = self.database_id_dict.get("电影")
            self.show_database_id = self.database_id_dict.get("剧集")
            self.episode_database_id = self.database_id_dict.get("单集")

    def search_database(self, block_id):
        children = self.client.blocks.children.list(block_id=block_id)["results"]
        for child in children:
            if child["type"] == "child_database":
                self.database_id_dict[child.get("child_database").get("title")] = child.get("id")
            if child.get("has_children"):
                self.search_database(child["id"])

    def get_movie_by_trakt_id(self, trakt_id):
        filter_obj = {"property": "Trakt ID", "number": {"equals": trakt_id}}
        response = self.query(database_id=self.movie_database_id, filter=filter_obj)
        return response.get("results")[0] if response.get("results") else None

    def get_show_by_trakt_id(self, trakt_id):
        filter_obj = {"property": "Trakt ID", "number": {"equals": trakt_id}}
        response = self.query(database_id=self.show_database_id, filter=filter_obj)
        return response.get("results")[0] if response.get("results") else None

    def get_episode_by_trakt_id(self, trakt_id):
        filter_obj = {"property": "Trakt ID", "number": {"equals": trakt_id}}
        response = self.query(database_id=self.episode_database_id, filter=filter_obj)
        return response.get("results")[0] if response.get("results") else None

    def create_movie(self, movie_data):
        properties = {
            "标题": get_title(movie_data['title']),
            "Trakt ID": get_number(movie_data['trakt_id']),
            "年份": get_number(movie_data.get('year')),
            "评分": get_number(movie_data.get('rating')),
            "类型": get_select(movie_data.get('genres', [])),
            "上映日期": get_date(movie_data.get('released')),
            "简介": get_rich_text(movie_data.get('overview', '')),
            "Trakt URL": get_url(movie_data.get('url'))
        }
        icon = movie_data.get('poster_url')
        return self.create_page(parent={"database_id": self.movie_database_id}, properties=properties, icon=icon, cover=icon)

    def create_show(self, show_data):
        properties = {
            "标题": get_title(show_data['title']),
            "Trakt ID": get_number(show_data['trakt_id']),
            "年份": get_number(show_data.get('year')),
            "状态": get_select(show_data.get('status')),
            "简介": get_rich_text(show_data.get('overview', '')),
            "Trakt URL": get_url(show_data.get('url'))
        }
        icon = show_data.get('poster_url')
        return self.create_page(parent={"database_id": self.show_database_id}, properties=properties, icon=icon, cover=icon)

    def create_episode(self, episode_data, show_page_id):
        properties = {
            "标题": get_title(episode_data['title']),
            "Trakt ID": get_number(episode_data['trakt_id']),
            "剧集": get_relation([show_page_id]),
            "季": get_number(episode_data.get('season')),
            "集": get_number(episode_data.get('number')),
            "播放日期": get_date(episode_data.get('watched_at')),
            "简介": get_rich_text(episode_data.get('overview', ''))
        }
        icon = episode_data.get('still_url')
        return self.create_page(parent={"database_id": self.episode_database_id}, properties=properties, icon=icon, cover=icon)
