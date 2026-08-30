import re
from collections.abc import Iterator
from contextlib import suppress
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ao3.exceptions import AO3AuthenticationError, AO3InvalidURLError, AO3ParseError
from ao3.pseud import Pseud

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark
    from ao3.subscription import Subscription
    from ao3.work import Work


class Series:
    """An AO3 series with lazy metadata, ordered works, and bookmarks."""

    class Reference:
        __slots__ = ("id", "path", "position", "title")

        def __init__(
            self,
            series_id: int,
            title: str,
            path: str | None = None,
            position: int | None = None,
        ) -> None:
            self.id = series_id
            self.title = title
            self.path = path or f"/series/{series_id}"
            self.position = position

    class Page:
        class Data:
            __slots__ = ("page", "page_count", "series", "total")

            def __init__(
                self,
                page: int,
                page_count: int,
                total: int,
                series: "tuple[Series.Data, ...]",
            ) -> None:
                self.page = page
                self.page_count = page_count
                self.total = total
                self.series = series

        __slots__ = ("page", "page_count", "series", "total")

        def __init__(
            self, page: int, page_count: int, total: int, series: "tuple[Series, ...]"
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.total = total
            self.series = series

        def __iter__(self) -> "Iterator[Series]":
            return iter(self.series)

        def __len__(self) -> int:
            return len(self.series)

    class Parsed:
        __slots__ = ("detail", "works")

        def __init__(self, detail: "Series.Data", works: "Work.Page.Data") -> None:
            self.detail = detail
            self.works = works

    class Data:
        __slots__ = (
            "begun",
            "bookmarks_count",
            "complete",
            "id",
            "notes",
            "notes_html",
            "path",
            "pseuds",
            "restricted",
            "summary",
            "summary_html",
            "title",
            "updated",
            "words",
            "works_count",
        )

        def __init__(
            self,
            series_id: int,
            path: str,
            title: str,
            pseuds: tuple[Pseud.Reference, ...],
            begun: date | None,
            updated: date | None,
            summary: str | None,
            summary_html: str | None,
            notes: str | None,
            notes_html: str | None,
            words: int,
            works_count: int,
            bookmarks_count: int,
            complete: bool,
            restricted: bool,
        ) -> None:
            self.id = series_id
            self.path = path
            self.title = title
            self.pseuds = pseuds
            self.begun = begun
            self.updated = updated
            self.summary = summary
            self.summary_html = summary_html
            self.notes = notes
            self.notes_html = notes_html
            self.words = words
            self.works_count = works_count
            self.bookmarks_count = bookmarks_count
            self.complete = complete
            self.restricted = restricted

    def __init__(
        self,
        series_id: int,
        *,
        link: str | None = None,
        title: str | None = None,
        position: int | None = None,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = series_id
        self.link = link or f"/series/{series_id}"

        if title is not None:
            self.__dict__["title"] = title

        self.position = position
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
    ) -> "Series":
        if not (
            match := re.search(
                r"/series/(?P<series_id>[0-9]+)", "/" + urlparse(url).path.lstrip("/")
            )
        ):
            raise AO3InvalidURLError(f"Not an AO3 series URL: {url}")

        return cls(
            int(match["series_id"]), page=page, view_adult=view_adult, client=client
        )

    @classmethod
    def from_reference(
        cls,
        reference: "Series.Reference",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Series":
        return cls(
            reference.id,
            link=reference.path,
            title=reference.title,
            position=reference.position,
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_summary(
        cls,
        summary: "Series.Data",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Series":
        series = cls(
            summary.id,
            link=summary.path,
            title=summary.title,
            page=page,
            view_adult=view_adult,
            client=client,
        )
        series._summary = summary
        return series

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def detail(self) -> "Series.Data":
        detail, self.works_page = self.client.fetch_series(self)
        self.__dict__["title"] = detail.title
        return detail

    @cached_property
    def title(self) -> str:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).title

    @property
    def begun(self) -> date | None:
        return self.detail.begun

    @property
    def updated(self) -> date | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).updated

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
    def notes(self) -> str | None:
        return self.detail.notes

    @property
    def notes_html(self) -> str | None:
        return self.detail.notes_html

    @property
    def words(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).words

    @property
    def works_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).works_count

    @property
    def bookmarks_count(self) -> int:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).bookmarks_count

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

    @cached_property
    def works_page(self) -> "Work.Page":
        self.detail, works_page = self.client.fetch_series(self)
        self.__dict__["title"] = self.detail.title
        return works_page

    @property
    def works(self) -> "tuple[Work, ...]":
        return self.works_page.works

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_series_bookmarks(self)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    def subscribe(self) -> "Subscription":
        return self.client.create_subscription(self)

    def unsubscribe(self) -> None:
        self.client.delete_subscription(self)

    def copy(self, *, page: int | None = None) -> "Series":
        return Series(
            self.id,
            link=self.link,
            title=self.__dict__.get("title"),
            position=self.position,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            client=self.client,
        )

    def __repr__(self) -> str:
        title = (
            f", title={self.__dict__['title']!r}" if "title" in self.__dict__ else ""
        )
        return f"Series(id={self.id}{title})"

    @staticmethod
    def parse_blurb(article: BeautifulSoup) -> "Series.Data | None":
        if (
            (heading := article.select_one("div.header.module h4.heading")) is None
            or (title_link := heading.select_one("a[href*='/series/']")) is None
            or not (
                match := re.search(
                    r"/series/(?P<series_id>[0-9]+)", str(title_link.get("href", ""))
                )
            )
        ):
            return None

        summary = article.select_one("blockquote.userstuff.summary")
        summary_html = (
            "".join(str(child) for child in summary.contents).strip() or None
            if summary is not None
            else None
        )
        stats = article.select_one("dl.stats")
        updated = None

        if date_element := article.select_one("p.datetime"):
            for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    updated = datetime.strptime(
                        date_element.get_text(" ", strip=True), date_format
                    ).date()
                    break
                except ValueError:
                    pass

        pseuds = []
        for anchor in heading.select("a[rel=author][href]"):
            with suppress(AO3InvalidURLError):
                pseuds.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        def stat(selector: str) -> int:
            if (
                stats
                and (element := stats.select_one(selector)) is not None
                and (value := re.search(r"(?P<count>[0-9][0-9,]*)", element.get_text()))
            ):
                return int(value["count"].replace(",", ""))
            return 0

        return Series.Data(
            int(match["series_id"]),
            f"/series/{match['series_id']}",
            title_link.get_text(" ", strip=True),
            tuple(pseuds),
            None,
            updated,
            summary.get_text(" ", strip=True) or None if summary else None,
            summary_html,
            None,
            None,
            stat("dd.words"),
            stat("dd.works"),
            stat("dd.bookmarks"),
            bool(article.select_one("span.complete-yes")),
            bool(article.select_one("img[title='Restricted']")),
        )

    @staticmethod
    def parse_index(content: bytes | str, requested_page: int) -> "Series.Page.Data":
        soup = BeautifulSoup(content, "lxml")
        listing = soup.select_one("ul.series.index.group")

        articles = (
            listing.select(":scope > li[role=article]")
            if listing is not None
            else soup.select("li[id^=series_][role=article]")
        )

        if listing is None and not articles:
            raise AO3ParseError("The AO3 series index was not found")

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
            r"(?P<count>[0-9][0-9,]*)\s+Series\b",
            heading.get_text(" ", strip=True) if heading else "",
            re.IGNORECASE,
        )
        series = tuple(
            parsed
            for article in articles
            if (parsed := Series.parse_blurb(article)) is not None
        )

        return Series.Page.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            int(total_match["count"].replace(",", "")) if total_match else len(series),
            series,
        )

    @staticmethod
    def parse_page(
        content: bytes | str, series_id: int, requested_page: int
    ) -> "Series.Parsed":
        from ao3.work import Work

        soup = BeautifulSoup(content, "lxml")

        if (meta := soup.select_one("dl.series.meta.group")) is None or (
            title_heading := soup.select_one("h2.heading")
        ) is None:
            if soup.select_one("form#new_user, form.new_user"):
                raise AO3AuthenticationError(
                    f"Series {series_id} requires an AO3 login"
                )
            raise AO3ParseError(f"Series metadata for {series_id} was not found")

        values = {}
        for label in meta.select(":scope > dt"):
            if (value := label.find_next_sibling("dd")) is not None:
                values[label.get_text(" ", strip=True).rstrip(":").lower()] = value

        begun = None
        updated = None
        for key, target in (("series begun", "begun"), ("series updated", "updated")):
            if (element := values.get(key)) is None:
                continue
            for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                try:
                    parsed_date = datetime.strptime(
                        element.get_text(" ", strip=True), date_format
                    ).date()

                    if target == "begun":
                        begun = parsed_date
                    else:
                        updated = parsed_date
                    break
                except ValueError:
                    pass

        summary = values.get("description")
        summary = summary.select_one("blockquote.userstuff") if summary else None
        notes = values.get("notes")
        notes = notes.select_one("blockquote.userstuff") if notes else None
        rendered = []
        for element in (summary, notes):
            if element is None:
                rendered.append((None, None))
                continue

            if not (
                content_html := "".join(
                    str(child) for child in element.contents
                ).strip()
                or None
            ):
                rendered.append((None, None))
                continue

            text_soup = BeautifulSoup(content_html, "lxml")
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
            rendered.append(
                ("\n".join(line for line in lines if line) or None, content_html)
            )

        pseuds = []

        if (
            creator_value := values.get("creator") or values.get("creators")
        ) is not None:
            for anchor in creator_value.select("a[rel=author][href]"):
                with suppress(AO3InvalidURLError):
                    pseuds.append(
                        Pseud.Reference.from_link(
                            anchor.get_text(" ", strip=True), str(anchor["href"])
                        )
                    )

        stats = meta.select_one("dd.stats dl.stats")

        def stat(selector: str) -> int:
            if (
                stats
                and (element := stats.select_one(selector)) is not None
                and (value := re.search(r"(?P<count>[0-9][0-9,]*)", element.get_text()))
            ):
                return int(value["count"].replace(",", ""))
            return 0

        complete = False

        if stats is not None:
            for label in stats.select(":scope > dt"):
                if label.get_text(" ", strip=True).rstrip(":").lower() == "complete":
                    value = label.find_next_sibling("dd")
                    complete = bool(
                        value and value.get_text(" ", strip=True).lower() == "yes"
                    )
                    break

        detail = Series.Data(
            series_id,
            f"/series/{series_id}",
            title_heading.get_text(" ", strip=True),
            tuple(pseuds),
            begun,
            updated,
            rendered[0][0],
            rendered[0][1],
            rendered[1][0],
            rendered[1][1],
            stat("dd.words"),
            stat("dd.works"),
            stat("dd.bookmarks"),
            complete,
            bool(title_heading.select_one("img[title='Restricted']")),
        )

        listing = soup.select_one("ul.series.work.index.group")
        works = tuple(
            parsed
            for article in (
                listing.select(":scope > li[role=article]") if listing else []
            )
            if (parsed := Work.parse_blurb(article)) is not None
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

        return Series.Parsed(
            detail,
            Work.Page.Data(
                int(current.get_text(strip=True))
                if current and current.get_text(strip=True).isdigit()
                else requested_page,
                max(pages, default=1),
                detail.works_count,
                works,
            ),
        )
