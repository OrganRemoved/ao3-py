import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ao3.collection import Collection
from ao3.exceptions import AO3InvalidURLError, AO3ParseError
from ao3.external_work import ExternalWork
from ao3.pseud import Pseud
from ao3.tag import Tag

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.series import Series
    from ao3.work import Work


class Bookmark:
    """An AO3 bookmark for a Work, Series, or ExternalWork."""

    class Page:
        class Data:
            __slots__ = ("bookmarks", "page", "page_count", "total")

            def __init__(
                self,
                page: int,
                page_count: int,
                total: int,
                bookmarks: "tuple[Bookmark.Data, ...]",
            ) -> None:
                self.page = page
                self.page_count = page_count
                self.total = total
                self.bookmarks = bookmarks

        __slots__ = ("bookmarks", "page", "page_count", "total")

        def __init__(
            self,
            page: int,
            page_count: int,
            total: int,
            bookmarks: "tuple[Bookmark, ...]",
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.total = total
            self.bookmarks = bookmarks

        def __iter__(self) -> "Iterator[Bookmark]":
            return iter(self.bookmarks)

        def __len__(self) -> int:
            return len(self.bookmarks)

    class Data:
        __slots__ = (
            "bookmarkable",
            "collections",
            "created",
            "id",
            "notes",
            "notes_html",
            "path",
            "private",
            "pseud",
            "recommended",
            "tags",
        )

        def __init__(
            self,
            bookmark_id: int | None,
            path: str | None,
            pseud: Pseud.Reference,
            created: date | None,
            tags: tuple[Tag.Reference, ...],
            collections: "tuple[Collection.Reference, ...]",
            notes: str | None,
            notes_html: str | None,
            recommended: bool,
            private: bool,
            bookmarkable: object | None,
        ) -> None:
            self.id = bookmark_id
            self.path = path
            self.pseud = pseud
            self.created = created
            self.tags = tags
            self.collections = collections
            self.notes = notes
            self.notes_html = notes_html
            self.recommended = recommended
            self.private = private
            self.bookmarkable = bookmarkable

    def __init__(
        self,
        bookmark_id: int | None,
        *,
        link: str | None = None,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = bookmark_id
        self.link = link or (
            f"/bookmarks/{bookmark_id}" if bookmark_id is not None else None
        )
        self.view_adult = view_adult
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @classmethod
    def from_url(
        cls, url: str, *, view_adult: bool = True, client: "AO3Client | None" = None
    ) -> "Bookmark":
        if not (
            match := re.search(
                r"/bookmarks/(?P<bookmark_id>[0-9]+)",
                "/" + urlparse(url).path.lstrip("/"),
            )
        ):
            raise AO3InvalidURLError(f"Not an AO3 bookmark URL: {url}")

        return cls(int(match["bookmark_id"]), view_adult=view_adult, client=client)

    @classmethod
    def from_data(
        cls,
        data: "Bookmark.Data",
        *,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Bookmark":
        bookmark = cls(data.id, link=data.path, view_adult=view_adult, client=client)
        bookmark.detail = data
        return bookmark

    @property
    def url(self) -> str | None:
        return f"{self.client.base_url}{self.link}" if self.link else None

    @cached_property
    def detail(self) -> "Bookmark.Data":
        if self.id is None:
            raise AO3ParseError("AO3 did not expose an ID for this bookmark")

        return self.client.fetch_bookmark(self)

    @cached_property
    def pseud(self) -> Pseud:
        return Pseud.from_reference(
            self.detail.pseud, view_adult=self.view_adult, client=self.client
        )

    @property
    def created(self) -> date | None:
        return self.detail.created

    @cached_property
    def tags(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in self.detail.tags
        )

    @cached_property
    def collections(self) -> tuple[Collection, ...]:
        return tuple(
            Collection.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in self.detail.collections
        )

    @property
    def notes(self) -> str | None:
        return self.detail.notes

    @property
    def notes_html(self) -> str | None:
        return self.detail.notes_html

    @property
    def recommended(self) -> bool:
        return self.detail.recommended

    @property
    def private(self) -> bool:
        return self.detail.private

    @cached_property
    def bookmarkable(self) -> "Work | Series | ExternalWork | None":
        from ao3.series import Series
        from ao3.work import Work

        if isinstance(self.detail.bookmarkable, Work.Data):
            return Work.from_summary(
                self.detail.bookmarkable, view_adult=self.view_adult, client=self.client
            )

        if isinstance(self.detail.bookmarkable, Series.Data):
            return Series.from_summary(
                self.detail.bookmarkable, view_adult=self.view_adult, client=self.client
            )

        if isinstance(self.detail.bookmarkable, ExternalWork.Data):
            return ExternalWork.from_summary(
                self.detail.bookmarkable, view_adult=self.view_adult, client=self.client
            )

    def update(
        self,
        *,
        notes: str | None = None,
        tags: str | Iterable[str | Tag] | None = None,
        collections: str | Iterable[str | Collection] | None = None,
        private: bool | None = None,
        recommended: bool | None = None,
        pseud_id: int | None = None,
    ) -> "Bookmark":
        detail = self.client.update_bookmark(
            self,
            notes=notes,
            tags=tags,
            collections=collections,
            private=private,
            recommended=recommended,
            pseud_id=pseud_id,
        )

        for attribute in ("detail", "pseud", "tags", "collections", "bookmarkable"):
            self.__dict__.pop(attribute, None)

        self.id = detail.id
        self.link = detail.path
        self.detail = detail

        return self

    def delete(self) -> None:
        self.client.delete_bookmark(self)

        for attribute in ("detail", "pseud", "tags", "collections", "bookmarkable"):
            self.__dict__.pop(attribute, None)

    def __repr__(self) -> str:
        return f"Bookmark(id={self.id!r})"

    @staticmethod
    def parse_blurb(article: BeautifulSoup) -> "Bookmark.Data | None":
        user_module = article.select_one("div.user.module.group") or article

        if (
            pseud_link := user_module.select_one("h5.byline.heading a[href^='/users/']")
        ) is None:
            return None

        try:
            pseud = Pseud.Reference.from_link(
                pseud_link.get_text(" ", strip=True), str(pseud_link["href"])
            )
        except AO3InvalidURLError:
            return None

        bookmark_id = (
            int(bookmark_match["bookmark_id"])
            if (
                bookmark_match := re.fullmatch(
                    r"bookmark_(?P<bookmark_id>[0-9]+)", str(article.get("id", ""))
                )
            )
            else None
        )

        created = None

        if date_element := user_module.select_one("p.datetime"):
            for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    created = datetime.strptime(
                        date_element.get_text(" ", strip=True), date_format
                    ).date()
                    break
                except ValueError:
                    pass

        tags = tuple(
            Tag.Reference(
                anchor.get_text(" ", strip=True), urlparse(str(anchor["href"])).path
            )
            for anchor in user_module.select("ul.meta.tags.commas a.tag[href]")
        )
        collections = []
        for anchor in user_module.select("ul.meta.commas a[href^='/collections/']"):
            path = urlparse(str(anchor["href"])).path
            parts = path.split("/")

            if len(parts) > 2:
                collections.append(
                    Collection.Reference(
                        parts[2], anchor.get_text(" ", strip=True), path
                    )
                )

        notes = user_module.select_one(
            "blockquote.userstuff.notes, blockquote.userstuff.summary"
        )
        notes_html = (
            "".join(str(child) for child in notes.contents).strip() or None
            if notes is not None
            else None
        )
        notes_text = None

        if notes_html:
            text_soup = BeautifulSoup(notes_html, "lxml")
            for br in text_soup.find_all("br"):
                br.replace_with("\n")
            for block in text_soup.find_all(
                ["blockquote", "div", "h1", "h2", "h3", "h4", "li", "p", "pre"]
            ):
                block.append("\n")
            lines = [
                re.sub(r"[^\S\n]+", " ", line).strip()
                for line in text_soup.get_text().splitlines()
            ]
            notes_text = "\n".join(line for line in lines if line) or None

        bookmarkable = None

        if article.select_one("a[href*='/works/']"):
            from ao3.work import Work

            bookmarkable = Work.parse_blurb(article)
        elif article.select_one("a[href*='/series/']"):
            from ao3.series import Series

            bookmarkable = Series.parse_blurb(article)
        elif (
            article.select_one("a[href*='/external_works/']")
            or str(article.get("class", "")).find("external-work") >= 0
        ):
            bookmarkable = ExternalWork.parse_blurb(article)

        classes = {str(value) for value in article.get("class", [])}
        status = article.select_one("p.status")
        status_text = status.get_text(" ", strip=True).lower() if status else ""

        return Bookmark.Data(
            bookmark_id,
            f"/bookmarks/{bookmark_id}" if bookmark_id else None,
            pseud,
            created,
            tags,
            tuple(collections),
            notes_text,
            notes_html,
            "rec" in classes
            or "recommend" in status_text
            or bool(status and status.select_one("span.recommended")),
            "private" in classes
            or "private" in status_text
            or bool(status and status.select_one("span.private")),
            bookmarkable,
        )

    @staticmethod
    def parse_index(content: bytes | str, requested_page: int) -> "Bookmark.Page.Data":
        soup = BeautifulSoup(content, "lxml")

        if (
            listing := soup.select_one(
                "ol.bookmark.index.group, ul.bookmark.index.group"
            )
        ) is None:
            raise AO3ParseError("The AO3 bookmark index was not found")

        bookmarks = tuple(
            parsed
            for article in listing.select(":scope > li[role=article]")
            if (parsed := Bookmark.parse_blurb(article)) is not None
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

        heading = soup.select_one("h2.heading")
        total_match = re.search(
            r"(?P<count>[0-9][0-9,]*)\s+Bookmarks?\b",
            heading.get_text(" ", strip=True) if heading else "",
            re.IGNORECASE,
        )

        return Bookmark.Page.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            int(total_match["count"].replace(",", ""))
            if total_match
            else len(bookmarks),
            bookmarks,
        )

    @staticmethod
    def parse_page(content: bytes | str, bookmark_id: int) -> "Bookmark.Data":
        soup = BeautifulSoup(content, "lxml")

        if (article := soup.select_one(f"li#bookmark_{bookmark_id}")) is None or (
            data := Bookmark.parse_blurb(article)
        ) is None:
            raise AO3ParseError(f"Bookmark {bookmark_id} was not found")

        return data
