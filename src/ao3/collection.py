import re
from collections.abc import Iterator
from contextlib import suppress
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse

from bs4 import BeautifulSoup

from ao3.exceptions import AO3InvalidURLError, AO3ParseError
from ao3.pseud import Pseud
from ao3.tag import Tag

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark
    from ao3.work import Work


class Collection:
    """An AO3 collection or challenge collection."""

    class Reference:
        __slots__ = ("name", "path", "title")

        def __init__(self, name: str, title: str, path: str | None = None) -> None:
            self.name = name
            self.title = title
            self.path = path or f"/collections/{quote(name, safe='')}"

    class Page:
        class Data:
            __slots__ = ("collections", "page", "page_count", "total")

            def __init__(
                self,
                page: int,
                page_count: int,
                total: int,
                collections: "tuple[Collection.Data, ...]",
            ) -> None:
                self.page = page
                self.page_count = page_count
                self.total = total
                self.collections = collections

        __slots__ = ("collections", "page", "page_count", "total")

        def __init__(
            self,
            page: int,
            page_count: int,
            total: int,
            collections: "tuple[Collection, ...]",
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.total = total
            self.collections = collections

        def __iter__(self) -> "Iterator[Collection]":
            return iter(self.collections)

        def __len__(self) -> int:
            return len(self.collections)

    class Data:
        __slots__ = (
            "active_since",
            "anonymous",
            "bookmarks_count",
            "challenge_type",
            "closed",
            "contact",
            "description",
            "description_html",
            "faq",
            "faq_html",
            "intro",
            "intro_html",
            "maintainers",
            "moderated",
            "name",
            "path",
            "rules",
            "rules_html",
            "subcollections_count",
            "tags",
            "title",
            "unrevealed",
            "updated",
            "works_count",
        )

        def __init__(
            self,
            name: str,
            path: str,
            title: str,
            description: str | None,
            description_html: str | None,
            active_since: date | None,
            updated: date | None,
            tags: tuple[Tag.Reference, ...],
            maintainers: tuple[Pseud.Reference, ...],
            contact: str | None,
            intro: str | None,
            intro_html: str | None,
            faq: str | None,
            faq_html: str | None,
            rules: str | None,
            rules_html: str | None,
            closed: bool,
            moderated: bool,
            unrevealed: bool,
            anonymous: bool,
            challenge_type: str | None,
            works_count: int | None,
            bookmarks_count: int | None,
            subcollections_count: int | None,
        ) -> None:
            self.name = name
            self.path = path
            self.title = title
            self.description = description
            self.description_html = description_html
            self.active_since = active_since
            self.updated = updated
            self.tags = tags
            self.maintainers = maintainers
            self.contact = contact
            self.intro = intro
            self.intro_html = intro_html
            self.faq = faq
            self.faq_html = faq_html
            self.rules = rules
            self.rules_html = rules_html
            self.closed = closed
            self.moderated = moderated
            self.unrevealed = unrevealed
            self.anonymous = anonymous
            self.challenge_type = challenge_type
            self.works_count = works_count
            self.bookmarks_count = bookmarks_count
            self.subcollections_count = subcollections_count

    def __init__(
        self,
        name: str,
        *,
        link: str | None = None,
        title: str | None = None,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.name = name
        self.link = link or f"/collections/{quote(name, safe='')}"

        if title is not None:
            self.__dict__["title"] = title

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
    ) -> "Collection":
        path = "/" + urlparse(url).path.lstrip("/")
        parts = path.split("/")

        if len(parts) < 3 or parts[1] != "collections" or not parts[2]:
            raise AO3InvalidURLError(f"Not an AO3 collection URL: {url}")

        name = unquote(parts[2])

        return cls(
            name,
            link=f"/collections/{quote(name, safe='')}",
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_reference(
        cls,
        reference: "Collection.Reference",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Collection":
        return cls(
            reference.name,
            link=reference.path,
            title=reference.title,
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_summary(
        cls,
        summary: "Collection.Data",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Collection":
        collection = cls(
            summary.name,
            link=summary.path,
            title=summary.title,
            page=page,
            view_adult=view_adult,
            client=client,
        )
        collection._summary = summary
        return collection

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def detail(self) -> "Collection.Data":
        detail = self.client.fetch_collection(self)
        self.__dict__["title"] = detail.title
        return detail

    @cached_property
    def title(self) -> str:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).title

    @property
    def description(self) -> str | None:
        return self.detail.description

    @property
    def description_html(self) -> str | None:
        return self.detail.description_html

    @property
    def active_since(self) -> date | None:
        return self.detail.active_since

    @property
    def updated(self) -> date | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).updated

    @property
    def contact(self) -> str | None:
        return self.detail.contact

    @property
    def intro(self) -> str | None:
        return self.detail.intro

    @property
    def intro_html(self) -> str | None:
        return self.detail.intro_html

    @property
    def faq(self) -> str | None:
        return self.detail.faq

    @property
    def faq_html(self) -> str | None:
        return self.detail.faq_html

    @property
    def rules(self) -> str | None:
        return self.detail.rules

    @property
    def rules_html(self) -> str | None:
        return self.detail.rules_html

    @property
    def closed(self) -> bool:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).closed

    @property
    def moderated(self) -> bool:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).moderated

    @property
    def unrevealed(self) -> bool:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).unrevealed

    @property
    def anonymous(self) -> bool:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).anonymous

    @property
    def challenge_type(self) -> str | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).challenge_type

    @property
    def subcollections_count(self) -> int | None:
        return (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        ).subcollections_count

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

    @property
    def maintainers(self) -> tuple[Pseud, ...]:
        return tuple(
            Pseud.from_reference(
                reference, view_adult=self.view_adult, client=self.client
            )
            for reference in (
                self.__dict__.get("detail")
                or self.__dict__.get("_summary")
                or self.detail
            ).maintainers
        )

    @cached_property
    def works_page(self) -> "Work.Page":
        return self.client.fetch_collection_works(self)

    @property
    def works(self) -> "tuple[Work, ...]":
        return self.works_page.works

    @property
    def works_count(self) -> int:
        data = (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        )

        if data.works_count is not None:
            return data.works_count

        return self.works_page.total

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_collection_bookmarks(self)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    @property
    def bookmarks_count(self) -> int:
        data = (
            self.__dict__.get("detail") or self.__dict__.get("_summary") or self.detail
        )

        if data.bookmarks_count is not None:
            return data.bookmarks_count

        return self.bookmarks_page.total

    @cached_property
    def subcollections_page(self) -> "Collection.Page":
        return self.client.fetch_subcollections(self)

    @property
    def subcollections(self) -> tuple["Collection", ...]:
        return self.subcollections_page.collections

    def copy(self, *, page: int | None = None) -> "Collection":
        return Collection(
            self.name,
            link=self.link,
            title=self.__dict__.get("title"),
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            client=self.client,
        )

    def __repr__(self) -> str:
        title = (
            f", title={self.__dict__['title']!r}" if "title" in self.__dict__ else ""
        )
        return f"Collection(name={self.name!r}{title})"

    @staticmethod
    def parse_blurb(article: BeautifulSoup) -> "Collection.Data | None":
        if (heading := article.select_one("div.header.module h4.heading")) is None or (
            title_link := heading.select_one("a[href*='/collections/']")
        ) is None:
            return None

        path = urlparse(str(title_link["href"])).path
        parts = path.split("/")

        if len(parts) < 3:
            return None

        name = (
            name_element.get_text(" ", strip=True).strip("()")
            if (name_element := heading.select_one("span.name"))
            else unquote(parts[2])
        )

        description = article.select_one("blockquote.userstuff.summary")
        description_html = (
            "".join(str(child) for child in description.contents).strip() or None
            if description is not None
            else None
        )
        type_text = (
            type_element.get_text(" ", strip=True).lower()
            if (type_element := article.select_one("p.type"))
            else ""
        )
        maintainers = []
        for anchor in heading.select("a.owner[href], a.mod[href]"):
            with suppress(AO3InvalidURLError):
                maintainers.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        tags = tuple(
            Tag.Reference(
                anchor.get_text(" ", strip=True), urlparse(str(anchor["href"])).path
            )
            for anchor in article.select("h5.tags.heading a.tag[href]")
        )

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

        def stat(selector: str) -> int | None:
            if (element := article.select_one(selector)) is not None and (
                value := re.search(r"(?P<count>[0-9][0-9,]*)", element.get_text())
            ):
                return int(value["count"].replace(",", ""))

        challenge_type = None

        if "gift exchange challenge" in type_text:
            challenge_type = "GiftExchange"
        elif "prompt meme challenge" in type_text:
            challenge_type = "PromptMeme"

        return Collection.Data(
            name,
            f"/collections/{quote(name, safe='')}",
            title_link.get_text(" ", strip=True),
            description.get_text(" ", strip=True) or None if description else None,
            description_html,
            None,
            updated,
            tags,
            tuple(maintainers),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "closed" in type_text and "open" not in type_text,
            "moderated" in type_text and "unmoderated" not in type_text,
            "unrevealed" in type_text,
            "anonymous" in type_text,
            challenge_type,
            stat("dd.works"),
            stat("dd.bookmarks"),
            stat("dd.collections"),
        )

    @staticmethod
    def parse_index(
        content: bytes | str, requested_page: int
    ) -> "Collection.Page.Data":
        soup = BeautifulSoup(content, "lxml")
        listing = soup.select_one("ul.collection.picture.index.group")

        if not listing and not soup.select_one("h2.heading"):
            raise AO3ParseError("The AO3 collection index was not found")

        collections = tuple(
            parsed
            for article in (
                listing.select(":scope > li[role=article]") if listing else ()
            )
            if (parsed := Collection.parse_blurb(article)) is not None
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

        heading = soup.select_one("h3.heading")
        total_match = re.search(
            r"(?P<count>[0-9][0-9,]*)\s+Collections?\b",
            heading.get_text(" ", strip=True) if heading else "",
            re.IGNORECASE,
        )

        return Collection.Page.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            int(total_match["count"].replace(",", ""))
            if total_match
            else len(collections),
            collections,
        )

    @staticmethod
    def parse_profile(content: bytes | str, name: str) -> "Collection.Data":
        soup = BeautifulSoup(content, "lxml")

        if (profile := soup.select_one("div.collection.home.profile")) is None:
            raise AO3ParseError(f"Collection profile for {name!r} was not found")

        header = profile.select_one("div.primary.header.module")
        title_link = header.select_one("h2.heading a") if header else None
        title_heading = header.select_one("h2.heading") if header else None
        title = (
            title_link.get_text(" ", strip=True)
            if title_link
            else title_heading.get_text(" ", strip=True)
            if title_heading
            else name
        )
        description = header.select_one("blockquote.userstuff") if header else None
        description_html = (
            "".join(str(child) for child in description.contents).strip() or None
            if description is not None
            else None
        )
        type_text = (
            type_element.get_text(" ", strip=True).lower()
            if header and (type_element := header.select_one("p.type"))
            else ""
        )

        active_since = None
        contact = None

        if (meta := profile.select_one("dl.meta.group")) is not None:
            for label in meta.select(":scope > dt"):
                if (value := label.find_next_sibling("dd")) is None:
                    continue

                label_text = label.get_text(" ", strip=True).rstrip(":").lower()

                if label_text == "active since":
                    for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                        try:
                            active_since = datetime.strptime(
                                value.get_text(" ", strip=True), date_format
                            ).date()
                            break
                        except ValueError:
                            pass
                elif label_text == "contact":
                    contact = value.get_text(" ", strip=True) or None

        tags = tuple(
            Tag.Reference(
                anchor.get_text(" ", strip=True), urlparse(str(anchor["href"])).path
            )
            for anchor in profile.select("dl.meta dd ul.tags a[href]")
        )
        maintainers = []
        for anchor in profile.select("dd.maintainers a[href]"):
            with suppress(AO3InvalidURLError):
                maintainers.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        sections = []
        for section_id in ("intro", "faq", "rules"):
            section = profile.select_one(f"div#{section_id} blockquote.userstuff")
            sections.append(
                (
                    section.get_text(" ", strip=True) or None,
                    "".join(str(child) for child in section.contents).strip() or None,
                )
                if section
                else (None, None)
            )

        challenge_type = None

        if "gift exchange challenge" in type_text:
            challenge_type = "GiftExchange"
        elif "prompt meme challenge" in type_text:
            challenge_type = "PromptMeme"

        return Collection.Data(
            name,
            f"/collections/{quote(name, safe='')}",
            title,
            description.get_text(" ", strip=True) or None if description else None,
            description_html,
            active_since,
            None,
            tags,
            tuple(maintainers),
            contact,
            sections[0][0],
            sections[0][1],
            sections[1][0],
            sections[1][1],
            sections[2][0],
            sections[2][1],
            "closed" in type_text and "open" not in type_text,
            "moderated" in type_text and "unmoderated" not in type_text,
            "unrevealed" in type_text,
            "anonymous" in type_text,
            challenge_type,
            None,
            None,
            None,
        )
