from functools import cached_property
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote, unquote, urlparse

from ao3.exceptions import AO3InvalidURLError

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.bookmark import Bookmark
    from ao3.work import Work

TagKind = Literal[
    "rating", "warning", "category", "fandom", "relationship", "character", "freeform"
]


class Tag:
    """A lightweight AO3 tag whose work and bookmark pages load on demand."""

    class Reference:
        __slots__ = ("kind", "letter", "name", "path", "works_count")

        def __init__(
            self,
            name: str,
            path: str,
            kind: TagKind | None = None,
            letter: str | None = None,
            works_count: int | None = None,
        ) -> None:
            self.name = name
            self.path = path
            self.kind = kind
            self.letter = letter
            self.works_count = works_count

    @staticmethod
    def path(name: str, *, bookmarks: bool = False) -> str:
        escaped = (
            name.replace("/", "*s*")
            .replace("&", "*a*")
            .replace(".", "*d*")
            .replace("?", "*q*")
            .replace("#", "*h*")
        )
        return (
            f"/tags/{quote(escaped, safe='*')}/{'bookmarks' if bookmarks else 'works'}"
        )

    def __init__(
        self,
        name: str,
        link: str | None = None,
        *,
        kind: TagKind | None = None,
        page: int = 1,
        view_adult: bool = True,
        letter: str | None = None,
        works_count: int | None = None,
        client: "AO3Client | None" = None,
    ) -> None:
        if link and link.endswith("/bookmarks"):
            link = f"{link.removesuffix('/bookmarks')}/works"

        self.name = name
        self.link = link or self.path(name)
        self.kind = kind
        self.letter = letter
        self.page = page
        self.view_adult = view_adult

        if works_count is not None:
            self.__dict__["works_count"] = works_count

        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        kind: TagKind | None = None,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Tag":
        path = "/" + urlparse(url).path.lstrip("/")

        parts = path.split("/")

        if (
            len(parts) < 4
            or parts[1] != "tags"
            or parts[3] not in {"works", "bookmarks"}
        ):
            raise AO3InvalidURLError(f"Not an AO3 tag URL: {url}")

        name = (
            unquote(parts[2])
            .replace("*s*", "/")
            .replace("*a*", "&")
            .replace("*d*", ".")
            .replace("*q*", "?")
            .replace("*h*", "#")
        )

        return cls(
            name,
            cls.path(name),
            kind=kind,
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @classmethod
    def from_reference(
        cls,
        reference: "Tag.Reference",
        *,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Tag":
        return cls(
            reference.name,
            reference.path,
            kind=reference.kind,
            view_adult=view_adult,
            letter=reference.letter,
            works_count=reference.works_count,
            client=client,
        )

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def works_page(self) -> "Work.Page":
        page = self.client.fetch_tag_works(self)
        self.__dict__["works_count"] = page.total

        if self.kind is None:
            for work in page.works:
                for tag in work.tags:
                    if tag.name == self.name:
                        self.kind = tag.kind
                        return page

        return page

    @property
    def works(self) -> "tuple[Work, ...]":
        return self.works_page.works

    @cached_property
    def works_count(self) -> int:
        return self.works_page.total

    @cached_property
    def bookmarks_page(self) -> "Bookmark.Page":
        return self.client.fetch_tag_bookmarks(self)

    @property
    def bookmarks(self) -> "tuple[Bookmark, ...]":
        return self.bookmarks_page.bookmarks

    def copy(self, *, page: int | None = None) -> "Tag":
        return Tag(
            self.name,
            self.link,
            kind=self.kind,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            letter=self.letter,
            works_count=self.__dict__.get("works_count"),
            client=self.client,
        )

    def __repr__(self) -> str:
        return f"Tag(name={self.name!r}, page={self.page})"
