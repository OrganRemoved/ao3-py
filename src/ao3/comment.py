import re
from collections.abc import Iterator
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag as Element

from ao3.exceptions import AO3AuthenticationError, AO3InvalidURLError, AO3ParseError
from ao3.pseud import Pseud

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client


class Comment:
    """A public AO3 comment and the visible part of its reply tree."""

    class Page:
        class Data:
            __slots__ = ("comments", "page", "page_count", "total")

            def __init__(
                self,
                page: int,
                page_count: int,
                total: int,
                comments: "tuple[Comment.Data, ...]",
            ) -> None:
                self.page = page
                self.page_count = page_count
                self.total = total
                self.comments = comments

        __slots__ = ("comments", "page", "page_count", "total")

        def __init__(
            self,
            page: int,
            page_count: int,
            total: int,
            comments: "tuple[Comment, ...]",
        ) -> None:
            self.page = page
            self.page_count = page_count
            self.total = total
            self.comments = comments

        def __iter__(self) -> "Iterator[Comment]":
            return iter(self.comments)

        def __len__(self) -> int:
            return len(self.comments)

    class Data:
        __slots__ = (
            "by_anonymous_creator",
            "content",
            "content_html",
            "created_at",
            "created_at_text",
            "deleted",
            "depth",
            "edited_at",
            "edited_at_text",
            "guest_name",
            "hidden",
            "id",
            "parent_id",
            "path",
            "pseud",
            "replies",
            "replies_count",
            "spam",
            "timezone",
            "unreviewed",
        )

        def __init__(
            self,
            comment_id: int,
            path: str,
            parent_id: int | None,
            depth: int,
            pseud: Pseud.Reference | None,
            guest_name: str | None,
            created_at: datetime | None,
            created_at_text: str | None,
            timezone: str | None,
            edited_at: datetime | None,
            edited_at_text: str | None,
            content: str | None,
            content_html: str | None,
            deleted: bool,
            by_anonymous_creator: bool,
            unreviewed: bool,
            spam: bool,
            hidden: bool,
            replies_count: int,
            replies: "tuple[Comment.Data, ...]",
        ) -> None:
            self.id = comment_id
            self.path = path
            self.parent_id = parent_id
            self.depth = depth
            self.pseud = pseud
            self.guest_name = guest_name
            self.created_at = created_at
            self.created_at_text = created_at_text
            self.timezone = timezone
            self.edited_at = edited_at
            self.edited_at_text = edited_at_text
            self.content = content
            self.content_html = content_html
            self.deleted = deleted
            self.by_anonymous_creator = by_anonymous_creator
            self.unreviewed = unreviewed
            self.spam = spam
            self.hidden = hidden
            self.replies_count = replies_count
            self.replies = replies

    def __init__(
        self,
        comment_id: int,
        *,
        link: str | None = None,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = comment_id
        self.link = link or f"/comments/{comment_id}"
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @classmethod
    def from_url(cls, url: str, *, client: "AO3Client | None" = None) -> "Comment":
        if not (
            match := re.search(
                r"/comments/(?P<comment_id>[0-9]+)",
                "/" + urlparse(url).path.lstrip("/"),
            )
        ):
            raise AO3InvalidURLError(f"Not an AO3 comment URL: {url}")

        return cls(int(match["comment_id"]), client=client)

    @classmethod
    def from_data(
        cls, data: "Comment.Data", *, client: "AO3Client | None" = None
    ) -> "Comment":
        comment = cls(data.id, link=data.path, client=client)
        comment.detail = data
        return comment

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    @cached_property
    def detail(self) -> "Comment.Data":
        return self.client.fetch_comment(self)

    @property
    def parent_id(self) -> int | None:
        return self.detail.parent_id

    @property
    def depth(self) -> int:
        return self.detail.depth

    @property
    def guest_name(self) -> str | None:
        return self.detail.guest_name

    @property
    def created_at(self) -> datetime | None:
        return self.detail.created_at

    @property
    def created_at_text(self) -> str | None:
        return self.detail.created_at_text

    @property
    def timezone(self) -> str | None:
        return self.detail.timezone

    @property
    def edited_at(self) -> datetime | None:
        return self.detail.edited_at

    @property
    def edited_at_text(self) -> str | None:
        return self.detail.edited_at_text

    @property
    def content(self) -> str | None:
        return self.detail.content

    @property
    def content_html(self) -> str | None:
        return self.detail.content_html

    @property
    def deleted(self) -> bool:
        return self.detail.deleted

    @property
    def by_anonymous_creator(self) -> bool:
        return self.detail.by_anonymous_creator

    @property
    def unreviewed(self) -> bool:
        return self.detail.unreviewed

    @property
    def spam(self) -> bool:
        return self.detail.spam

    @property
    def hidden(self) -> bool:
        return self.detail.hidden

    @property
    def replies_count(self) -> int:
        return self.detail.replies_count

    @cached_property
    def pseud(self) -> Pseud | None:
        if self.detail.pseud:
            return Pseud.from_reference(self.detail.pseud, client=self.client)

    @cached_property
    def replies(self) -> tuple["Comment", ...]:
        return tuple(
            Comment.from_data(reply, client=self.client)
            for reply in self.detail.replies
        )

    def reply(
        self,
        content: str,
        *,
        pseud_id: int | None = None,
        name: str | None = None,
        email: str | None = None,
    ) -> "Comment":
        reply = self.client.create_comment(
            self, content, pseud_id=pseud_id, name=name, email=email
        )

        self.__dict__.pop("replies", None)
        self.__dict__.pop("detail", None)

        return reply

    def update(self, content: str, *, pseud_id: int | None = None) -> "Comment":
        self.detail = self.client.update_comment(self, content, pseud_id=pseud_id)

        self.__dict__.pop("pseud", None)

        return self

    def delete(self) -> None:
        self.client.delete_comment(self)

        self.__dict__.pop("detail", None)
        self.__dict__.pop("pseud", None)
        self.__dict__.pop("replies", None)

    def __repr__(self) -> str:
        return f"Comment(id={self.id})"

    @staticmethod
    def parse_element(
        article: Element, parent_id: int | None = None, depth: int = 0
    ) -> "Comment.Data | None":
        if not (
            match := re.fullmatch(
                r"comment_(?P<comment_id>[0-9]+)", str(article.get("id", ""))
            )
        ):
            return None

        comment_id = int(match["comment_id"])
        deleted = (
            "previous comment deleted" in article.get_text(" ", strip=True).lower()
        )
        heading = article.select_one("h4.heading.byline")

        if heading is None or deleted:
            pseud_reference, guest_name, by_anonymous_creator = None, None, False
        elif pseud_link := heading.select_one("a[href^='/users/']"):
            pseud_reference, guest_name, by_anonymous_creator = (
                Pseud.Reference.from_link(
                    pseud_link.get_text(" ", strip=True), str(pseud_link["href"])
                ),
                None,
                False,
            )
        else:
            heading_copy = BeautifulSoup(str(heading), "lxml")
            for element in heading_copy.select(
                "span.parent, span.datetime, span.status"
            ):
                element.extract()

            pseud_reference = None
            guest_name = heading_copy.get_text(" ", strip=True) or None
            by_anonymous_creator = guest_name == "Anonymous Creator"
            guest_name = None if by_anonymous_creator else guest_name

        created_element = (
            heading.select_one("span.posted.datetime") if heading else None
        )
        created_at_text = (
            created_element.get_text(" ", strip=True) if created_element else None
        )
        timezone = (
            timezone_element.get_text(" ", strip=True)
            if created_element
            and (timezone_element := created_element.select_one("abbr.timezone"))
            else None
        )

        if (
            created_element
            and (day := created_element.select_one("span.date"))
            and (month := created_element.select_one("abbr.month"))
            and (year := created_element.select_one("span.year"))
            and (time := created_element.select_one("span.time"))
        ):
            created_at = datetime.strptime(
                f"{day.get_text(strip=True)} {month.get_text(strip=True)} "
                f"{year.get_text(strip=True)} {time.get_text(strip=True)}",
                "%d %b %Y %I:%M%p",
            )
        else:
            created_at = None

        edited_element = article.select_one("p.edited.datetime")
        edited_at_text = (
            edited_element.get_text(" ", strip=True) if edited_element else None
        )

        if (
            edited_element
            and (day := edited_element.select_one("span.date"))
            and (month := edited_element.select_one("abbr.month"))
            and (year := edited_element.select_one("span.year"))
            and (time := edited_element.select_one("span.time"))
        ):
            edited_at = datetime.strptime(
                f"{day.get_text(strip=True)} {month.get_text(strip=True)} "
                f"{year.get_text(strip=True)} {time.get_text(strip=True)}",
                "%d %b %Y %I:%M%p",
            )
        else:
            edited_at = None

        content = article.select_one("blockquote.userstuff")
        content_html = (
            "".join(str(child) for child in content.contents).strip() or None
            if content is not None
            else None
        )
        content_text = None

        if content_html:
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
            content_text = "\n".join(line for line in lines if line) or None

        replies = []
        replies_count = 0
        wrapper = article.find_next_sibling("li")

        reply_list = (
            wrapper.find("ol", class_="thread", recursive=False)
            if wrapper is not None and not wrapper.get("id")
            else None
        )

        if reply_list is not None:
            for child in reply_list.find_all("li", recursive=False):
                if str(child.get("id", "")).startswith("comment_"):
                    if (
                        parsed := Comment.parse_element(child, comment_id, depth + 1)
                    ) is not None:
                        replies.append(parsed)
                elif count_match := re.search(
                    r"(?P<count>[0-9][0-9,]*)\s+more comments?",
                    child.get_text(" ", strip=True),
                    re.IGNORECASE,
                ):
                    replies_count += int(count_match["count"].replace(",", ""))

        replies_count += len(replies)

        classes = {str(value) for value in article.get("class", [])}
        notice = article.select_one("p.notice, p.message")
        notice_text = notice.get_text(" ", strip=True).lower() if notice else ""

        return Comment.Data(
            comment_id,
            f"/comments/{comment_id}",
            parent_id,
            depth,
            pseud_reference,
            guest_name,
            created_at,
            created_at_text,
            timezone,
            edited_at,
            edited_at_text,
            content_text,
            content_html,
            deleted,
            by_anonymous_creator,
            bool(heading and heading.select_one("span.unreviewed.status")),
            "spam" in classes or "spam" in notice_text,
            "hidden" in classes
            or "hidden" in notice_text
            or "currently unavailable" in notice_text,
            replies_count,
            tuple(replies),
        )

    @staticmethod
    def parse_page(
        content: bytes | str, requested_page: int, total: int | None = None
    ) -> "Comment.Page.Data":
        soup = BeautifulSoup(content, "lxml")

        if (
            total is None
            and (comments_stat := soup.select_one("dd.comments")) is not None
            and (
                count := re.search(r"(?P<count>[0-9][0-9,]*)", comments_stat.get_text())
            )
        ):
            total = int(count["count"].replace(",", ""))

        container = soup.select_one("div#comments_placeholder") or soup

        if (thread := container.select_one("ol.thread")) is None:
            if soup.select_one("form#new_user, form.new_user"):
                raise AO3AuthenticationError("AO3 comments require a login")

            if soup.select_one("div#feedback"):
                return Comment.Page.Data(requested_page, 1, total or 0, ())

            raise AO3ParseError("The AO3 comment thread was not found")

        comments = tuple(
            parsed
            for article in thread.find_all("li", recursive=False)
            if (parsed := Comment.parse_element(article)) is not None
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

        return Comment.Page.Data(
            int(current.get_text(strip=True))
            if current and current.get_text(strip=True).isdigit()
            else requested_page,
            max(pages, default=1),
            total if total is not None else len(comments),
            comments,
        )

    @staticmethod
    def parse_root(content: bytes | str, comment_id: int) -> "Comment.Data":
        page = Comment.parse_page(content, 1)
        comments = list(page.comments)

        while comments:
            comment = comments.pop()

            if comment.id == comment_id:
                return comment

            comments.extend(comment.replies)

        raise AO3ParseError(f"Comment {comment_id} was not found")
