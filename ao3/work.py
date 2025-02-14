from dataclasses import KW_ONLY, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from ao3.tag import Tag


T = TypeVar("T")


@dataclass
class Chapter:
    _: KW_ONLY

    session: requests.Session = field(default_factory=requests.Session, repr=False)

    title: str | None = None
    summary: str | None = None
    notes: str | None = None
    article: str | None = None
    end_notes: str | None = None


class Descriptor(Generic[T]):
    def __init__(self, *, default: Any = None) -> None:
        self.default = default

    def __set_name__(self, owner: type["Work"], name: str) -> None:
        self.name = name

    def __get__(self, instance: "Work", owner: type["Work"]) -> Any:
        if instance is None:
            return self

        if not hasattr(instance, f"_{self.name}"):
            from ao3.tag import Tag

            resp = instance.session.get(
                urljoin("https://archiveofourown.org", instance.link)
            )

            soup = BeautifulSoup(resp.text, features="lxml")

            for dd in (
                soup.find("div", {"class": "wrapper"})
                .find("dl", {"class": "work meta group"})
                .find_all("dd")
            ):
                match dd["class"]:
                    case ["rating", "tags"]:
                        setattr(
                            instance,
                            "_rating",
                            [
                                Tag(
                                    session=instance.session,
                                    name=a.text,
                                    link=a["href"],
                                )
                                for a in dd.find("ul", {"class": "commas"}).find_all(
                                    "a", {"class": "tag"}
                                )
                            ],
                        )

                    case ["warning", "tags"]:
                        setattr(
                            instance,
                            "_archive_warning",
                            [
                                Tag(
                                    session=instance.session,
                                    name=a.text,
                                    link=a["href"],
                                )
                                for a in dd.find("ul", {"class": "commas"}).find_all(
                                    "a", {"class": "tag"}
                                )
                            ],
                        )

                    case ["category", "tags"]:
                        setattr(
                            instance,
                            "_category",
                            [
                                Tag(
                                    session=instance.session,
                                    name=a.text,
                                    link=a["href"],
                                )
                                for a in dd.find("ul", {"class": "commas"}).find_all(
                                    "a", {"class": "tag"}
                                )
                            ],
                        )

                    case ["fandom", "tags"]:
                        setattr(
                            instance,
                            "_fandom",
                            [
                                Tag(
                                    session=instance.session,
                                    name=a.text,
                                    link=a["href"],
                                )
                                for a in dd.find("ul", {"class": "commas"}).find_all(
                                    "a", {"class": "tag"}
                                )
                            ],
                        )

                    case ["relationship", "tags"]:
                        setattr(
                            instance,
                            "_relationships",
                            [
                                Tag(
                                    session=instance.session,
                                    name=a.text,
                                    link=a["href"],
                                )
                                for a in dd.find("ul", {"class": "commas"}).find_all(
                                    "a", {"class": "tag"}
                                )
                            ],
                        )

                    case ["language"]:
                        setattr(instance, "_language", dd.text.strip())

                    case ["stats"]:
                        stats = dd.find("dl", {"class": "stats"})

                        if elem := stats.find("dd", {"class": "published"}):
                            setattr(
                                instance,
                                "_published",
                                datetime.fromisoformat(elem.text),
                            )

                        if elem := stats.find("dd", {"class": "status"}):
                            setattr(
                                instance, "_status", datetime.fromisoformat(elem.text)
                            )
                            setattr(instance, "_complete", False)
                        else:
                            setattr(instance, "_status", None)
                            setattr(instance, "_complete", True)

                        if elem := stats.find("dd", {"class": "words"}):
                            setattr(instance, "_words", int(elem.text.replace(",", "")))

                        if elem := stats.find("dd", {"class": "chapters"}):
                            chapter, chapter_count = elem.text.split("/")

                            setattr(instance, "_chapter_number", int(chapter))
                            setattr(
                                instance,
                                "_chapter_count",
                                None if chapter_count == "?" else int(chapter_count),
                            )

                        if elem := stats.find("dd", {"class": "comments"}):
                            setattr(
                                instance, "_comments", int(elem.text.replace(",", ""))
                            )

                        if elem := stats.find("dd", {"class": "kudos"}):
                            setattr(instance, "_kudos", int(elem.text.replace(",", "")))

                        if elem := stats.find("dd", {"class": "hits"}):
                            setattr(instance, "_hits", int(elem.text.replace(",", "")))

            workskin = soup.find("div", {"id": "workskin"})

            preface = workskin.find("div", {"class": "preface group"})

            setattr(
                instance,
                "_title",
                preface.find("h2", {"class": "title heading"}).text.strip(),
            )

            if elem := preface.find("h3", {"class": "byline heading"}).find(
                "a",
                {"rel": "author"},
            ):
                setattr(instance, "_author", elem.text)
            else:
                setattr(instance, "_author", None)

            if elem := preface.find("div", {"class": "summary module"}):
                setattr(
                    instance,
                    "_summary",
                    "\n".join(
                        elem.find("blockquote", {"class": "userstuff"}).strings
                    ).strip(),
                )

            chapters = []

            for chapter in workskin.find("div", {"id": "chapters"}).find_all(
                "div", {"class": "chapter"}, recursive=False
            ):
                c = Chapter(session=instance.session)

                if elem := chapter.find("h3", {"class": "title"}):
                    setattr(c, "title", elem.text)

                if elem := chapter.find("div", {"id": "summary"}):
                    setattr(
                        c,
                        "summary",
                        "\n".join(
                            elem.find("blockquote", {"class": "userstuff"}).strings
                        ).strip(),
                    )

                if (elem := chapter.find("div", {"id": "notes"})) and (
                    notes := elem.find("blockquote", {"class": "userstuff"})
                ):
                    setattr(c, "notes", "\n".join(notes.strings).strip())

                if elem := chapter.find("div", {"role": "article"}):
                    setattr(c, "article", "\n".join(elem.strings).strip())

                if elem := chapter.find("div", {"class": "end notes module"}):
                    setattr(
                        c,
                        "end_notes",
                        "\n".join(
                            elem.find("blockquote", {"class": "userstuff"}).strings
                        ).strip(),
                    )

                chapters.append(c)

            if elem := workskin.find("div", {"class": "userstuff"}):
                chapters.append(
                    Chapter(session=instance.session, article="\n".join(elem.strings))
                )

            setattr(instance, "_chapters", chapters)

        if not hasattr(instance, f"_{self.name}"):
            setattr(instance, f"_{self.name}", self.default)
            return self.default

        return getattr(instance, f"_{self.name}")

    def __set__(self, instance: "Work", value: Any) -> None:
        setattr(instance, f"_{self.name}", value)


