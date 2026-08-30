import re
from contextlib import suppress
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse

from bs4 import BeautifulSoup

from ao3.exceptions import AO3InvalidURLError, AO3ParseError
from ao3.pseud import Pseud

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark
    from ao3.collection import Collection
    from ao3.series import Series
    from ao3.subscription import Subscription
    from ao3.work import Work


class User:
    """An AO3 login account that can own one or more Pseuds."""

    class Reference:
        __slots__ = ("login", "path")

        def __init__(self, login: str, path: str | None = None) -> None:
            self.login = login
            self.path = path or f"/users/{quote(login, safe='')}"

    class Data:
        __slots__ = (
            "bio",
            "bio_html",
            "id",
            "joined",
            "login",
            "path",
            "pseuds",
            "title",
        )

        def __init__(
            self,
            login: str,
            path: str,
            user_id: int | None,
            joined: date | None,
            title: str | None,
            bio: str | None,
            bio_html: str | None,
            pseuds: tuple[Pseud.Reference, ...],
        ) -> None:
            self.login = login
            self.path = path
            self.id = user_id
            self.joined = joined
            self.title = title
            self.bio = bio
            self.bio_html = bio_html
            self.pseuds = pseuds

    def __init__(
        self,
        login: str,
        link: str | None = None,
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.login = login
        self.link = link or f"/users/{quote(login, safe='')}"
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
    ) -> "User":
        path = "/" + urlparse(url).path.lstrip("/")

        parts = path.split("/")

        if len(parts) < 3 or parts[1] != "users" or not parts[2]:
            raise AO3InvalidURLError(f"Not an AO3 user URL: {url}")

        login = unquote(parts[2])

        return cls(
            login,
            f"/users/{quote(login, safe='')}",
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_reference(
        cls,
        reference: "User.Reference",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "User":
        return cls(
            reference.login,
            reference.path,
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def detail(self) -> "User.Data":
        return self.client.fetch_user(self)

    @property
    def id(self) -> int | None:
        return self.detail.id

    @property
    def joined(self) -> date | None:
        return self.detail.joined

    @property
    def title(self) -> str | None:
        return self.detail.title

    @property
    def bio(self) -> str | None:
        return self.detail.bio

    @property
    def bio_html(self) -> str | None:
        return self.detail.bio_html

    @cached_property
    def default_pseud(self) -> Pseud | None:
        if self.detail.pseuds:
            return Pseud.from_reference(
                self.detail.pseuds[0],
                page=self.page,
                view_adult=self.view_adult,
                client=self.client,
            )

    @cached_property
    def pseuds_page(self) -> Pseud.Page:
        return self.client.fetch_user_pseuds(self)

    @property
    def pseuds(self) -> tuple[Pseud, ...]:
        return self.pseuds_page.pseuds

    @cached_property
    def works_page(self) -> "Work.Page":
        return self.client.fetch_user_works(self)

    @property
    def works(self) -> "tuple[Work, ...]":
        return self.works_page.works

    @cached_property
    def series_page(self) -> "Series.Page":
        return self.client.fetch_user_series(self)

    @property
    def series(self) -> "tuple[Series, ...]":
        return self.series_page.series

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_user_bookmarks(self)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    @cached_property
    def collections_page(self) -> "Collection.Page":
        return self.client.fetch_user_collections(self)

    @property
    def collections(self) -> "tuple[Collection, ...]":
        return self.collections_page.collections

    def subscribe(self) -> "Subscription":
        return self.client.create_subscription(self)

    def unsubscribe(self) -> None:
        self.client.delete_subscription(self)

    def copy(self, *, page: int | None = None) -> "User":
        return User(
            self.login,
            self.link,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            client=self.client,
        )

    def __repr__(self) -> str:
        return f"User(login={self.login!r})"

    @staticmethod
    def parse_profile(content: bytes | str, login: str) -> "User.Data":
        soup = BeautifulSoup(content, "lxml")

        if (profile := soup.select_one("div.user.home.profile")) is None:
            raise AO3ParseError(f"AO3 profile for {login!r} was not found")

        user_id = None
        joined = None

        if (meta := profile.select_one("dl.meta")) is not None:
            for label in meta.select(":scope > dt"):
                if (value := label.find_next_sibling("dd")) is None:
                    continue

                label_text = label.get_text(" ", strip=True).lower()

                if "joined" in label_text:
                    for date_format in (
                        "%Y-%m-%d",
                        "%d %b %Y",
                        "%d %B %Y",
                        "%b %d, %Y",
                    ):
                        try:
                            joined = datetime.strptime(
                                value.get_text(" ", strip=True), date_format
                            ).date()
                            break
                        except ValueError:
                            pass
                elif "user id" in label_text and (
                    match := re.search(r"(?P<user_id>[0-9]+)", value.get_text())
                ):
                    user_id = int(match["user_id"])

        pseud_references = []
        for anchor in profile.select("dd.pseuds a[href*='/pseuds/']"):
            with suppress(AO3InvalidURLError):
                pseud_references.append(
                    Pseud.Reference.from_link(
                        anchor.get_text(" ", strip=True), str(anchor["href"])
                    )
                )

        header = profile.select_one("div.primary.header.module")
        title_heading = profile.select_one(":scope > h3.heading")

        if title_heading and header and header.find(title_heading):
            title_heading = None

        bio = profile.select_one("div.bio.module blockquote.userstuff")
        bio_html = (
            "".join(str(child) for child in bio.contents).strip() or None
            if bio is not None
            else None
        )

        return User.Data(
            login,
            f"/users/{quote(login, safe='')}",
            user_id,
            joined,
            title_heading.get_text(" ", strip=True) if title_heading else None,
            bio.get_text(" ", strip=True) or None if bio else None,
            bio_html,
            tuple(pseud_references),
        )
