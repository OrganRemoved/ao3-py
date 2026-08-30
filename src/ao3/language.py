import re
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse

from bs4.element import Tag as Element

from ao3.exceptions import AO3InvalidURLError

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client
    from ao3.work import Work


class Language:
    """An AO3 language and its public work listing."""

    class Reference:
        __slots__ = ("name", "short")

        def __init__(self, short: str, name: str) -> None:
            self.short = short
            self.name = name

        @classmethod
        def from_element(cls, element: Element | None) -> "Language.Reference | None":
            if element is not None:
                anchor = element.select_one("a[href*='/languages/']")
                short = str(
                    element.get("lang") or (anchor.get("lang") if anchor else "")
                )

                if (
                    not short
                    and anchor
                    and (
                        match := re.search(
                            r"/languages/(?P<short>[^/]+)", str(anchor["href"])
                        )
                    )
                ):
                    short = unquote(match["short"])

                if short:
                    return cls(short, element.get_text(" ", strip=True))

    def __init__(
        self,
        short: str,
        name: str | None = None,
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> None:
        self.short = short
        self.name = name or short
        self.link = f"/languages/{quote(short, safe='')}/works"
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
    ) -> "Language":
        if not (
            match := re.search(
                r"/languages/(?P<short>[^/]+)(?:/works)?", urlparse(url).path
            )
        ):
            raise AO3InvalidURLError(f"Not an AO3 language URL: {url}")

        return cls(
            unquote(match["short"]), page=page, view_adult=view_adult, client=client
        )

    @classmethod
    def from_reference(
        cls,
        reference: "Language.Reference",
        *,
        page: int = 1,
        view_adult: bool = True,
        client: "AO3Client | None" = None,
    ) -> "Language":
        return cls(
            reference.short,
            reference.name,
            page=page,
            view_adult=view_adult,
            client=client,
        )

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def works_page(self) -> "Work.Page":
        return self.client.fetch_language_works(self)

    @property
    def works(self) -> "tuple[Work, ...]":
        return self.works_page.works

    @property
    def works_count(self) -> int:
        return self.works_page.total

    def copy(self, *, page: int | None = None) -> "Language":
        return Language(
            self.short,
            self.name,
            page=self.page if page is None else page,
            view_adult=self.view_adult,
            client=self.client,
        )

    def __repr__(self) -> str:
        return f"Language(short={self.short!r}, name={self.name!r})"
