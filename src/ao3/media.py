import re
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlparse

from bs4 import BeautifulSoup

from ao3.exceptions import AO3InvalidURLError, AO3ParseError
from ao3.tag import Tag

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client


class Media:
    """An AO3 top-level media category and its fandom-tag index."""

    class Data:
        __slots__ = ("index_fandoms", "name", "path")

        def __init__(
            self, name: str, path: str, index_fandoms: tuple[Tag.Reference, ...]
        ) -> None:
            self.name = name
            self.path = path
            self.index_fandoms = index_fandoms

    @staticmethod
    def path(name: str) -> str:
        escaped = (
            name.replace("/", "*s*")
            .replace("&", "*a*")
            .replace(".", "*d*")
            .replace("?", "*q*")
            .replace("#", "*h*")
        )
        return f"/media/{quote(escaped, safe='*')}/fandoms"

    def __init__(
        self, name: str, link: str | None = None, *, client: "AO3Client | None" = None
    ) -> None:
        self.name = name
        self.link = link or self.path(name)
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @classmethod
    def from_url(cls, url: str, *, client: "AO3Client | None" = None) -> "Media":
        path = "/" + urlparse(url).path.lstrip("/")
        parts = path.split("/")

        if len(parts) < 4 or parts[1] != "media" or parts[3] != "fandoms":
            raise AO3InvalidURLError(f"Not an AO3 media URL: {url}")

        name = (
            unquote(parts[2])
            .replace("*s*", "/")
            .replace("*a*", "&")
            .replace("*d*", ".")
            .replace("*q*", "?")
            .replace("*h*", "#")
        )

        return cls(name, path, client=client)

    @classmethod
    def from_data(
        cls, data: "Media.Data", *, client: "AO3Client | None" = None
    ) -> "Media":
        media = cls(data.name, data.path, client=client)
        media.index_fandoms = tuple(
            Tag.from_reference(reference, client=client)
            for reference in data.index_fandoms
        )
        return media

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def index_fandoms(self) -> tuple[Tag, ...]:
        return self.client.fetch_media_index_fandoms(self)

    @cached_property
    def fandoms(self) -> tuple[Tag, ...]:
        return tuple(
            Tag.from_reference(reference, client=self.client)
            for reference in self.client.fetch_fandoms(self)
        )

    def __repr__(self) -> str:
        return f"Media(name={self.name!r})"

    @staticmethod
    def parse_index(content: bytes | str) -> "tuple[Media.Data, ...]":
        soup = BeautifulSoup(content, "lxml")

        if not soup.select_one("ul.media.fandom.index.group"):
            raise AO3ParseError("The AO3 media index was not found")

        media = []
        for item in soup.select(
            "ul.media.fandom.index.group > li.medium.listbox.group"
        ):
            if (heading := item.select_one("h3.heading > a[href]")) is None:
                continue

            index_fandoms = []
            for entry in item.select("ol.index.group > li"):
                if (anchor := entry.select_one("a.tag[href]")) is None:
                    continue
                index_fandoms.append(
                    Tag.Reference(
                        anchor.get_text(" ", strip=True),
                        urlparse(str(anchor["href"])).path,
                        "fandom",
                        works_count=(
                            int(count["count"].replace(",", ""))
                            if (
                                count := re.search(
                                    r"\((?P<count>[0-9,]+)\)\s*$",
                                    entry.get_text(" ", strip=True),
                                )
                            )
                            else None
                        ),
                    )
                )

            media.append(
                Media.Data(
                    heading.get_text(" ", strip=True),
                    urlparse(str(heading["href"])).path,
                    tuple(index_fandoms),
                )
            )

        return tuple(media)

    @staticmethod
    def parse_fandoms(content: bytes | str) -> "tuple[Tag.Reference, ...]":
        soup = BeautifulSoup(content, "lxml")

        if not soup.select_one("ol.alphabet.fandom.index.group"):
            raise AO3ParseError("The AO3 fandom index was not found")

        fandoms = []
        for group in soup.select(
            "ol.alphabet.fandom.index.group > li.letter.listbox.group"
        ):
            letter = unquote(str(group.get("id", ""))[7:]) or None
            for entry in group.select("ul.tags.index.group > li"):
                if (anchor := entry.select_one("a.tag[href]")) is None:
                    continue
                fandoms.append(
                    Tag.Reference(
                        anchor.get_text(" ", strip=True),
                        urlparse(str(anchor["href"])).path,
                        "fandom",
                        letter,
                        (
                            int(count["count"].replace(",", ""))
                            if (
                                count := re.search(
                                    r"\((?P<count>[0-9,]+)\)\s*$",
                                    entry.get_text(" ", strip=True),
                                )
                            )
                            else None
                        ),
                    )
                )

        return tuple(fandoms)
