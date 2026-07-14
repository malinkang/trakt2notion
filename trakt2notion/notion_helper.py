import os

from notionhub.client import NotionHelperBase
from notionhub.utils import (
    get_date,
    get_multi_select,
    get_number,
    get_relation,
    get_rich_text,
    get_select,
    get_title,
    get_url,
)
from notionhub.log import log
from notionhub.sync_policy import current_sync_policy


class NotionHelper(NotionHelperBase):
    def __init__(self):
        super().__init__()
        self.movie_database_id, self.movie_data_source_id = self._resolve_ids("MOVIE")
        self.show_database_id, self.show_data_source_id = self._resolve_ids("SHOW")
        self.episode_database_id, self.episode_data_source_id = self._resolve_ids("EPISODE")
        self._property_types = {}
        self._image_cache = {}
        self.upload_to_notion = current_sync_policy().allows("media") and str(
            os.getenv("UPLOAD_TO_NOTION", "false")
        ).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        # Mapping names to IDs if NOTION_PAGE is provided
        notion_page = os.getenv("NOTION_PAGE")
        if notion_page and not self.movie_database_id:
            self.page_id = self.extract_page_id(notion_page)
            self.search_database(self.page_id)
            self.movie_database_id = self.database_id_dict.get("电影")
            self.show_database_id = self.database_id_dict.get("剧集")
            self.episode_database_id = self.database_id_dict.get("单集")
            self.movie_data_source_id = self._database_to_data_source(self.movie_database_id)
            self.show_data_source_id = self._database_to_data_source(self.show_database_id)
            self.episode_data_source_id = self._database_to_data_source(self.episode_database_id)

    def _database_to_data_source(self, database_id):
        if not database_id:
            return None
        try:
            return self.resolve_data_source_id(database_id)
        except Exception:
            return None

    def _data_source_to_database(self, data_source_id):
        if not data_source_id:
            return None
        try:
            return self.resolve_database_id(data_source_id)
        except Exception:
            return None

    def _resolve_ids(self, prefix):
        database_id = self.get_optional_env_value(f"{prefix}_DATABASE_ID")
        data_source_id = self.get_optional_env_value(f"{prefix}_DATA_SOURCE_ID")
        if data_source_id:
            return self._data_source_to_database(data_source_id), data_source_id
        if database_id:
            data_source_id = self._database_to_data_source(database_id)
            if data_source_id:
                return database_id, data_source_id
            # Some older callers pass a data_source_id through *_DATABASE_ID.
            return self._data_source_to_database(database_id), database_id
        return None, None

    def search_database(self, block_id):
        children = self.client.blocks.children.list(block_id=block_id)["results"]
        for child in children:
            if child["type"] == "child_database":
                self.database_id_dict[child.get("child_database").get("title")] = child.get("id")
            if child.get("has_children"):
                self.search_database(child["id"])

    def _get_property_types(self, data_source_id, database_id=None):
        target_id = data_source_id or database_id
        if not target_id:
            return {}
        if target_id not in self._property_types:
            try:
                if data_source_id:
                    db = self.retrieve_data_source(data_source_id)
                else:
                    db = self.retrieve_database(database_id)
                    if not (db.get("properties") or {}):
                        fallback_data_source_id = (db.get("data_sources") or [{}])[0].get("id")
                        if fallback_data_source_id:
                            db = self.retrieve_data_source(fallback_data_source_id)
                self._property_types[target_id] = {
                    name: prop.get("type")
                    for name, prop in (db.get("properties") or {}).items()
                    if isinstance(prop, dict) and prop.get("type")
                }
            except Exception as exc:
                log(f"读取 Trakt Notion 数据库属性失败: {target_id} {exc}")
                self._property_types[target_id] = {}
        return self._property_types[target_id]

    def _build_properties(self, data_source_id, database_id, raw):
        types = self._get_property_types(data_source_id, database_id)
        if "标题" in (raw or {}) and "标题" not in types:
            title_prop = next((name for name, prop_type in types.items() if prop_type == "title"), None)
            if title_prop and title_prop not in raw:
                raw = {**raw, title_prop: raw.get("标题")}
        properties = {}
        for name, value in (raw or {}).items():
            if name not in types:
                continue
            prop_type = types[name]
            if value is None or value == "":
                continue
            if prop_type == "title":
                properties[name] = get_title(str(value))
            elif prop_type == "rich_text":
                properties[name] = get_rich_text(str(value))
            elif prop_type == "url":
                properties[name] = get_url(str(value))
            elif prop_type == "number":
                try:
                    properties[name] = get_number(int(value) if float(value).is_integer() else float(value))
                except Exception:
                    continue
            elif prop_type == "date":
                properties[name] = get_date(str(value))
            elif prop_type == "select":
                selected = value[0] if isinstance(value, list) and value else value
                if selected:
                    properties[name] = get_select(str(selected))
            elif prop_type == "status":
                properties[name] = {"status": {"name": str(value)}}
            elif prop_type == "multi_select":
                values = value if isinstance(value, list) else [value]
                names = [str(item) for item in values if item]
                if names:
                    properties[name] = get_multi_select(names)
            elif prop_type == "relation":
                values = value if isinstance(value, list) else [value]
                ids = [item for item in values if item]
                if ids:
                    properties[name] = get_relation(ids)
        return properties

    def _prepare_image_url(self, url):
        if not url:
            return url
        if not self.upload_to_notion:
            return url
        if url in self._image_cache:
            return self._image_cache[url]
        try:
            from movie2notion.utils import upload_cover

            uploaded_url = upload_cover(url)
            if uploaded_url:
                self._image_cache[url] = uploaded_url
                return uploaded_url
        except Exception as exc:
            log(f"Trakt 封面转存失败，使用原图链接: {exc}")
        return url

    def _query_first(self, data_source_id, database_id, filter_obj):
        if not (data_source_id or database_id) or not filter_obj:
            return None
        try:
            kwargs = {"filter": filter_obj}
            if data_source_id:
                kwargs["data_source_id"] = data_source_id
            else:
                kwargs["database_id"] = database_id
            response = self.query(**kwargs)
            return response.get("results")[0] if response.get("results") else None
        except Exception as exc:
            log(f"查询 Trakt Notion 页面失败，已跳过该条件: {exc}")
            return None

    def _url_property_names(self, data_source_id, database_id):
        types = self._get_property_types(data_source_id, database_id)
        return [name for name in ("Trakt URL", "Trakt") if types.get(name) == "url"]

    def _get_by_trakt_identity(self, data_source_id, database_id, trakt_id=None, trakt_url=None):
        if trakt_url:
            for property_name in self._url_property_names(data_source_id, database_id):
                page = self._query_first(
                    data_source_id,
                    database_id,
                    {"property": property_name, "url": {"equals": trakt_url}},
                )
                if page:
                    return page
        if trakt_id is not None:
            return self._query_first(
                data_source_id,
                database_id,
                {"property": "Trakt ID", "number": {"equals": trakt_id}},
            )
        return None

    @staticmethod
    def _parent(data_source_id, database_id):
        if data_source_id:
            return {"type": "data_source_id", "data_source_id": data_source_id}
        return {"database_id": database_id}

    def get_movie_by_trakt_id(self, trakt_id, trakt_url=None):
        return self._get_by_trakt_identity(
            self.movie_data_source_id, self.movie_database_id, trakt_id, trakt_url
        )

    def get_show_by_trakt_id(self, trakt_id, trakt_url=None):
        return self._get_by_trakt_identity(
            self.show_data_source_id, self.show_database_id, trakt_id, trakt_url
        )

    def get_episode_by_trakt_id(self, trakt_id, trakt_url=None):
        return self._get_by_trakt_identity(
            self.episode_data_source_id, self.episode_database_id, trakt_id, trakt_url
        )

    def create_movie(self, movie_data):
        raw = {
            "标题": movie_data.get("title"),
            "Trakt ID": movie_data.get("trakt_id"),
            "年份": movie_data.get("year"),
            "评分": movie_data.get("rating"),
            "类型": movie_data.get("genres"),
            "上映日期": movie_data.get("release_date") or movie_data.get("released"),
            "片长": movie_data.get("runtime"),
            "简介": movie_data.get("overview"),
            "Trakt URL": movie_data.get("url"),
            "TMDB": movie_data.get("tmdb_url"),
            "原名": movie_data.get("original_title"),
        }
        properties = self._build_properties(self.movie_data_source_id, self.movie_database_id, raw)
        icon = self._prepare_image_url(movie_data.get("poster_url"))
        return self.create_page(
            parent=self._parent(self.movie_data_source_id, self.movie_database_id),
            properties=properties,
            icon=icon,
            cover=icon,
        )

    def create_show(self, show_data):
        raw = {
            "标题": show_data.get("title"),
            "Trakt ID": show_data.get("trakt_id"),
            "年份": show_data.get("year"),
            "状态": show_data.get("status"),
            "类型": show_data.get("genres"),
            "首播日期": show_data.get("first_air_date"),
            "简介": show_data.get("overview"),
            "Trakt URL": show_data.get("url"),
            "TMDB": show_data.get("tmdb_url"),
            "原名": show_data.get("original_title"),
        }
        properties = self._build_properties(self.show_data_source_id, self.show_database_id, raw)
        icon = self._prepare_image_url(show_data.get("poster_url"))
        return self.create_page(
            parent=self._parent(self.show_data_source_id, self.show_database_id),
            properties=properties,
            icon=icon,
            cover=icon,
        )

    def create_episode(self, episode_data, show_page_id):
        raw = {
            "标题": episode_data.get("title"),
            "剧集": [show_page_id],
            "影视": [show_page_id],
            "季": episode_data.get("season"),
            "集": episode_data.get("number"),
            "播放日期": episode_data.get("watched_at"),
            "片长": episode_data.get("runtime"),
            "简介": episode_data.get("overview"),
            "Trakt URL": episode_data.get("url"),
            "Trakt": episode_data.get("url"),
            "TMDB": episode_data.get("tmdb_url"),
        }
        properties = self._build_properties(self.episode_data_source_id, self.episode_database_id, raw)
        icon = self._prepare_image_url(
            episode_data.get("still_url")
            or episode_data.get("show_poster_url")
            or episode_data.get("poster_url")
        )
        return self.create_page(
            parent=self._parent(self.episode_data_source_id, self.episode_database_id),
            properties=properties,
            icon=icon,
            cover=icon,
        )
