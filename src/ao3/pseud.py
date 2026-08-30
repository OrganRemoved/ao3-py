import re
from collections.abc import Iterator
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse

from bs4 import BeautifulSoup

from ao3.exceptions import AO3InvalidURLError, AO3ParseError

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark
    from ao3.series import Series
    from ao3.user import User
    from ao3.work import Work


class Pseud:
    """An AO3 Pseud: the public identity attached to creations and comments."""

    class Reference:
        __slots__ = (
            "description",
            "description_html",
            "name",
            "path",
            "recs_count",
            "user_login",
            "works_count",
        )

        def __init__(
            self,
            name: str,
            user_login: str,
            path: str | None = None,
            *,
            description: str | None = None,
            description_html: str | None = None,
            works_count: int | None = None,
            recs_count: int | None = None,
        ) -> None:
            self.name = name
            self.user_login = user_login
            self.path = path or (
                f"/users/{quote(user_login, safe='')}/pseuds/{quote(name, safe='')}"
            )
            self.description = description
            self.description_html = description_html
            self.works_count = works_count
            self.recs_count = recs_count

        @classmethod
        def from_link(cls, name: str, href: str) -> "Pseud.Reference":
            parts = urlparse(href).path.split("/")

            if len(parts) < 3 or parts[1] != "users":
                raise AO3InvalidURLError(f"Not an AO3 pseud URL: {href}")

            user_login = unquote(parts[2])
            pseud_name = (
                unquote(parts[4]) if len(parts) > 4 and parts[3] == "pseuds" else name
            )

            if match := re.fullmatch(
                r"(?P<name>.+?)\s*\((?P<user_login>[^()]*)\)", pseud_name
            ):
                pseud_name = match["name"].strip()
                user_login = match["user_login"].strip()

            return cls(pseud_name, user_login)

    class Page:
        class Data:
            __slots__ = ("page", "page_count", "pseuds", "total")

            def __init__(
                self,
                page: int,
                page_count: int,
                total: int | None,
                pseuds: "tuple[Pseud.Reference, ...]",
            ) -> None:
                self.page = page
                self.page_count = page_count
                self.total = total
                self.pseuds = pseuds

        __slots__ = ("page", "page_count", "pseuds", "total")

        def __init__(
            self,
            page: int,
            page_count: int,
            total: int | None,
            pseuds: "tuple[Pseud, ...]",
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.total = total
            self.pseuds = pseuds

        def __iter__(self) -> "Iterator[Pseud]":
            return iter(self.pseuds)

        def __len__(self) -> int:
            return len(self.pseuds)

    def __init__(
        self,
        name: str,
        user_login: str,
        link: str | None = None,
        *,
        page: int = 1,
        view_adult: bool = True,
        description: str | None = None,
        description_html: str | None = None,
        works_count: int | None = None,
        recs_count: int | None = None,
        client: "AO3Client | None" = None,
    ) -> None:
        self.name = name
        self.user_login = user_login
        self.link = link or (
            f"/users/{quote(user_login, safe='')}/pseuds/{quote(name, safe='')}"
        )
        self.page = page
        self.view_adult = view_adult
        self.description = description
        self.description_html = description_html
        self.works_count = works_count
        self.recs_count = recs_count
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
    ) -> "Pseud":
        path = "/" + urlparse(url).path.lstrip("/")

        parts = path.split("/")

        if len(parts) < 5 or parts[1] != "users" or parts[3] != "pseuds":
            raise AO3InvalidURLError(f"Not an AO3 pseud URL: {url}")

        return cls(
            unquote(parts[4]),
            unquote(parts[2]),
            "/".join(parts[:5]),
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_reference(
        cls,
        reference: "Pseud.Reference",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Pseud":
        return cls(
            reference.name,
            reference.user_login,
            reference.path,
            page=page,
            view_adult=view_adult,
            description=reference.description,
            description_html=reference.description_html,
            works_count=reference.works_count,
            recs_count=reference.recs_count,
            client=client,
        )

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @property
    def byline(self) -> str:
        return (
            f"{self.name} ({self.user_login})"
            if self.name != self.user_login
            else self.name
        )

    @cached_property
    def user(self) -> "User":
        from ao3.user import User

        return User(
            self.user_login,
            page=self.page,
            view_adult=self.view_adult,
            client=self.client,
        )

    @cached_property
    def works_page(self) -> "Work.Page":
        page = self.client.fetch_pseud_works(self)
        self.works_count = page.total
        return page

    @property
    def works(self) -> "tuple[Work, ...]":
        return self.works_page.works

    @cached_property
    def series_page(self) -> "Series.Page":
        return self.client.fetch_pseud_series(self)

    @property
    def series(self) -> "tuple[Series, ...]":
        return self.series_page.series

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_pseud_bookmarks(self)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    def copy(self, *, page: int | None = None) -> "Pseud":
        return Pseud(
            self.name,
            self.user_login,
            self.link,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            description=self.description,
            description_html=self.description_html,
            works_count=self.works_count,
            recs_count=self.recs_count,
            client=self.client,
        )

    def __repr__(self) -> str:
        return f"Pseud(name={self.name!r}, user_login={self.user_login!r})"

    @staticmethod
    def parse_index(content: bytes | str, requested_page: int) -> "Pseud.Page.Data":
        soup = BeautifulSoup(content, "lxml")
        listing = soup.select("li.user.pseud.picture.blurb.group[role=article]")

        if not listing and not soup.select_one("h2.heading"):
            raise AO3ParseError("The AO3 pseud index was not found")

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

        pseuds = []
        for item in listing:
            if (heading := item.select_one("div.header.module h4.heading")) is None or (
                pseud_link := heading.select_one("a[href*='/pseuds/']")
            ) is None:
                continue

            reference = Pseud.Reference.from_link(
                pseud_link.get_text(" ", strip=True), str(pseud_link["href"])
            )

            if (
                user_link := heading.select_one(
                    "a[href^='/users/']:not([href*='/pseuds/'])"
                )
            ) is not None:
                reference.user_login = user_link.get_text(" ", strip=True)

            if (description := item.select_one("blockquote.userstuff")) is not None:
                reference.description_html = (
                    "".join(str(child) for child in description.contents).strip()
                    or None
                )
                reference.description = description.get_text(" ", strip=True) or None

            counts = item.select_one("div.header.module h5.heading")
            counts_text = counts.get_text(" ", strip=True) if counts else ""

            if match := re.search(
                r"(?P<count>[0-9][0-9,]*)\s+Works?\b", counts_text, re.IGNORECASE
            ):
                reference.works_count = int(match["count"].replace(",", ""))

            if match := re.search(
                r"(?P<count>[0-9][0-9,]*)\s+Recs?\b", counts_text, re.IGNORECASE
            ):
                reference.recs_count = int(match["count"].replace(",", ""))

            pseuds.append(reference)

        return Pseud.Page.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            len(pseuds) if not pages else None,
            tuple(pseuds),
        )