@dataclass
class Work:
    _: KW_ONLY

    session: Descriptor[requests.Session] = Descriptor(default=requests.Session())

    link: Descriptor[str] = Descriptor()

    work_id: Descriptor[int] = Descriptor()
    chapter_id: Descriptor[int] = Descriptor()

    rating: Descriptor[list["Tag"]] = Descriptor()
    archive_warning: Descriptor[list["Tag"]] = Descriptor()
    fandoms: Descriptor[list["Tag"]] = Descriptor()
    relationships: Descriptor[list["Tag"]] = Descriptor()
    characters: Descriptor[list["Tag"]] = Descriptor()
    additional_tags: Descriptor[list["Tag"]] = Descriptor()
    language: Descriptor[str] = Descriptor()

    published: Descriptor[datetime] = Descriptor()
    status: Descriptor[datetime] = Descriptor()
    words: Descriptor[int] = Descriptor()
    chapter_number: Descriptor[int] = Descriptor()
    chapter_count: Descriptor[int] = Descriptor()
    comments: Descriptor[int] = Descriptor()
    kudos: Descriptor[int] = Descriptor()
    bookmarks: Descriptor[int] = Descriptor()
    hits: Descriptor[int] = Descriptor()

    author: Descriptor[str] = Descriptor()
    title: Descriptor[str] = Descriptor()
    summary: Descriptor[str] = Descriptor()

    chapters: Descriptor[list[Chapter]] = Descriptor()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.title}, author={self.author})"
