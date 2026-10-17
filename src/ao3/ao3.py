import re
from collections.abc import Iterable, Mapping
from functools import cache, cached_property
from typing import Any, Literal, overload

import httpx2
from bs4 import BeautifulSoup
from bs4.element import Tag as Element

from ao3.bookmark import Bookmark
from ao3.collection import Collection
from ao3.comment import Comment
from ao3.exceptions import (
    AO3ActionError,
    AO3AuthenticationError,
    AO3CSRFError,
    AO3ParseError,
)
from ao3.external_work import ExternalWork
from ao3.language import Language
from ao3.media import Media
from ao3.pseud import Pseud
from ao3.series import Series
from ao3.subscription import Subscription
from ao3.tag import Tag
from ao3.user import User
from ao3.work import Chapter, Kudos, Work


class AO3Client:
    """HTTPX2 connection pool and AO3 page-loading operations."""

    @classmethod
    @cache
    def _default(cls) -> "AO3Client":
        return cls()

    def __init__(
        self,
        *,
        base_url: str = "https://archiveofourown.org",
        cookies: Mapping[str, str] | httpx2.Cookies | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx2.Timeout = 30,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        request_headers = httpx2.Headers(
            {
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/153.0.0.0 Safari/537.36"
                ),
            }
        )
        request_headers.update(headers or {})
        self.http = httpx2.Client(
            base_url=base_url,
            cookies=cookies,
            follow_redirects=True,
            headers=request_headers,
            http2=True,
            timeout=timeout,
            transport=transport,
        )

    @property
    def base_url(self) -> str:
        return str(self.http.base_url).rstrip("/")

    @base_url.setter
    def base_url(self, value: str) -> None:
        self.http.base_url = value

    def get(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self._check_response(self.http.get(url, **kwargs))

    def post(self, url: str, **kwargs: Any) -> httpx2.Response:
        return self._check_response(self.http.post(url, **kwargs))

    @staticmethod
    def _check_response(
        response: httpx2.Response, *, login_page: bool = False
    ) -> httpx2.Response:
        if response.url.path.rstrip("/") == "/auth_error":
            raise AO3CSRFError("AO3 rejected the form's authenticity token")

        if response.status_code == 422:
            try:
                payload = response.json()
            except ValueError:
                payload = None

            if (
                isinstance(payload, dict)
                and isinstance(errors := payload.get("errors"), dict)
                and "auth_error" in errors
            ):
                raise AO3CSRFError("AO3 rejected the form's authenticity token")

            if (
                isinstance(payload, dict)
                and isinstance(errors := payload.get("errors"), list)
                and errors
                and all(isinstance(error, str) for error in errors)
            ):
                raise AO3ActionError(" ".join(errors))

        response.raise_for_status()

        if not login_page and response.url.path.rstrip("/") == "/users/login":
            raise AO3AuthenticationError("This AO3 resource requires a login")

        return response

    def _csrf_token(self) -> str:
        response = self.get(
            "/token_dispenser.json",
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise AO3ParseError("AO3 did not return an authenticity token") from error

        if (
            not isinstance(payload, dict)
            or not isinstance(token := payload.get("token"), str)
            or not token.strip()
        ):
            raise AO3ParseError("AO3 did not return an authenticity token")

        return token

    def _same_origin(self, url: httpx2.URL) -> bool:
        origin = self.http.base_url
        return (url.scheme, url.host, url.port) == (
            origin.scheme,
            origin.host,
            origin.port,
        )

    def _follow_redirects(self, response: httpx2.Response) -> httpx2.Response:
        history = []
        while response.next_request is not None:
            if len(history) >= self.http.max_redirects:
                raise httpx2.TooManyRedirects(
                    "Exceeded maximum allowed redirects", request=response.request
                )
            request = response.next_request
            if not self._same_origin(request.url):
                raise AO3ActionError(
                    "AO3 form redirects must stay on the client origin"
                )
            history.append(response)
            response = self.http.send(request, follow_redirects=False)
        response.history = history
        return self._check_response(response)

    def _submit_form(
        self,
        page: httpx2.Response,
        form: Element,
        data: Mapping[str, str],
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response:
        action = page.url.join(str(form["action"]))
        if not self._same_origin(page.url) or not self._same_origin(action):
            raise AO3ActionError("AO3 form submissions must stay on the client origin")

        fields = dict(data)
        document = form.find_parent("html") or form
        if document.select_one("#small_login") or not fields.get("authenticity_token"):
            fields["authenticity_token"] = self._csrf_token()

        request_headers = {"Referer": str(page.url), **(headers or {})}
        retried = False
        while True:
            response = self.http.post(
                action, data=fields, headers=request_headers, follow_redirects=False
            )
            try:
                if response.next_request is not None:
                    target = response.next_request.url
                    if not self._same_origin(target):
                        raise AO3ActionError(
                            "AO3 form redirects must stay on the client origin"
                        )
                    if target.path.rstrip("/") == "/auth_error":
                        raise AO3CSRFError("AO3 rejected the form's authenticity token")
                else:
                    self._check_response(response)
            except AO3CSRFError:
                if retried:
                    raise
                # Rails rejects CSRF before running the action. Other failures,
                # especially timeouts, must not replay a potentially saved write.
                fields["authenticity_token"] = self._csrf_token()
                retried = True
                continue

            return self._follow_redirects(response) if follow_redirects else response

    def login(
        self, login: str, password: str, *, remember_me: bool = False
    ) -> "AO3Client":
        response = self._check_response(
            self.http.get("/users/login", follow_redirects=True), login_page=True
        )

        if (
            form := BeautifulSoup(response.content, "lxml").select_one(
                "form#new_user[action]"
            )
        ) is None:
            raise AO3ParseError("The AO3 login form was not found")

        data = {
            str(element["name"]): str(element.get("value", ""))
            for element in form.select("input[type=hidden][name]")
        }
        data["user[login]"] = login
        data["user[password]"] = password
        data["user[remember_me]"] = "1" if remember_me else "0"
        response = self._submit_form(response, form, data)
        if BeautifulSoup(response.content, "lxml").select_one("body.logged-in") is None:
            raise AO3AuthenticationError("AO3 did not confirm a successful login")

        return self

    @overload
    def work(
        self, id: int, chapter_id: int | None = None, *, view_adult: bool = True
    ) -> Work: ...

    @overload
    def work(self, *, url: str, view_adult: bool = True) -> Work: ...

    def work(
        self,
        id: int | None = None,
        chapter_id: int | None = None,
        *,
        url: str | None = None,
        view_adult: bool = True,
    ) -> Work:
        if url is not None:
            if id is not None:
                raise TypeError("work() accepts either id or url, not both")
            return Work.from_url(url, view_adult=view_adult, client=self)

        if id is None:
            raise TypeError("work() requires id or url")

        return Work.from_id(id, chapter_id, view_adult=view_adult, client=self)

    def tag(self, name: str, *, page: int = 1, view_adult: bool = True) -> Tag:
        return Tag(name, page=page, view_adult=view_adult, client=self)

    def media(self, name: str) -> Media:
        return Media(name, client=self)

    def language(
        self,
        short: str,
        name: str | None = None,
        *,
        page: int = 1,
        view_adult: bool = True,
    ) -> Language:
        return Language(short, name, page=page, view_adult=view_adult, client=self)

    def user(self, login: str, *, page: int = 1, view_adult: bool = True) -> User:
        return User(login, page=page, view_adult=view_adult, client=self)

    def pseud(
        self, name: str, user_login: str, *, page: int = 1, view_adult: bool = True
    ) -> Pseud:
        return Pseud(name, user_login, page=page, view_adult=view_adult, client=self)

    def series(
        self, series_id: int, *, page: int = 1, view_adult: bool = True
    ) -> Series:
        return Series(series_id, page=page, view_adult=view_adult, client=self)

    def comment(self, comment_id: int) -> Comment:
        return Comment(comment_id, client=self)

    def bookmark(self, bookmark_id: int, *, view_adult: bool = True) -> Bookmark:
        return Bookmark(bookmark_id, view_adult=view_adult, client=self)

    def external_work(
        self, external_work_id: int, *, page: int = 1, view_adult: bool = True
    ) -> ExternalWork:
        return ExternalWork(
            external_work_id, page=page, view_adult=view_adult, client=self
        )

    def collection(
        self, name: str, *, page: int = 1, view_adult: bool = True
    ) -> Collection:
        return Collection(name, page=page, view_adult=view_adult, client=self)

    @cached_property
    def media_index(self) -> tuple[Media, ...]:
        return tuple(
            Media.from_data(data, client=self)
            for data in Media.parse_index(self.get("/media").content)
        )

    def fetch_media_index_fandoms(self, media: Media) -> tuple[Tag, ...]:
        for item in self.media_index:
            if item.name == media.name:
                media.link = item.link
                return tuple(tag.copy() for tag in item.index_fandoms)

        raise AO3ParseError(f"AO3 media category {media.name!r} was not found")

    def fetch_fandoms(self, media: Media) -> tuple[Tag.Reference, ...]:
        return Media.parse_fandoms(self.get(media.link).content)

    def fetch_tag_works(self, tag: Tag) -> Work.Page:
        params: dict[str, str | int] = {"page": tag.page}

        if tag.view_adult:
            params["view_adult"] = "true"

        response = self.get(tag.link, params=params)
        if (
            response.history
            and tag.page != 1
            and response.url.params.get("page") != str(tag.page)
        ):
            response = self.get(str(response.url), params=params)
        data = Work.parse_index(response.content, tag.page)

        return Work.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Work.from_summary(summary, view_adult=tag.view_adult, client=self)
                for summary in data.works
            ),
        )

    def fetch_tag_bookmarks(self, tag: Tag) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": tag.page}

        if tag.view_adult:
            params["view_adult"] = "true"

        response = self.get(Tag.path(tag.name, bookmarks=True), params=params)
        if (
            response.history
            and tag.page != 1
            and response.url.params.get("page") != str(tag.page)
        ):
            response = self.get(str(response.url), params=params)
        data = Bookmark.parse_index(response.content, tag.page)

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(bookmark, view_adult=tag.view_adult, client=self)
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def fetch_language_works(self, language: Language) -> Work.Page:
        params: dict[str, str | int] = {"page": language.page}

        if language.view_adult:
            params["view_adult"] = "true"

        data = Work.parse_index(
            self.get(language.link, params=params).content, language.page
        )

        return Work.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Work.from_summary(work, view_adult=language.view_adult, client=self)
                for work in data.works
            ),
        )

    def fetch_work(self, work: Work, *, include_content: bool) -> Work.Parsed:
        params = {"style": "disable"}

        if work.view_adult:
            params["view_adult"] = "true"

        if include_content and work.chapter_id is None:
            params["view_full_work"] = "true"

        parsed = Work.parse_page(
            self.get(work.link, params=params).content,
            work.id,
            include_content=include_content,
        )

        if parsed.chapters:
            references = Chapter.parse_navigation(
                self.get(f"/works/{work.id}/navigate").content
            )

            references_by_id = {reference.id: reference for reference in references}
            references_by_position = {
                reference.position: reference for reference in references
            }

            for chapter in parsed.chapters:
                reference = (
                    references_by_id.get(chapter.id)
                    if chapter.id is not None
                    else references_by_position.get(chapter.position)
                )

                if reference:
                    chapter.merge(reference)

        return parsed

    def fetch_work_comments(self, work: Work, page: int) -> Comment.Page:
        params: dict[str, str | int] = {
            "page": page,
            "show_comments": "true",
            "style": "disable",
        }

        if work.view_adult:
            params["view_adult"] = "true"

        if work.chapter_id is None:
            params["view_full_work"] = "true"

        data = Comment.parse_page(self.get(work.link, params=params).content, page)

        return Comment.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(Comment.from_data(comment, client=self) for comment in data.comments),
        )

    def create_comment(
        self,
        commentable: Work | Chapter | Comment,
        content: str,
        *,
        pseud_id: int | None = None,
        name: str | None = None,
        email: str | None = None,
    ) -> Comment:
        if isinstance(commentable, Work):
            path = (
                f"/works/{commentable.id}/chapters/{commentable.chapter_id}/comments/new"
                if commentable.chapter_id is not None
                else f"/works/{commentable.id}/comments/new"
            )
            params = {"view_adult": "true"} if commentable.view_adult else None

        elif isinstance(commentable, Chapter):
            path = (
                f"/works/{commentable.work_id}/chapters/{commentable.id}/comments/new"
                if commentable.id is not None
                else f"/works/{commentable.work_id}/comments/new"
            )
            params = {"view_adult": "true"} if commentable.view_adult else None

        else:
            path = f"/comments/{commentable.id}/comments/new"
            params = None

        page = self.get(path, params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                "form[id^='comment_for_'][action]"
            )
        ) is None:
            raise AO3ActionError("AO3 did not offer a comment form")

        data = {
            str(element["name"]): str(element.get("value", ""))
            for element in form.select("input[type=hidden][name]")
        }

        if pseud_id is not None:
            data["comment[pseud_id]"] = str(pseud_id)

        elif "comment[pseud_id]" not in data and (
            option := form.select_one(
                "select[name='comment[pseud_id]'] option[selected]"
            )
            or form.select_one("select[name='comment[pseud_id]'] option")
        ):
            data["comment[pseud_id]"] = str(option.get("value", ""))

        if name is not None:
            data["comment[name]"] = name

        if email is not None:
            data["comment[email]"] = email

        data["comment[comment_content]"] = content

        response = self._submit_form(page, form, data, follow_redirects=False)

        # The new-comment form redirects directly to the saved comment. A guest
        # cannot open that page while it is awaiting moderation, but the write
        # has already succeeded. Return the usual lazy Comment without a GET.
        if (
            response.status_code in {302, 303}
            and response.next_request is not None
            and (
                match := re.fullmatch(
                    r"/comments/(?P<comment_id>[0-9]+)", response.next_request.url.path
                )
            )
        ):
            return Comment(int(match["comment_id"]), client=self)

        response = self._follow_redirects(response)

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one(
            "#error_explanation, #errorExplanation, .errorExplanation, "
            "div.flash.error, div.flash.comment_error"
        ):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if not (
            match := re.fullmatch(
                r"/comments/(?P<comment_id>[0-9]+)", response.url.path.rstrip("/")
            )
        ):
            raise AO3ParseError("AO3 did not return the created comment")

        return Comment(int(match["comment_id"]), client=self)

    def fetch_chapter_comments(self, chapter: Chapter, page: int) -> Comment.Page:
        params: dict[str, str | int] = {
            "page": page,
            "show_comments": "true",
            "style": "disable",
        }

        if chapter.view_adult:
            params["view_adult"] = "true"

        data = Comment.parse_page(
            self.get(
                f"/works/{chapter.work_id}/chapters/{chapter.id}", params=params
            ).content,
            page,
        )

        return Comment.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(Comment.from_data(comment, client=self) for comment in data.comments),
        )

    def fetch_kudos(self, kudos: Kudos) -> Kudos.Data:
        return Kudos.parse_page(
            self.get(kudos.url, params={"page": kudos.page}).content, kudos.page
        )

    def leave_kudos(self, kudos: Kudos) -> None:
        params = {"style": "disable"}

        if kudos.view_adult:
            params["view_adult"] = "true"

        page = self.get(f"/works/{kudos.work_id}", params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                "form#new_kudo[action]"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 does not allow this session to leave Kudos on Work "
                f"{kudos.work_id}"
            )

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
        )

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one("div.flash.kudos_error, div.flash.error"):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if soup.select_one("div.flash.kudos_notice") is None:
            raise AO3ParseError(
                f"AO3 did not confirm that Kudos were left on Work {kudos.work_id}"
            )

    def fetch_work_bookmarks(self, work: Work, page: int) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": page}

        if work.view_adult:
            params["view_adult"] = "true"

        data = Bookmark.parse_index(
            self.get(f"/works/{work.id}/bookmarks", params=params).content, page
        )

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(bookmark, view_adult=work.view_adult, client=self)
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def create_bookmark(
        self,
        work: Work,
        *,
        notes: str = "",
        tags: str | Iterable[str | Tag] = (),
        collections: str | Iterable[str | Collection] = (),
        private: bool = False,
        recommended: bool = False,
        pseud_id: int | None = None,
    ) -> Bookmark:
        params = {"view_adult": "true"} if work.view_adult else None
        page = self.get(f"/works/{work.id}/bookmarks/new", params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                "#bookmark-form form[action], form#new_bookmark[action]"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not offer a bookmark form for Work {work.id}"
            )

        data = {
            str(element["name"]): str(element.get("value", ""))
            for element in form.select("input[type=hidden][name]")
        }

        if pseud_id is not None:
            data["bookmark[pseud_id]"] = str(pseud_id)

        elif "bookmark[pseud_id]" not in data:
            option = form.select_one(
                "select[name='bookmark[pseud_id]'] option:checked"
            ) or form.select_one("select[name='bookmark[pseud_id]'] option")

            if option is None:
                raise AO3ParseError("The AO3 bookmark form did not expose a pseud")

            data["bookmark[pseud_id]"] = str(option.get("value", ""))

        data.update(
            {
                "bookmark[bookmarker_notes]": notes,
                "bookmark[tag_string]": tags
                if isinstance(tags, str)
                else ", ".join(
                    tag.name if isinstance(tag, Tag) else tag for tag in tags
                ),
                "bookmark[collection_names]": collections
                if isinstance(collections, str)
                else ", ".join(
                    collection.name
                    if isinstance(collection, Collection)
                    else collection
                    for collection in collections
                ),
                "bookmark[private]": "1" if private else "0",
                "bookmark[rec]": "1" if recommended else "0",
            }
        )

        response = self._submit_form(page, form, data)

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one(
            "#error_explanation, #errorExplanation, .errorExplanation, div.flash.error"
        ):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if (article := soup.select_one("li[id^='bookmark_']")) is None or (
            detail := Bookmark.parse_blurb(article)
        ) is None:
            raise AO3ParseError(
                f"AO3 did not return the created bookmark for Work {work.id}"
            )

        return Bookmark.from_data(detail, view_adult=work.view_adult, client=self)

    def fetch_user(self, user: User) -> User.Data:
        return User.parse_profile(self.get(f"{user.link}/profile").content, user.login)

    def fetch_user_pseuds(self, user: User) -> Pseud.Page:
        data = Pseud.parse_index(
            self.get(f"{user.link}/pseuds", params={"page": user.page}).content,
            user.page,
        )

        return Pseud.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Pseud.from_reference(pseud, view_adult=user.view_adult, client=self)
                for pseud in data.pseuds
            ),
        )

    def fetch_user_works(self, user: User) -> Work.Page:
        params: dict[str, str | int] = {"page": user.page}

        if user.view_adult:
            params["view_adult"] = "true"

        data = Work.parse_index(
            self.get(f"{user.link}/works", params=params).content, user.page
        )

        return Work.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Work.from_summary(work, view_adult=user.view_adult, client=self)
                for work in data.works
            ),
        )

    def fetch_user_series(self, user: User) -> Series.Page:
        params: dict[str, str | int] = {"page": user.page}

        if user.view_adult:
            params["view_adult"] = "true"

        data = Series.parse_index(
            self.get(f"{user.link}/series", params=params).content, user.page
        )

        return Series.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Series.from_summary(series, view_adult=user.view_adult, client=self)
                for series in data.series
            ),
        )

    def fetch_user_bookmarks(self, user: User) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": user.page}

        if user.view_adult:
            params["view_adult"] = "true"

        data = Bookmark.parse_index(
            self.get(f"{user.link}/bookmarks", params=params).content, user.page
        )

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(bookmark, view_adult=user.view_adult, client=self)
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def fetch_user_collections(self, user: User) -> Collection.Page:
        data = Collection.parse_index(
            self.get(f"{user.link}/collections", params={"page": user.page}).content,
            user.page,
        )

        return Collection.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Collection.from_summary(
                    collection, view_adult=user.view_adult, client=self
                )
                for collection in data.collections
            ),
        )

    def fetch_pseud_works(self, pseud: Pseud) -> Work.Page:
        params: dict[str, str | int] = {"page": pseud.page}

        if pseud.view_adult:
            params["view_adult"] = "true"

        data = Work.parse_index(
            self.get(f"{pseud.link}/works", params=params).content, pseud.page
        )

        return Work.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Work.from_summary(work, view_adult=pseud.view_adult, client=self)
                for work in data.works
            ),
        )

    def fetch_pseud_series(self, pseud: Pseud) -> Series.Page:
        params: dict[str, str | int] = {"page": pseud.page}

        if pseud.view_adult:
            params["view_adult"] = "true"

        data = Series.parse_index(
            self.get(f"{pseud.link}/series", params=params).content, pseud.page
        )

        return Series.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Series.from_summary(series, view_adult=pseud.view_adult, client=self)
                for series in data.series
            ),
        )

    def fetch_pseud_bookmarks(self, pseud: Pseud) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": pseud.page}

        if pseud.view_adult:
            params["view_adult"] = "true"

        data = Bookmark.parse_index(
            self.get(f"{pseud.link}/bookmarks", params=params).content, pseud.page
        )

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(bookmark, view_adult=pseud.view_adult, client=self)
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def fetch_series(self, series: Series) -> tuple[Series.Data, Work.Page]:
        params: dict[str, str | int] = {"page": series.page}

        if series.view_adult:
            params["view_adult"] = "true"

        parsed = Series.parse_page(
            self.get(series.link, params=params).content, series.id, series.page
        )

        return (
            parsed.detail,
            Work.Page(
                parsed.works.page,
                parsed.works.page_count,
                parsed.works.total,
                tuple(
                    Work.from_summary(work, view_adult=series.view_adult, client=self)
                    for work in parsed.works.works
                ),
            ),
        )

    def fetch_series_bookmarks(self, series: Series) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": series.page}

        if series.view_adult:
            params["view_adult"] = "true"

        data = Bookmark.parse_index(
            self.get(f"/series/{series.id}/bookmarks", params=params).content,
            series.page,
        )

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(bookmark, view_adult=series.view_adult, client=self)
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def fetch_comment(self, comment: Comment) -> Comment.Data:
        return Comment.parse_root(self.get(comment.link).content, comment.id)

    def update_comment(
        self, comment: Comment, content: str, *, pseud_id: int | None = None
    ) -> Comment.Data:
        page = self.get(f"/comments/{comment.id}/edit")

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                f"form[action$='/comments/{comment.id}']"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not allow this session to edit Comment {comment.id}"
            )

        data = {
            str(element["name"]): str(element.get("value", ""))
            for element in form.select("input[type=hidden][name]")
        }

        if pseud_id is not None:
            data["comment[pseud_id]"] = str(pseud_id)
        elif "comment[pseud_id]" not in data and (
            option := form.select_one(
                "select[name='comment[pseud_id]'] option[selected]"
            )
            or form.select_one("select[name='comment[pseud_id]'] option")
        ):
            data["comment[pseud_id]"] = str(option.get("value", ""))

        data["comment[comment_content]"] = content

        response = self._submit_form(page, form, data)

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one(
            "#error_explanation, #errorExplanation, .errorExplanation, "
            "div.flash.error, div.flash.comment_error"
        ):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if soup.select_one("div.flash.comment_notice, div.flash.notice") is None:
            raise AO3ParseError(
                f"AO3 did not confirm the update to Comment {comment.id}"
            )

        return Comment.parse_root(response.content, comment.id)

    def delete_comment(self, comment: Comment) -> None:
        page = self.get(comment.link, params={"delete_comment_id": comment.id})

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                f"form[action$='/comments/{comment.id}']:has("
                "input[name='_method'][value='delete'])"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not allow this session to delete Comment {comment.id}"
            )

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
        )

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one("div.flash.error, div.flash.comment_error"):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if soup.select_one("div.flash.comment_notice, div.flash.notice") is None:
            raise AO3ParseError(f"AO3 did not confirm deletion of Comment {comment.id}")

    def create_subscription(self, subscribable: Work | Series | User) -> Subscription:
        subscribable_type: Literal["Work", "Series", "User"]

        if isinstance(subscribable, Work):
            subscribable_type = "Work"
            subscribable_link = f"/works/{subscribable.id}"
            params = {"view_adult": "true"} if subscribable.view_adult else None
        elif isinstance(subscribable, Series):
            subscribable_type = "Series"
            subscribable_link = subscribable.link
            params = {"view_adult": "true"} if subscribable.view_adult else None
        else:
            subscribable_type = "User"
            subscribable_link = subscribable.link
            params = None

        page = self.get(subscribable_link, params=params)
        soup = BeautifulSoup(page.content, "lxml")
        form = soup.select_one(
            "form.ajax-create-destroy[action]:has("
            "input[name='subscription[subscribable_type]']"
            f"[value='{subscribable_type}'])"
        )

        if form is None:
            raise AO3ActionError(
                f"AO3 did not offer a subscription form for {subscribable_type}"
            )

        if (
            id_element := form.select_one("input[name='subscription[subscribable_id]']")
        ) is None:
            raise AO3ParseError("The AO3 subscription form did not expose its target")

        subscribable_id = int(str(id_element["value"]))

        if form.select_one("input[name='_method'][value='delete']"):
            if not (
                match := re.search(
                    r"/subscriptions/(?P<subscription_id>[0-9]+)$", str(form["action"])
                )
            ):
                raise AO3ParseError(
                    "The AO3 subscription form did not expose its subscription ID"
                )

            return Subscription(
                int(match["subscription_id"]),
                subscribable_type,
                subscribable_id,
                subscribable_link,
                str(form["action"]),
                client=self,
            )

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
            headers={"Accept": "application/json"},
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise AO3ParseError(
                "AO3 did not return the created subscription"
            ) from error

        if not isinstance(payload, dict) or "item_id" not in payload:
            raise AO3ParseError("AO3 did not return the created subscription")

        return Subscription(
            int(payload["item_id"]),
            subscribable_type,
            subscribable_id,
            subscribable_link,
            f"{str(form['action']).rstrip('/')}/{payload['item_id']}",
            client=self,
        )

    def delete_subscription(
        self, subscription: Subscription | Work | Series | User
    ) -> None:
        subscribable_type: Literal["Work", "Series", "User"]

        if isinstance(subscription, Subscription):
            subscribable_type = subscription.subscribable_type
            subscribable_link = subscription.subscribable_link
            params = {"view_adult": "true"}
        elif isinstance(subscription, Work):
            subscribable_type = "Work"
            subscribable_link = f"/works/{subscription.id}"
            params = {"view_adult": "true"} if subscription.view_adult else None
        elif isinstance(subscription, Series):
            subscribable_type = "Series"
            subscribable_link = subscription.link
            params = {"view_adult": "true"} if subscription.view_adult else None
        else:
            subscribable_type = "User"
            subscribable_link = subscription.link
            params = None

        page = self.get(subscribable_link, params=params)
        soup = BeautifulSoup(page.content, "lxml")
        form = soup.select_one(
            "form.ajax-create-destroy[action]:has("
            "input[name='subscription[subscribable_type]']"
            f"[value='{subscribable_type}'])"
        )

        if (
            form is None
            or form.select_one("input[name='_method'][value='delete']") is None
        ):
            raise AO3ActionError(
                f"This session is not subscribed to {subscribable_type}"
            )

        if isinstance(subscription, Subscription) and (
            httpx2.URL(str(form["action"])).path != httpx2.URL(subscription.link).path
        ):
            raise AO3ActionError("This subscription has been replaced or removed")

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
            headers={"Accept": "application/json"},
        )

        try:
            payload = response.json()
        except ValueError as error:
            raise AO3ParseError("AO3 did not confirm subscription deletion") from error

        if not isinstance(payload, dict) or "item_success_message" not in payload:
            raise AO3ParseError("AO3 did not confirm subscription deletion")

    def mark_for_later(self, work: Work) -> None:
        params = {"view_adult": "true"} if work.view_adult else None
        page = self.get(f"/works/{work.id}", params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                f"form[action$='/works/{work.id}/mark_for_later']:has("
                "input[name='_method'][value='patch'])"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not offer the mark_for_later action for Work {work.id}"
            )

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
        )

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one("div.flash.error"):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if soup.select_one("div.flash.notice") is None:
            raise AO3ParseError(
                f"AO3 did not confirm mark_for_later for Work {work.id}"
            )

    def mark_as_read(self, work: Work) -> None:
        params = {"view_adult": "true"} if work.view_adult else None
        page = self.get(f"/works/{work.id}", params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                f"form[action$='/works/{work.id}/mark_as_read']:has("
                "input[name='_method'][value='patch'])"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not offer the mark_as_read action for Work {work.id}"
            )

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
        )

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one("div.flash.error"):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if soup.select_one("div.flash.notice") is None:
            raise AO3ParseError(f"AO3 did not confirm mark_as_read for Work {work.id}")

    def fetch_bookmark(self, bookmark: Bookmark) -> Bookmark.Data:
        if bookmark.id is None or bookmark.link is None:
            raise AO3ParseError("AO3 did not expose an ID for this bookmark")

        params = {"view_adult": "true"} if bookmark.view_adult else None

        return Bookmark.parse_page(
            self.get(bookmark.link, params=params).content, bookmark.id
        )

    def update_bookmark(
        self,
        bookmark: Bookmark,
        *,
        notes: str | None = None,
        tags: str | Iterable[str | Tag] | None = None,
        collections: str | Iterable[str | Collection] | None = None,
        private: bool | None = None,
        recommended: bool | None = None,
        pseud_id: int | None = None,
    ) -> Bookmark.Data:
        if bookmark.id is None:
            raise AO3ParseError("AO3 did not expose an ID for this bookmark")

        params = {"view_adult": "true"} if bookmark.view_adult else None
        page = self.get(f"/bookmarks/{bookmark.id}/edit", params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                f"form[action$='/bookmarks/{bookmark.id}']"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not allow this session to edit Bookmark {bookmark.id}"
            )

        data = {
            str(element["name"]): str(element.get("value", ""))
            for element in form.select("input[type=hidden][name]")
            if str(element["name"]) not in {"bookmark[private]", "bookmark[rec]"}
        }

        if pseud_id is not None:
            data["bookmark[pseud_id]"] = str(pseud_id)

        if notes is not None:
            data["bookmark[bookmarker_notes]"] = notes

        if tags is not None:
            data["bookmark[tag_string]"] = (
                tags
                if isinstance(tags, str)
                else ", ".join(
                    tag.name if isinstance(tag, Tag) else tag for tag in tags
                )
            )

        if collections is not None:
            data["bookmark[collection_names]"] = (
                collections
                if isinstance(collections, str)
                else ", ".join(
                    collection.name
                    if isinstance(collection, Collection)
                    else collection
                    for collection in collections
                )
            )

        if private is not None:
            data["bookmark[private]"] = "1" if private else "0"

        if recommended is not None:
            data["bookmark[rec]"] = "1" if recommended else "0"

        response = self._submit_form(page, form, data)

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one(
            "#error_explanation, #errorExplanation, .errorExplanation, div.flash.error"
        ):
            raise AO3ActionError(error.get_text(" ", strip=True))

        return Bookmark.parse_page(response.content, bookmark.id)

    def delete_bookmark(self, bookmark: Bookmark) -> None:
        if bookmark.id is None:
            raise AO3ParseError("AO3 did not expose an ID for this bookmark")

        params = {"view_adult": "true"} if bookmark.view_adult else None
        page = self.get(f"/bookmarks/{bookmark.id}/confirm_delete", params=params)

        if (
            form := BeautifulSoup(page.content, "lxml").select_one(
                f"form.simple.destroy[action$='/bookmarks/{bookmark.id}']"
            )
        ) is None:
            raise AO3ActionError(
                f"AO3 did not allow this session to delete Bookmark {bookmark.id}"
            )

        response = self._submit_form(
            page,
            form,
            data={
                str(element["name"]): str(element.get("value", ""))
                for element in form.select("input[type=hidden][name]")
            },
        )

        soup = BeautifulSoup(response.content, "lxml")

        if error := soup.select_one(
            "#error_explanation, #errorExplanation, .errorExplanation, div.flash.error"
        ):
            raise AO3ActionError(error.get_text(" ", strip=True))

        if soup.select_one("div.flash.notice") is None:
            raise AO3ParseError(
                f"AO3 did not confirm deletion of Bookmark {bookmark.id}"
            )

    def fetch_external_work(self, external_work: ExternalWork) -> ExternalWork.Data:
        params = {"view_adult": "true"} if external_work.view_adult else None

        return ExternalWork.parse_page(
            self.get(external_work.link, params=params).content, external_work.id
        )

    def fetch_external_work_bookmarks(
        self, external_work: ExternalWork
    ) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": external_work.page}

        if external_work.view_adult:
            params["view_adult"] = "true"

        data = Bookmark.parse_index(
            self.get(
                f"/external_works/{external_work.id}/bookmarks", params=params
            ).content,
            external_work.page,
        )

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(
                    bookmark, view_adult=external_work.view_adult, client=self
                )
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def fetch_collection(self, collection: Collection) -> Collection.Data:
        return Collection.parse_profile(
            self.get(f"{collection.link}/profile").content, collection.name
        )

    def fetch_collection_works(self, collection: Collection) -> Work.Page:
        params: dict[str, str | int] = {"page": collection.page}

        if collection.view_adult:
            params["view_adult"] = "true"

        data = Work.parse_index(
            self.get(f"{collection.link}/works", params=params).content, collection.page
        )

        return Work.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Work.from_summary(work, view_adult=collection.view_adult, client=self)
                for work in data.works
            ),
        )

    def fetch_collection_bookmarks(self, collection: Collection) -> Bookmark.Page:
        params: dict[str, str | int] = {"page": collection.page}

        if collection.view_adult:
            params["view_adult"] = "true"

        data = Bookmark.parse_index(
            self.get(f"{collection.link}/bookmarks", params=params).content,
            collection.page,
        )

        return Bookmark.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Bookmark.from_data(
                    bookmark, view_adult=collection.view_adult, client=self
                )
                for bookmark in data.bookmarks
            ),
            grouped=data.grouped,
        )

    def fetch_subcollections(self, collection: Collection) -> Collection.Page:
        data = Collection.parse_index(
            self.get(
                f"{collection.link}/collections", params={"page": collection.page}
            ).content,
            collection.page,
        )

        return Collection.Page(
            data.page,
            data.page_count,
            data.total,
            tuple(
                Collection.from_summary(
                    child, view_adult=collection.view_adult, client=self
                )
                for child in data.collections
            ),
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "AO3Client":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
