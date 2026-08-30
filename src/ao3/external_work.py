import re
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ao3.exceptions import AO3InvalidURLError, AO3ParseError
from ao3.language import Language
from ao3.tag import Tag, TagKind

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark


class ExternalWork:
    """A work hosted outside AO3 and represented by an AO3 bookmark record."""

    class Data:
        __slots__ = (
            "author",
            "bookmarks_count",
            "created",
            "id",
            "language",
            "path",
            "related_works_count",
            "summary",
            "summary_html",
            "tags",
            "title",
            "url",
        )

        def __init__(
            self,
            external_work_id: int,
            path: str,
            url: str,
            title: str,
            author: str,
            tags: tuple[Tag.Reference, ...],
            summary: str | None,
            summary_html: str | None,
            language: Language.Reference | None,
            created: date | None,
            bookmarks_count: int,
            related_works_count: int,
        ) -> None:
            self.id = external_work_id
            self.path = path
            self.url = url
            self.title = title
            self.author = author
            self.tags = tags
            self.summary = summary
            self.summary_html = summary_html
            self.language = language
            self.created = created
            self.bookmarks_count = bookmarks_count
            self.related_works_count = related_works_count

    def __init__(
        self,
        external_work_id: int,
        *,
        link: str | None = None,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = external_work_id
        self.link = link or f"/external_works/{external_work_id}"
        self.page = page
        self.view_adult = view_adult
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "ExternalWork":
        if not (
            match := re.search(
                r"/external_works/(?P<external_work_id>[0-9]+)",
                "/" + urlparse(url).path.lstrip("/"),
            )
        ):
            raise AO3InvalidURLError(f"Not an AO3 external work URL: {url}")

        return cls(
            int(match["external_work_id"]),
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_summary(
        cls,
        summary: "ExternalWork.Data",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "ExternalWork":
        external_work = cls(
            summary.id,
            link=summary.path,
            page=page,
            view_adult=view_adult,
            client=client,
        )
        external_work._summary = summary
        return external_work

    @property
    def ao3_url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def detail(self) -> "ExternalWork.Data":
        return self.client.fetch_external_work(self)

    @property
    def url(self) -> str:
        if detail := self.__dict__.get("detail"):
            return detail.url

        if summary := self.__dict__.get("_summary"):
            return summary.url

        return self.detail.url

    @property
    def title(self) -> str:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).title

    @property
    def author(self) -> str:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).author

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
    def created(self) -> date | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).created

    @property
    def bookmarks_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).bookmarks_count

    @property
    def related_works_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).related_works_count

    @property
    def tags(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).tags
        )

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_external_work_bookmarks(self)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    def copy(self, *, page: int | None = None) -> "ExternalWork":
        return ExternalWork(
            self.id,
            link=self.link,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            client=self.client,
        )

    def __repr__(self) -> str:
        data = self.__dict__.get("detail") or self.__dict__.get("_summary")
        title = f", title={data.title!r}" if data else ""
        return f"ExternalWork(id={self.id}{title})"

    @staticmethod
    def parse_blurb(article: BeautifulSoup) -> "ExternalWork.Data | None":
        if (heading := article.select_one("div.header.module h4.heading")) is None:
            return None

        ao3_link = heading.select_one("a[href*='/external_works/']")

        if not (
            id_match := re.search(
                r"external_work_(?P<external_work_id>[0-9]+)",
                str(article.get("id", "")),
            )
            or (
                re.search(
                    r"/external_works/(?P<external_work_id>[0-9]+)",
                    str(ao3_link.get("href", "")),
                )
                if ao3_link
                else None
            )
        ):
            return None

        external_work_id = int(id_match["external_work_id"])

        if (title_link := ao3_link or heading.select_one("a[href]")) is None:
            return None

        target_url = str(title_link["href"])

        if target_url.startswith("/") and (
            external_target := article.select_one("a[href^='http']")
        ):
            target_url = str(external_target["href"])

        heading_copy = BeautifulSoup(str(heading), "lxml")

        if copied_link := heading_copy.select_one("a"):
            copied_link.extract()

        author = re.sub(
            r"^\s*by\s+",
            "",
            heading_copy.get_text(" ", strip=True),
            flags=re.IGNORECASE,
        )

        tags = []
        selectors: tuple[tuple[str, TagKind], ...] = (
            ("h5.fandoms a.tag[href]", "fandom"),
            ("ul.tags > li.warnings a.tag[href]", "warning"),
            ("ul.tags > li.relationships a.tag[href]", "relationship"),
            ("ul.tags > li.characters a.tag[href]", "character"),
            ("ul.tags > li.freeforms a.tag[href]", "freeform"),
        )
        for selector, kind in selectors:
            for anchor in article.select(selector):
                name = anchor.get_text(" ", strip=True)
                tags.append(
                    Tag.Reference(name, urlparse(str(anchor["href"])).path, kind)
                )

        summary = article.select_one("blockquote.userstuff.summary")
        summary_html = (
            "".join(str(child) for child in summary.contents).strip() or None
            if summary is not None
            else None
        )

        created = None

        if date_element := article.select_one("p.datetime"):
            for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    created = datetime.strptime(
                        date_element.get_text(" ", strip=True), date_format
                    ).date()
                    break
                except ValueError:
                    pass

        def stat(selector: str) -> int:
            if (element := article.select_one(selector)) is not None and (
                value := re.search(r"(?P<count>[0-9][0-9,]*)", element.get_text())
            ):
                return int(value["count"].replace(",", ""))
            return 0

        return ExternalWork.Data(
            external_work_id,
            f"/external_works/{external_work_id}",
            target_url,
            title_link.get_text(" ", strip=True),
            author,
            tuple(tags),
            summary.get_text(" ", strip=True) or None if summary else None,
            summary_html,
            Language.Reference.from_element(article.select_one("dd.language")),
            created,
            stat("dd.bookmarks"),
            stat("dd.inspired"),
        )

    @staticmethod
    def parse_page(content: bytes | str, external_work_id: int) -> "ExternalWork.Data":
        soup = BeautifulSoup(content, "lxml")

        if (
            article := soup.select_one(
                f"li#external_work_{external_work_id}, "
                "ol.work.index.group > li[role=article]"
            )
        ) is None or (data := ExternalWork.parse_blurb(article)) is None:
            raise AO3ParseError(
                f"External work metadata for {external_work_id} was not found"
            )

        return data
