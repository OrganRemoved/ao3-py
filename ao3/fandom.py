import re
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from ao3.tag import Tag

T = TypeVar("T")


class Descriptor(Generic[T]):
    def __init__(self, *, default: Any = None) -> None:
        self.default = default

    def __set_name__(self, owner: type["Fandom"], name: str) -> None:
        self.name = name

    def __get__(self, instance: "Fandom", owner: type["Fandom"]) -> Any:
        if instance is None:
            return self

        if not hasattr(instance, f"_{self.name}"):
            from ao3.tag import Tag

            soup = BeautifulSoup(
                instance.session.get("https://archiveofourown.org/media").text,
                features="lxml",
            )

            for li in soup.find("ul", {"class": "media fandom index group"}).find_all(
                "li", {"class": "medium listbox group"}
            ):
                if heading := li.find("h3", {"class": "heading"}).find(
                    "a", string=self.name
                ):
                    setattr(instance, "_link", heading["href"])

                    setattr(
                        instance,
                        "_hot_tags",
                        [
                            Tag(
                                session=instance.session,
                                name=a.text,
                                link=a["href"],
                                works_count=int(
                                    re.search(
                                        r"\((?P<works_count>\d+)\)", fandom.text
                                    ).groupdict()["works_count"]
                                ),
                            )
                            for fandom in li.find(
                                "ol", {"class": "index group"}
                            ).find_all("li")
                            if (a := fandom.find("a", {"class": "tag"}))
                        ],
                    )

            soup = BeautifulSoup(
                instance.session.get(
                    urljoin("https://archiveofourown.org", instance.link)
                ).text,
                features="lxml",
            )

            setattr(
                instance,
                "_tags",
                [
                    Tag(
                        session=instance.session,
                        name=a.text,
                        link=a["href"],
                        letter=li["id"].split("-")[1],
                    )
                    for li in soup.find(
                        "ol", {"class": "alphabet fandom index group"}
                    ).find_all("li", {"class": "letter listbox group"})
                    for li_ in li.find("ul", {"class": "tags index group"}).find_all(
                        "li"
                    )
                    if (a := li_.find("a", {"class": "tag"}))
                ],
            )

        if not hasattr(instance, f"_{self.name}"):
            setattr(instance, f"_{self.name}", self.default)
            return self.default

        return getattr(instance, f"_{self.name}")

    def __set__(self, instance: "Fandom", value: Any) -> None:
        setattr(instance, f"_{self.name}", value)


@dataclass
class Fandom:
    _: KW_ONLY

    session: Descriptor[requests.Session] = Descriptor(default=requests.Session())

    name: Descriptor[str] = Descriptor()
    link: Descriptor[str] = Descriptor()

    hot_tags: Descriptor[list["Tag"]] = Descriptor()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"
