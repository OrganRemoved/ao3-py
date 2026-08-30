import re
from collections.abc import Iterable, Iterator
from contextlib import suppress
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING, Literal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag as Element

from ao3.collection import Collection
from ao3.exceptions import (
    AO3AuthenticationError,
    AO3InvalidURLError,
    AO3ParseError,
)
from ao3.language import Language
from ao3.pseud import Pseud
from ao3.series import Series
from ao3.tag import Tag, TagKind
from ao3.user import User

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark
    from ao3.comment import Comment
    from ao3.subscription import Subscription


class Chapter:
    """A parsed chapter that belongs to one Work."""

    class Reference:
        __slots__ = ("id", "link", "position", "published", "title", "work_id")

        def __init__(
            self,
            chapter_id: int,
            work_id: int,
            position: int,
            link: str,
            title: str | None,
            published: date | None,
        ) -> None:
            self.id = chapter_id
            self.work_id = work_id
            self.position = position
            self.link = link
            self.title = title
            self.published = published

    class Data:
        __slots__ = (
            "content",
            "content_html",
            "endnotes",
            "endnotes_html",
            "id",
            "link",
            "notes",
            "notes_html",
            "position",
            "pseuds",
            "published",
            "summary",
            "summary_html",
            "title",
            "work_id",
        )

        def __init__(
            self,
            chapter_id: int | None,
            work_id: int,
            position: int,
            link: str | None,
            title: str | None,
            published: date | None,
            pseuds: tuple[Pseud.Reference, ...],
            summary: str | None,
            summary_html: str | None,
            notes: str | None,
            notes_html: str | None,
            content: str,
            content_html: str,
            endnotes: str | None,
            endnotes_html: str | None,
        ) -> None:
            self.id = chapter_id
            self.work_id = work_id
            self.position = position
            self.link = link
            self.title = title
            self.published = published
            self.pseuds = pseuds
            self.summary = summary
            self.summary_html = summary_html
            self.notes = notes
            self.notes_html = notes_html
            self.content = content
            self.content_html = content_html
            self.endnotes = endnotes
            self.endnotes_html = endnotes_html

        def merge(self, reference: "Chapter.Reference") -> None:
            self.id = reference.id
            self.work_id = reference.work_id
            self.position = reference.position
            self.link = reference.link
            self.title = self.title or reference.title
            self.published = reference.published

    def __init__(
        self,
        data: "Chapter.Data",
        *,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = data.id
        self.work_id = data.work_id
        self.position = data.position
        self.link = data.link
        self.title = data.title
        self.published = data.published
        self.summary = data.summary
        self.summary_html = data.summary_html
        self.notes = data.notes
        self.notes_html = data.notes_html
        self.content = data.content
        self.content_html = data.content_html
        self.endnotes = data.endnotes
        self.endnotes_html = data.endnotes_html
        self._pseud_references = data.pseuds
        self.view_adult = view_adult
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @property
    def url(self) -> str | None:
        return f"{self.client.base_url}{self.link}" if self.link else None

    @cached_property
    def work(self) -> "Work":
        return Work.from_id(
            self.work_id, view_adult=self.view_adult, client=self.client
        )

    @cached_property
    def pseuds(self) -> tuple[Pseud, ...]:
        return tuple(
            Pseud.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in self._pseud_references
        )

    @cached_property
    def comments_page(self) -> "Comment.Page":
        return self.client.fetch_chapter_comments(self, 1)

    @property
    def comments(self) -> "tuple[Comment, ...]":
        return self.comments_page.comments

    def comments_for_page(self, page: int) -> "Comment.Page":
        if page == 1:
            return self.comments_page

        return self.client.fetch_chapter_comments(self, page)

    def create_comment(
        self,
        content: str,
        *,
        pseud_id: int | None = None,
        name: str | None = None,
        email: str | None = None,
    ) -> "Comment":
        comment = self.client.create_comment(
            self, content, pseud_id=pseud_id, name=name, email=email
        )

        self.__dict__.pop("comments_page", None)

        return comment

    def __repr__(self) -> str:
        return (
            f"Chapter(id={self.id}, work_id={self.work_id}, position={self.position})"
        )

    @staticmethod
    def parse_navigation(content: bytes | str) -> "tuple[Chapter.Reference, ...]":
        soup = BeautifulSoup(content, "lxml")
        references = []
        for fallback_position, anchor in enumerate(
            soup.select("ol.chapter.index.group a[href*='/chapters/']"), 1
        ):
            if not (
                match := re.search(
                    r"/works/(?P<work_id>[0-9]+)/chapters/(?P<chapter_id>[0-9]+)",
                    str(anchor["href"]),
                )
            ):
                continue

            label = anchor.get_text(" ", strip=True)
            position = re.match(r"(?P<position>[0-9]+)\.\s*", label)
            title = re.sub(r"^[0-9]+\.\s*", "", label)

            if re.fullmatch(r"Chapter\s+[0-9]+", title, re.IGNORECASE):
                title = ""

            published = anchor.find_next_sibling("span", class_="datetime")
            published_date = None

            if published:
                with suppress(ValueError):
                    published_date = datetime.strptime(
                        published.get_text(" ", strip=True).strip("()"), "%Y-%m-%d"
                    ).date()

            references.append(
                Chapter.Reference(
                    int(match["chapter_id"]),
                    int(match["work_id"]),
                    int(position["position"]) if position else fallback_position,
                    urlparse(str(anchor["href"])).path,
                    title or None,
                    published_date,
                )
            )

        if not references:
            raise AO3ParseError("The AO3 chapter index was not found")

        return tuple(references)


class Kudos:
    """The public kudos summary and leave action for one Work."""

    class Data:
        __slots__ = ("guest_count", "page", "page_count", "users", "users_count")

        def __init__(
            self,
            page: int,
            page_count: int,
            users_count: int,
            guest_count: int,
            users: tuple[User.Reference, ...],
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.users_count = users_count
            self.guest_count = guest_count
            self.users = users

    def __init__(
        self,
        work_id: int,
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.work_id = work_id
        self.page = page
        self.view_adult = view_adult
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @property
    def url(self) -> str:
        return f"{self.client.base_url}/works/{self.work_id}/kudos"

    @cached_property
    def detail(self) -> "Kudos.Data":
        return self.client.fetch_kudos(self)

    @property
    def users(self) -> tuple[User, ...]:
        return tuple(
            User.from_reference(reference, client=self.client)
            for reference in self.detail.users
        )

    @property
    def users_count(self) -> int:
        return self.detail.users_count

    @property
    def guest_count(self) -> int:
        return self.detail.guest_count

    @property
    def total(self) -> int:
        return self.users_count + self.guest_count

    @property
    def page_count(self) -> int:
        return self.detail.page_count

    def leave(self) -> "Kudos":
        self.client.leave_kudos(self)

        self.__dict__.pop("detail", None)

        return self

    @staticmethod
    def parse_page(content: bytes | str, requested_page: int) -> "Kudos.Data":
        soup = BeautifulSoup(content, "lxml")

        if (container := soup.select_one("div#kudos")) is None or (
            heading := soup.select_one("h2.heading")
        ) is None:
            raise AO3ParseError("The AO3 kudos page was not found")

        users = tuple(
            User.Reference(
                anchor.get_text(" ", strip=True), urlparse(str(anchor["href"])).path
            )
            for anchor in container.select("p.kudos a[href^='/users/']")
        )
        pages = [
            int(element.get_text(strip=True))
            for element in soup.select(
                "ol.pagination.actions a, ol.pagination.actions span, "
                "div.pagination a, div.pagination em"
            )
            if element.get_text(strip=True).isdigit()
        ]
        current = soup.select_one(
            "ol.pagination.actions .current, "
            "ol.pagination.actions [aria-current=page], div.pagination .current"
        )
        guest_heading = next(
            (
                element
                for element in soup.select("h3.heading")
                if "guest" in element.get_text(" ", strip=True).lower()
            ),
            None,
        )

        return Kudos.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            int(match["users_count"].replace(",", ""))
            if (
                match := re.search(
                    r"(?P<users_count>[0-9][0-9,]*)\s+Users?\b",
                    heading.get_text(" ", strip=True),
                    re.IGNORECASE,
                )
            )
            else len(users),
            int(match["guest_count"].replace(",", ""))
            if guest_heading
            and (
                match := re.search(
                    r"(?P<guest_count>[0-9][0-9,]*)", guest_heading.get_text()
                )
            )
            else 0,
            users,
        )

    def copy(self, *, page: int | None = None) -> "Kudos":
        return Kudos(
            self.work_id,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            client=self.client,
        )


class Work:
    """An AO3 work with separate summary, metadata, and content states."""

    class DownloadLinks:
        __slots__ = ("azw3", "epub", "html", "mobi", "pdf")

        def __init__(
            self, azw3: str, epub: str, mobi: str, pdf: str, html: str
        ) -> None:
            self.azw3 = azw3
            self.epub = epub
            self.mobi = mobi
            self.pdf = pdf
            self.html = html

    class Parsed:
        __slots__ = ("chapters", "detail")

        def __init__(
            self, detail: "Work.Data", chapters: tuple[Chapter.Data, ...] | None
        ) -> None:
            self.detail = detail
            self.chapters = chapters

    class Page:
        class Data:
            __slots__ = ("page", "page_count", "total", "works")

            def __init__(
                self,
                page: int,
                page_count: int,
                total: int,
                works: "tuple[Work.Data, ...]",
            ) -> None:
                self.page = page
                self.page_count = page_count
                self.total = total
                self.works = works

        __slots__ = ("page", "page_count", "total", "works")

        def __init__(
            self, page: int, page_count: int, total: int, works: "tuple[Work, ...]"
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.total = total
            self.works = works

        def __iter__(self) -> "Iterator[Work]":
            return iter(self.works)

        def __len__(self) -> int:
            return len(self.works)

    class Data:
        __slots__ = (
            "additional_tags",
            "bookmarks_count",
            "categories",
            "characters",
            "collections",
            "collections_count",
            "comments_count",
            "complete",
            "download_links",
            "endnotes",
            "endnotes_html",
            "expected_number_of_chapters",
            "fandoms",
            "hits",
            "id",
            "kudos_count",
            "language",
            "notes",
            "notes_html",
            "number_of_posted_chapters",
            "path",
            "pseuds",
            "published",
            "ratings",
            "recipients",
            "relationships",
            "restricted",
            "series",
            "summary",
            "summary_html",
            "title",
            "updated",
            "warnings",
            "words",
        )

        def __init__(
            self,
            work_id: int,
            path: str,
            title: str,
            pseuds: tuple[Pseud.Reference, ...],
            recipients: tuple[Pseud.Reference, ...],
            series: tuple[Series.Reference, ...],
            collections: "tuple[Collection.Reference, ...]",
            collections_count: int,
            summary: str | None,
            summary_html: str | None,
            ratings: tuple[Tag.Reference, ...],
            warnings: tuple[Tag.Reference, ...],
            categories: tuple[Tag.Reference, ...],
            fandoms: tuple[Tag.Reference, ...],
            relationships: tuple[Tag.Reference, ...],
            characters: tuple[Tag.Reference, ...],
            additional_tags: tuple[Tag.Reference, ...],
            language: Language.Reference | None,
            published: date | None,
            updated: date | None,
            words: int,
            number_of_posted_chapters: int,
            expected_number_of_chapters: int | None,
            comments_count: int,
            kudos_count: int,
            bookmarks_count: int,
            hits: int,
            complete: bool,
            restricted: bool,
            notes: str | None = None,
            notes_html: str | None = None,
            endnotes: str | None = None,
            endnotes_html: str | None = None,
            download_links: "Work.DownloadLinks | None" = None,
        ) -> None:
            self.id = work_id
            self.path = path
            self.title = title
            self.pseuds = pseuds
            self.recipients = recipients
            self.series = series
            self.collections = collections
            self.collections_count = collections_count
            self.summary = summary
            self.summary_html = summary_html
            self.ratings = ratings
            self.warnings = warnings
            self.categories = categories
            self.fandoms = fandoms
            self.relationships = relationships
            self.characters = characters
            self.additional_tags = additional_tags
            self.language = language
            self.published = published
            self.updated = updated
            self.words = words
            self.number_of_posted_chapters = number_of_posted_chapters
            self.expected_number_of_chapters = expected_number_of_chapters
            self.comments_count = comments_count
            self.kudos_count = kudos_count
            self.bookmarks_count = bookmarks_count
            self.hits = hits
            self.complete = complete
            self.restricted = restricted
            self.notes = notes
            self.notes_html = notes_html
            self.endnotes = endnotes
            self.endnotes_html = endnotes_html
            self.download_links = download_links

    def __init__(
        self,
        work_id: int,
        chapter_id: int | None = None,
        *,
        link: str | None = None,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = work_id
        self.chapter_id = chapter_id
        self.link = link or (
            f"/works/{work_id}/chapters/{chapter_id}"
            if chapter_id
            else f"/works/{work_id}"
        )
        self.view_adult = view_adult
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @classmethod
    def from_id(
        cls,
        work_id: int,
        chapter_id: int | None = None,
        *,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Work":
        return cls(work_id, chapter_id, view_adult=view_adult, client=client)

    @classmethod
    def from_url(
        cls, url: str, *, view_adult: bool = True, client: "AO3Client | None" = None
    ) -> "Work":
        if not (
            match := re.search(
                r"/works/(?P<work_id>[0-9]+)"
                r"(?:/chapters/(?P<chapter_id>[0-9]+))?",
                "/" + urlparse(url).path.lstrip("/"),
            )
        ):
            raise AO3InvalidURLError(f"Not an AO3 work URL: {url}")

        return cls(
            int(match["work_id"]),
            int(match["chapter_id"]) if match["chapter_id"] else None,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_summary(
        cls,
        summary: "Work.Data",
        *,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Work":
        work = cls(summary.id, link=summary.path, view_adult=view_adult, client=client)
        work._summary = summary
        work.__dict__["title"] = summary.title
        return work

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def detail(self) -> "Work.Data":
        detail = self.client.fetch_work(self, include_content=False).detail
        self.__dict__["title"] = detail.title
        return detail

    @cached_property
    def title(self) -> str:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).title

    @property
    def pseuds(self) -> tuple[Pseud, ...]:
        return tuple(
            Pseud.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).pseuds
        )

    @property
    def recipients(self) -> tuple[Pseud, ...]:
        return tuple(
            Pseud.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).recipients
        )

    @property
    def series(self) -> tuple[Series, ...]:
        return tuple(
            Series.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).series
        )

    @property
    def collections(self) -> tuple[Collection, ...]:
        return tuple(
            Collection.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in self.detail.collections
        )

    @property
    def collections_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).collections_count

    @property
    def summary(self) -> str | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).summary

    @property
    def summary_html(self) -> str | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).summary_html

    @property
    def ratings(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).ratings
        )

    @property
    def warnings(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).warnings
        )

    @property
    def categories(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).categories
        )

    @property
    def fandoms(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).fandoms
        )

    @property
    def relationships(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).relationships
        )

    @property
    def characters(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).characters
        )

    @property
    def additional_tags(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).additional_tags
        )

    @property
    def tags(self) -> tuple[Tag, ...]:
        data = (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        )

        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                data.ratings
                + data.warnings
                + data.categories
                + data.fandoms
                + data.relationships
                + data.characters
                + data.additional_tags
            )
        )

    @cached_property
    def language(self) -> Language | None:
        data = (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        )

        if data.language:
            return Language.from_reference(
                data.language, view_adult=self.view_adult, client=self.client
            )

    @property
    def published(self) -> date | None:
        return self.detail.published

    @property
    def updated(self) -> date | None:
        return self.detail.updated

    @property
    def words(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).words

    @property
    def number_of_posted_chapters(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).number_of_posted_chapters

    @property
    def expected_number_of_chapters(self) -> int | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).expected_number_of_chapters

    @property
    def comments_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).comments_count

    @property
    def kudos_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).kudos_count

    @property
    def bookmarks_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).bookmarks_count

    @property
    def hits(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).hits

    @property
    def complete(self) -> bool:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).complete

    @property
    def restricted(self) -> bool:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).restricted

    @property
    def notes(self) -> str | None:
        return self.detail.notes

    @property
    def notes_html(self) -> str | None:
        return self.detail.notes_html

    @property
    def endnotes(self) -> str | None:
        return self.detail.endnotes

    @property
    def endnotes_html(self) -> str | None:
        return self.detail.endnotes_html

    @cached_property
    def chapters(self) -> tuple[Chapter, ...]:
        parsed = self.client.fetch_work(self, include_content=True)

        self.detail = parsed.detail
        self.__dict__["title"] = parsed.detail.title

        return tuple(
            Chapter(chapter, view_adult=self.view_adult, client=self.client)
            for chapter in parsed.chapters or ()
        )

    @cached_property
    def download_links(self) -> "Work.DownloadLinks | None":
        if links := self.detail.download_links:
            return Work.DownloadLinks(
                urljoin(f"{self.client.base_url}/", links.azw3),
                urljoin(f"{self.client.base_url}/", links.epub),
                urljoin(f"{self.client.base_url}/", links.mobi),
                urljoin(f"{self.client.base_url}/", links.pdf),
                urljoin(f"{self.client.base_url}/", links.html),
            )

    @cached_property
    def comments_page(self) -> "Comment.Page":
        return self.client.fetch_work_comments(self, 1)

    @property
    def comments(self) -> "tuple[Comment, ...]":
        return self.comments_page.comments

    def comments_for_page(self, page: int) -> "Comment.Page":
        if page == 1:
            return self.comments_page

        return self.client.fetch_work_comments(self, page)

    def create_comment(
        self,
        content: str,
        *,
        pseud_id: int | None = None,
        name: str | None = None,
        email: str | None = None,
    ) -> "Comment":
        comment = self.client.create_comment(
            self, content, pseud_id=pseud_id, name=name, email=email
        )

        self.__dict__.pop("comments_page", None)

        return comment

    @cached_property
    def kudos(self) -> Kudos:
        return Kudos(self.id, view_adult=self.view_adult, client=self.client)

    def create_bookmark(
        self,
        *,
        notes: str = "",
        tags: str | Iterable[str | Tag] = (),
        collections: str | Iterable[str | Collection] = (),
        private: bool = False,
        recommended: bool = False,
        pseud_id: int | None = None,
    ) -> "Bookmark":
        bookmark = self.client.create_bookmark(
            self,
            notes=notes,
            tags=tags,
            collections=collections,
            private=private,
            recommended=recommended,
            pseud_id=pseud_id,
        )

        self.__dict__.pop("bookmarks_page", None)

        return bookmark

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_work_bookmarks(self, 1)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    def bookmarks_for_page(self, page: int) -> "Bookmark.Page":
        if page == 1:
            return self.bookmarks_page

        return self.client.fetch_work_bookmarks(self, page)

    def subscribe(self) -> "Subscription":
        return self.client.create_subscription(self)

    def unsubscribe(self) -> None:
        self.client.delete_subscription(self)

    def mark_for_later(self) -> "Work":
        self.client.mark_for_later(self)
        return self

    def mark_as_read(self) -> "Work":
        self.client.mark_as_read(self)
        return self

    def download(
        self, *, file_type: Literal["azw3", "epub", "mobi", "pdf", "html"]
    ) -> bytes:
        if not (links := self.download_links):
            raise AO3ParseError(f"Work {self.id} does not expose download links")

        return self.client.get(getattr(links, file_type)).content

    def __repr__(self) -> str:
        title = (
            f", title={self.__dict__['title']!r}" if "title" in self.__dict__ else ""
        )
        return f"Work(id={self.id}{title})"

    @staticmethod
    def fragment(element: Element | None) -> str | None:
        if element is not None:
            return "".join(str(child) for child in element.contents).strip() or None

    @staticmethod
    def user_text(element: Element | None) -> str | None:
        if element is None or not (content := Work.fragment(element)):
            return None

        soup = BeautifulSoup(content, "lxml")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for block in soup.find_all(
            [
                "address",
                "article",
                "aside",
                "blockquote",
                "div",
                "figcaption",
                "figure",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "li",
                "p",
                "pre",
            ]
        ):
            block.append("\n")
        lines = [
            re.sub(r"[^\S\n]+", " ", line).strip()
            for line in soup.get_text().splitlines()
        ]
        return "\n".join(line for line in lines if line) or None

    @staticmethod
    def number(element: Element | None) -> int:
        if element is None or not (
            match := re.search(r"(?P<number>[0-9][0-9,]*)", element.get_text())
        ):
            return 0

        return int(match["number"].replace(",", ""))

    @staticmethod
    def parse_date(element: Element | None) -> date | None:
        if element is not None:
            value = element.get_text(" ", strip=True)
            for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                with suppress(ValueError):
                    return datetime.strptime(value, date_format).date()

    @staticmethod
    def references(
        container: Element | BeautifulSoup, selector: str, kind: TagKind
    ) -> tuple[Tag.Reference, ...]:
        return tuple(
            Tag.Reference(
                anchor.get_text(" ", strip=True),
                urlparse(str(anchor["href"])).path,
                kind,
            )
            for anchor in container.select(selector)
        )

    @staticmethod
    def parse_blurb(article: Element) -> "Work.Data | None":
        if (
            (heading := article.select_one("div.header.module h4.heading")) is None
            or (title_link := heading.select_one("a[href*='/works/']")) is None
            or not (
                work_id := re.search(
                    r"(?:work_|/works/)(?P<work_id>[0-9]+)",
                    f"{article.get('id', '')} {title_link.get('href', '')}",
                )
            )
        ):
            return None

        stats = article.select_one("dl.stats")
        chapters = stats.select_one("dd.chapters") if stats else None
        number_of_posted_chapters, expected_number_of_chapters = 0, None

        if chapters and "/" in (chapter_text := chapters.get_text(" ", strip=True)):
            current, total = chapter_text.split("/", 1)
            number_of_posted_chapters = int(current.replace(",", ""))
            expected_number_of_chapters = (
                None if total.strip() == "?" else int(total.replace(",", ""))
            )

        rating = article.select_one("ul.required-tags span.rating")
        categories = article.select_one("ul.required-tags span.category")
        category_names = str(categories.get("title", "")) if categories else ""

        if category_names.casefold() == "no category":
            category_names = ""

        complete = bool(article.select_one("ul.required-tags span.complete-yes"))

        if not article.select_one(
            "ul.required-tags span.complete-yes, ul.required-tags span.complete-no"
        ):
            complete = (
                expected_number_of_chapters is not None
                and number_of_posted_chapters == expected_number_of_chapters
            )

        pseuds = []
        for anchor in heading.select("a[rel=author][href]"):
            with suppress(AO3InvalidURLError):
                pseuds.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        recipients = []
        for anchor in heading.select("a[href*='/gifts']"):
            with suppress(AO3InvalidURLError):
                recipients.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        series = []
        for item in article.select("ul.series > li"):
            if (anchor := item.select_one("a[href*='/series/']")) is None or not (
                match := re.search(
                    r"/series/(?P<series_id>[0-9]+)", str(anchor["href"])
                )
            ):
                continue

            position = re.search(
                r"\bPart\s+(?P<position>[0-9]+)\b",
                item.get_text(" ", strip=True),
                re.IGNORECASE,
            )
            series.append(
                Series.Reference(
                    int(match["series_id"]),
                    anchor.get_text(" ", strip=True),
                    f"/series/{match['series_id']}",
                    int(position["position"]) if position else None,
                )
            )

        summary = article.select_one("blockquote.userstuff.summary")

        return Work.Data(
            int(work_id["work_id"]),
            f"/works/{work_id['work_id']}",
            title_link.get_text(" ", strip=True),
            tuple(pseuds),
            tuple(recipients),
            tuple(series),
            (),
            Work.number(stats.select_one("dd.collections") if stats else None),
            Work.user_text(summary),
            Work.fragment(summary),
            (
                (
                    Tag.Reference(
                        str(rating.get("title") or rating.get_text(" ", strip=True)),
                        Tag.path(
                            str(rating.get("title") or rating.get_text(" ", strip=True))
                        ),
                        "rating",
                    ),
                )
                if rating
                else ()
            ),
            Work.references(
                article, "ul.tags.commas > li.warnings a.tag[href]", "warning"
            ),
            tuple(
                Tag.Reference(name, Tag.path(name), "category")
                for name in category_names.split(", ")
                if name
            ),
            Work.references(article, "h5.fandoms a.tag[href]", "fandom"),
            Work.references(
                article, "ul.tags.commas > li.relationships a.tag[href]", "relationship"
            ),
            Work.references(
                article, "ul.tags.commas > li.characters a.tag[href]", "character"
            ),
            Work.references(
                article, "ul.tags.commas > li.freeforms a.tag[href]", "freeform"
            ),
            Language.Reference.from_element(
                stats.select_one("dd.language") if stats else None
            ),
            None,
            Work.parse_date(article.select_one("p.datetime")),
            Work.number(stats.select_one("dd.words") if stats else None),
            number_of_posted_chapters,
            expected_number_of_chapters,
            Work.number(stats.select_one("dd.comments") if stats else None),
            Work.number(stats.select_one("dd.kudos") if stats else None),
            Work.number(stats.select_one("dd.bookmarks") if stats else None),
            Work.number(stats.select_one("dd.hits") if stats else None),
            complete,
            bool(article.select_one("img[title='Restricted']")),
        )

    @staticmethod
    def parse_index(content: bytes | str, requested_page: int) -> "Work.Page.Data":
        soup = BeautifulSoup(content, "lxml")

        if (
            listing := soup.select_one("ol.work.index.group, ul.work.index.group")
        ) is None:
            raise AO3ParseError("The AO3 work listing was not found")

        works = tuple(
            work
            for article in listing.select(":scope > li[role=article]")
            if (work := Work.parse_blurb(article)) is not None
        )

        pages = [
            int(element.get_text(strip=True))
            for element in soup.select(
                "ol.pagination.actions a, ol.pagination.actions span, "
                "div.pagination a, div.pagination em"
            )
            if element.get_text(strip=True).isdigit()
        ]
        current = soup.select_one(
            "ol.pagination.actions .current, "
            "ol.pagination.actions [aria-current=page], div.pagination .current"
        )

        heading = listing.find_previous("h2", class_="heading")
        total = re.search(
            r"(?P<count>[0-9][0-9,]*)\s+Works?\b",
            heading.get_text(" ", strip=True) if heading else "",
            re.IGNORECASE,
        )

        return Work.Page.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            int(total["count"].replace(",", "")) if total else len(works),
            works,
        )

    @staticmethod
    def parse_page(
        content: bytes | str, work_id: int, *, include_content: bool
    ) -> "Work.Parsed":
        soup = BeautifulSoup(content, "lxml")

        if (
            (meta := soup.select_one("dl.work.meta.group")) is None
            or (preface := soup.select_one("#workskin > .preface.group")) is None
            or (title_heading := preface.select_one("h2.title.heading")) is None
        ):
            if (
                soup.select_one("form#new_user, form.new_user")
                or "registered users" in soup.get_text().lower()
            ):
                raise AO3AuthenticationError(f"Work {work_id} requires an AO3 login")
            raise AO3ParseError(f"Work metadata for {work_id} was not found")

        stats = meta.select_one("dd.stats dl.stats")
        chapters = stats.select_one("dd.chapters") if stats else None
        number_of_posted_chapters, expected_number_of_chapters = 0, None

        if chapters and "/" in (chapter_text := chapters.get_text(" ", strip=True)):
            current, total = chapter_text.split("/", 1)
            number_of_posted_chapters = int(current.replace(",", ""))
            expected_number_of_chapters = (
                None if total.strip() == "?" else int(total.replace(",", ""))
            )

        pseuds = []
        for anchor in preface.select("h3.byline.heading a[rel=author][href]"):
            with suppress(AO3InvalidURLError):
                pseuds.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        recipients = []
        for anchor in preface.select(
            "div.notes.module ul.associations a[href*='/gifts']"
        ):
            with suppress(AO3InvalidURLError):
                recipients.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        series = []
        for anchor in meta.select("dd.series a[href*='/series/']"):
            if not (
                match := re.search(
                    r"/series/(?P<series_id>[0-9]+)", str(anchor["href"])
                )
            ):
                continue

            position_element = (
                anchor.find_parent("span", class_="position") or anchor.parent
            )
            position = re.search(
                r"\bPart\s+(?P<position>[0-9]+)\b",
                position_element.get_text(" ", strip=True) if position_element else "",
                re.IGNORECASE,
            )
            series.append(
                Series.Reference(
                    int(match["series_id"]),
                    anchor.get_text(" ", strip=True),
                    f"/series/{match['series_id']}",
                    int(position["position"]) if position else None,
                )
            )

        collections = []
        for anchor in meta.select("dd.collections a[href^='/collections/']"):
            path = urlparse(str(anchor["href"])).path
            parts = path.split("/")

            if len(parts) > 2:
                collections.append(
                    Collection.Reference(
                        parts[2], anchor.get_text(" ", strip=True), path
                    )
                )

        summary = preface.select_one("div.summary.module blockquote.userstuff")
        notes = preface.select_one("div.notes.module blockquote.userstuff")
        endnotes = soup.select_one(
            "#work_endnotes blockquote.userstuff, "
            "#workskin > .afterword .end.notes.module blockquote.userstuff"
        )

        links = {
            anchor.get_text(" ", strip=True).lower(): str(anchor["href"])
            for anchor in soup.select("li.download a[href]")
        }

        detail = Work.Data(
            work_id,
            f"/works/{work_id}",
            title_heading.get_text(" ", strip=True),
            tuple(pseuds),
            tuple(recipients),
            tuple(series),
            tuple(collections),
            len(collections),
            Work.user_text(summary),
            Work.fragment(summary),
            Work.references(meta, "dd.rating.tags a.tag[href]", "rating"),
            Work.references(meta, "dd.warning.tags a.tag[href]", "warning"),
            Work.references(meta, "dd.category.tags a.tag[href]", "category"),
            Work.references(meta, "dd.fandom.tags a.tag[href]", "fandom"),
            Work.references(meta, "dd.relationship.tags a.tag[href]", "relationship"),
            Work.references(meta, "dd.character.tags a.tag[href]", "character"),
            Work.references(meta, "dd.freeform.tags a.tag[href]", "freeform"),
            Language.Reference.from_element(meta.select_one("dd.language")),
            Work.parse_date(stats.select_one("dd.published") if stats else None),
            Work.parse_date(stats.select_one("dd.status") if stats else None),
            Work.number(stats.select_one("dd.words") if stats else None),
            number_of_posted_chapters,
            expected_number_of_chapters,
            Work.number(stats.select_one("dd.comments") if stats else None),
            Work.number(stats.select_one("dd.kudos") if stats else None),
            Work.number(stats.select_one("dd.bookmarks") if stats else None),
            Work.number(stats.select_one("dd.hits") if stats else None),
            expected_number_of_chapters is not None
            and number_of_posted_chapters == expected_number_of_chapters,
            bool(title_heading.select_one("img[title='Restricted']")),
            Work.user_text(notes),
            Work.fragment(notes),
            Work.user_text(endnotes),
            Work.fragment(endnotes),
            Work.DownloadLinks(
                links["azw3"], links["epub"], links["mobi"], links["pdf"], links["html"]
            )
            if {"azw3", "epub", "mobi", "pdf", "html"} <= links.keys()
            else None,
        )

        if not include_content:
            return Work.Parsed(detail, None)

        parsed_chapters = []
        for fallback_position, chapter in enumerate(
            soup.select("#chapters > div.chapter"), 1
        ):
            position = re.search(
                r"chapter-(?P<position>[0-9]+)", str(chapter.get("id", ""))
            )
            heading = chapter.select_one("div.chapter.preface.group h3.title")
            chapter_link = heading.select_one("a[href]") if heading else None
            chapter_id = (
                re.search(
                    r"/chapters/(?P<chapter_id>[0-9]+)", str(chapter_link["href"])
                )
                if chapter_link
                else None
            )
            title = heading.get_text(" ", strip=True) if heading else ""

            if chapter_link:
                title = title.removeprefix(
                    chapter_link.get_text(" ", strip=True)
                ).lstrip(": ")

            chapter_pseuds = []
            for anchor in chapter.select("h4.byline a[rel=author][href]"):
                with suppress(AO3InvalidURLError):
                    chapter_pseuds.append(
                        Pseud.Reference.from_link(
                            anchor.get_text(" ", strip=True), str(anchor["href"])
                        )
                    )
            chapter_summary = chapter.select_one(
                "div.summary.module blockquote.userstuff"
            )
            chapter_notes = chapter.select_one("div.notes.module blockquote.userstuff")

            if (
                content := chapter.select_one("div.userstuff.module[role=article]")
            ) is None:
                raise AO3ParseError(f"Chapter content for work {work_id} was not found")

            chapter_endnotes = chapter.select_one(
                "div.end.notes.module blockquote.userstuff"
            )
            parsed_chapters.append(
                Chapter.Data(
                    int(chapter_id["chapter_id"]) if chapter_id else None,
                    work_id,
                    int(position["position"]) if position else fallback_position,
                    urlparse(str(chapter_link["href"])).path if chapter_link else None,
                    title or None,
                    None,
                    tuple(chapter_pseuds) or tuple(pseuds),
                    Work.user_text(chapter_summary),
                    Work.fragment(chapter_summary),
                    Work.user_text(chapter_notes),
                    Work.fragment(chapter_notes),
                    Work.user_text(content) or "",
                    Work.fragment(content) or "",
                    Work.user_text(chapter_endnotes),
                    Work.fragment(chapter_endnotes),
                )
            )

        if not parsed_chapters and (
            content := soup.select_one("#chapters > div.userstuff")
        ):
            parsed_chapters.append(
                Chapter.Data(
                    None,
                    work_id,
                    1,
                    None,
                    None,
                    None,
                    tuple(pseuds),
                    None,
                    None,
                    None,
                    None,
                    Work.user_text(content) or "",
                    Work.fragment(content) or "",
                    None,
                    None,
                )
            )

        if not parsed_chapters:
            raise AO3ParseError(f"Chapter content for work {work_id} was not found")

        return Work.Parsed(detail, tuple(parsed_chapters))
