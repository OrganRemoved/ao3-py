from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ao3.ao3 import AO3Client


class Subscription:
    """An AO3 email subscription to a Work, Series, or User."""

    def __init__(
        self,
        subscription_id: int,
        subscribable_type: Literal["Work", "Series", "User"],
        subscribable_id: int,
        subscribable_link: str,
        link: str,
        *,
        client: "AO3Client | None" = None,
    ) -> None:
        self.id = subscription_id
        self.subscribable_type = subscribable_type
        self.subscribable_id = subscribable_id
        self.subscribable_link = subscribable_link
        self.link = link
        from ao3.ao3 import AO3Client

        self.client = client or AO3Client._default()

    @property
    def url(self) -> str:
        return f"{self.client.base_url}{self.link}"

    def delete(self) -> None:
        self.client.delete_subscription(self)

    def __repr__(self) -> str:
        return (
            f"Subscription(id={self.id}, "
            f"subscribable_type={self.subscribable_type!r}, "
            f"subscribable_id={self.subscribable_id})"
        )
