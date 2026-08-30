# ao3-py

An unofficial, typed Python client for [Archive of Our Own](https://archiveofourown.org/).

`ao3-py` turns AO3 pages into lazy domain objects. Constructing a `Work`, `Tag`,
`User`, or another model creates only a lightweight handle. The first property that
needs remote data loads it through `httpx`, and the parsed state is then cached on
that object.

## Table of contents

- [Design highlights](#design-highlights)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Object and loading model](#object-and-loading-model)
  - [Summary, detail, and content states](#summary-detail-and-content-states)
  - [Lightweight relationships](#lightweight-relationships)
  - [Clients and connection lifetime](#clients-and-connection-lifetime)
  - [Custom origin, cookies, and transport settings](#custom-origin-cookies-and-transport-settings)
  - [Pagination](#pagination)
- [Login](#login)
- [Authenticated actions](#authenticated-actions)
  - [Kudos and bookmarks](#kudos-and-bookmarks)
  - [Comments and replies](#comments-and-replies)
  - [Subscriptions and Marked for Later](#subscriptions-and-marked-for-later)
- [Browsing tags and languages](#browsing-tags-and-languages)
- [Works, chapters, comments, kudos, and downloads](#works-chapters-comments-kudos-and-downloads)
- [Users and pseuds](#users-and-pseuds)
- [Media and fandom indexes](#media-and-fandom-indexes)
- [Series, collections, bookmarks, and external works](#series-collections-bookmarks-and-external-works)
- [API reference](#api-reference)
  - [`AO3Client`](#ao3client)
  - [`Work`](#work)
  - [`Chapter`](#chapter)
  - [`Kudos`](#kudos)
  - [`Tag` and `TagKind`](#tag-and-tagkind)
  - [`Language`](#language)
  - [`Media`](#media)
  - [`User`](#user)
  - [`Pseud`](#pseud)
  - [`Series`](#series)
  - [`Collection`](#collection)
  - [`Bookmark`](#bookmark)
  - [`ExternalWork`](#externalwork)
  - [`Comment`](#comment)
  - [`Subscription`](#subscription)
  - [Page objects](#page-objects)
  - [Exceptions](#exceptions)
- [Adult content](#adult-content)
- [Network and parsing behavior](#network-and-parsing-behavior)
- [Disclaimer](#disclaimer)

## Design highlights

- Standalone models use one process-wide client that is created lazily; there is no
  default-client setup API to call before `Work.from_url(...)`.
- Explicit `AO3Client` sessions provide login, custom cookies, a mutable origin, and
  deterministic connection-pool lifetime.
- HTTP/2 is preferred when AO3 supports it, with HTTP/1.1 negotiated automatically.
- List pages produce lightweight, summary-backed models instead of eagerly loading
  every result and causing an N+1 request pattern.
- Related resources such as tags, pseuds, series, and works are returned as fresh
  handles, so loading a child does not grow the parent into a large object graph.
- Metadata, full chapter content, and independent listings such as comments or
  bookmarks have separate lazy caches, so callers only pay for the data they use.
- Plain text and the corresponding parsed HTML fragments are exposed separately
  where AO3 provides rich user content.
- Models follow AO3 terminology: a `User` is the account and a `Pseud` is the public
  identity attached to works, series, bookmarks, and comments.
- Read and write operations live on the object they affect: for example,
  `work.create_bookmark()`, `comment.reply()`, and `series.subscribe()`.
- Parser records, references, and page containers are nested under their owning
  model, keeping the public module layout small and cohesive.

## Installation

`ao3-py` requires Python 3.10 or newer.

```sh
uv add ao3-py
```

or:

```sh
pip install --upgrade ao3-py
```

## Quick start

Examples use symbolic placeholders such as `WORK_ID`, `TAG_NAME`, `TAG_URL`, and
`SERIES_ID`. Supply them from your own configuration; the documentation deliberately
does not point at a particular AO3 work, tag, creator, or collection.

```python
from ao3 import Work

# Both constructors create a lightweight handle without making a request.
work = Work.from_id(WORK_ID)
work = Work.from_url(f"https://archiveofourown.org/works/{WORK_ID}")

# The first metadata-backed property loads and caches the work page.
print(work.title)
print(work.pseuds)
print(work.words, work.kudos_count, work.hits)

for tag in work.tags:
    print(tag.kind, tag.name)

# Full chapter content is loaded separately from metadata.
for chapter in work.chapters:
    print(chapter.id, chapter.position, chapter.title, chapter.published)
    print(chapter.content)
```

`content`, `summary`, `notes`, and similar properties contain plain text. Their
matching `content_html`, `summary_html`, and `notes_html` properties retain the parsed
HTML fragment when one is available.

## Object and loading model

### Summary, detail, and content states

A handle stores identity, paging options, and a client. It does not load its page in
the constructor:

```python
from ao3 import Tag, Work

work = Work.from_id(WORK_ID)  # no request
tag = Tag(TAG_NAME)  # no request

print(work.title)  # loads work metadata once
print(work.title)  # uses the cached result
```

Objects produced by list pages already contain the information visible in that list.
Reading a summary field such as `title`, `summary`, `tags`, or work statistics does
not immediately fetch every individual work:

```python
tag = Tag(TAG_NAME)

for work in tag.works:
    print(work.title, work.words, work.complete)
```

For a `Work`, these states are deliberately separate:

1. A result from a work index may already contain a summary, tags, creators, and
   statistics.
2. A metadata-only handle loads `detail` the first time a detail-backed property is
   needed.
3. `chapters` requests and parses full work content separately.
4. `comments_page`, `bookmarks_page`, and `kudos.detail` are independent listings and
   therefore have independent caches.

This gives list-heavy applications useful summary data without fetching every work,
while still making the complete resource available through the same object.

There is no parallel `loaded`, `has_next`, or manual `load()` state API. Cached
properties and the data already present on a summary-backed object are the state.
Successful write operations invalidate only the affected cache, such as comments,
bookmarks, or Kudos, so the next read reflects AO3 again.

### Lightweight relationships

Relationship properties intentionally return new lightweight handles. This keeps
loaded state local to the object you chose to use:

```python
first = tag.works[0].fandoms[0]
second = tag.works[0].fandoms[0]

assert first is not second
assert first.name == second.name
```

### Clients and connection lifetime

When no client is passed, models share an internal process-wide `AO3Client`. It is
created only when the first standalone model is constructed, and it is intentionally
not exposed as a public configuration concept. Use an explicit client whenever
session identity or lifetime matters.

Models hold a client through composition; they do not inherit networking behavior.
This keeps cookies, HTTP policy, and request lifetime in `AO3Client`, while the model
owns AO3 terminology, relationships, parsed state, and object-bound actions.

Use an explicit client when you need a bounded connection-pool lifetime,
authentication, cookies, or a different AO3 origin:

```python
from ao3 import AO3Client, Work

with AO3Client() as client:
    by_id = client.work(id=WORK_ID)
    by_url = client.work(url=f"https://archiveofourown.org/works/{WORK_ID}")
    from_class = Work.from_id(WORK_ID, client=client)

    assert by_id.client is client
    assert by_url.client is client
    assert from_class.client is client
```

The same client is passed to related handles returned by a model, so all requests use
the same cookies and connection pool.

### Custom origin, cookies, and transport settings

```python
from ao3 import AO3Client

client = AO3Client(
    base_url="https://archiveofourown.org",
    cookies={"accepted_tos": "20180523"},
    headers={"Accept-Language": "en-US,en;q=0.9"},
    timeout=60,
)

client.base_url = "https://archiveofourown.org"
```

Model URLs and relative download links are resolved against the owning client's
current `base_url`.

The built-in client uses a Chrome user agent and enables HTTP/2. `httpx` negotiates
HTTP/1.1 when HTTP/2 is unavailable. Transport errors and timeouts are left visible to
the caller instead of being hidden behind automatic retries.

### Pagination

Every listing page exposes `page`, `page_count`, `total`, and a model-specific tuple
such as `works`, `comments`, `bookmarks`, `series`, `collections`, or `pseuds`. Page
objects support iteration and `len(page)`; index the contained tuple when random
access is needed:

```python
tag = client.tag(TAG_NAME)
page = tag.works_page

first_work = page.works[0]
print(len(page), page.total, first_work.title)

for work in page:
    print(work.title)

if page.page < page.page_count:
    next_page = tag.copy(page=page.page + 1).works_page
```

The page object itself is intentionally not sequence-indexable. `copy(page=...)`
creates a clean handle with the same identity, options, and client without copying
the original object's loaded state.

## Login

AO3 currently accepts either a username or an email address in its login form.
Credentials are posted directly to AO3; the password is not retained on
`AO3Client`.

```python
import os

from ao3 import AO3Client

with AO3Client(timeout=60) as client:
    client.login(
        os.environ["AO3_LOGIN"],
        os.environ["AO3_PASSWORD"],
        remember_me=False,
    )

    user = client.user("your_ao3_username")

    print(user.id, user.joined, user.title)
    print(user.pseuds)
    print(user.works_page.total)
```

The session cookies remain inside that client's `httpx` cookie jar. If AO3 redirects
a protected request to the login page, `AO3AuthenticationError` is raised.

## Authenticated actions

### Kudos and bookmarks

Write operations use the same object relationships as browsing: actions concerning a
work begin on `Work` or its `Kudos`, while an existing `Bookmark` owns its update and
delete operations. They submit immediately and therefore should use an explicitly
authenticated client when AO3 requires an account.

```python
import os

from ao3 import AO3Client

with AO3Client() as client:
    client.login(os.environ["AO3_LOGIN"], os.environ["AO3_PASSWORD"])

    work = client.work(id=WORK_ID)

    # AO3 records this against the logged-in user. Public works also accept
    # guest Kudos when the client has not logged in.
    work.kudos.leave()

    # The default pseud is selected automatically. Pass pseud_id when the
    # account has multiple pseuds and another one should own the bookmark.
    bookmark = work.create_bookmark(
        notes="Read again after the next update.",
        tags=["To Reread", "Favorite"],
        collections=["collection_name"],
        private=True,
        recommended=False,
    )

    bookmark.update(
        notes="Finished reading.",
        tags=["Finished"],
        private=False,
        recommended=True,
    )

    bookmark.delete()
```

For `Bookmark.update()`, `None` leaves a field unchanged; an empty string or empty
iterable clears text, tags, or collections. AO3 permits only one bookmark per user for
the same item, so a second create is rejected with `AO3ActionError`.

AO3 exposes `POST /kudos` for creation and no `DELETE /kudos/:id` route or delete
form override. Leaving Kudos is therefore one-way for both the sender and the work
creator, and the library deliberately exposes no removal method. Duplicate Kudos,
bookmarking a work twice, attempting to edit somebody else's bookmark, and other
AO3-side business-rule failures raise `AO3ActionError`.

### Comments and replies

Comment creation belongs to the object being commented on. Existing comments own
their reply, update, and delete operations. With an authenticated client, only the
comment text is required; AO3 supplies the account's default pseud through the
returned form:

```python
work = client.work(id=WORK_ID)

comment = work.create_comment("Thank you for writing this!")
reply = comment.reply("One more thought about the ending.")

comment.update("Thank you for writing and sharing this!")
reply.delete()

# A Chapter uses the same operation but posts to that chapter's comment route.
chapter_comment = work.chapters[0].create_comment("I loved this chapter.")
```

When an account has multiple pseuds, pass `pseud_id` to `create_comment()`, `reply()`,
or `update()`. Do not pass `name` or `email` for an authenticated comment.

The optional `name` and `email` arguments exist only because AO3 also supports guest
comments on works whose creators allow them. They are used with a client that has not
logged in:

```python
guest_comment = work.create_comment(
    "A guest comment.",
    name=GUEST_NAME,
    email=GUEST_EMAIL,
)
```

AO3 decides whether the current session may comment, reply, edit, or delete. Rejected
operations raise `AO3ActionError`; moderated comments may remain visible only to the
commenter and work creator until approved.

Comment deletion has no user-facing restore operation. AO3 destroys a childless
comment; when replies exist, it preserves the thread position but wipes the content
and marks the comment as deleted.

### Subscriptions and Marked for Later

AO3 subscriptions apply to a work, series, or user. `subscribe()` returns the
corresponding `Subscription`; calling it for an existing subscription returns that
same server-side relationship instead of creating a duplicate:

```python
work_subscription = work.subscribe()
series_subscription = client.series(SERIES_ID).subscribe()
user_subscription = client.user(USER_LOGIN).subscribe()

print(work_subscription.id, work_subscription.subscribable_type)

# Either form removes a subscription.
work_subscription.delete()
client.series(SERIES_ID).unsubscribe()
user_subscription.delete()
```

Marked for Later is a work-specific reading-list action:

```python
work.mark_for_later()

# AO3 calls the inverse action “Mark as Read”; it removes the work from the
# Marked for Later list rather than exposing a general read/unread property.
work.mark_as_read()
```

Subscriptions and Marked for Later require an authenticated `AO3Client`.

## Browsing tags and languages

```python
from ao3 import Tag

tag = Tag.from_url(TAG_URL)

page = tag.works_page
print(page.page, page.page_count, page.total)

for work in page:
    print(work.id, work.title)

if page.page < page.page_count:
    next_page = tag.copy(page=page.page + 1).works_page
```

Tags also expose bookmarks independently:

```python
for bookmark in tag.bookmarks:
    print(bookmark.pseud.byline, bookmark.notes)
```

`copy(page=...)` creates another lightweight handle carrying the same identity and
client without copying loaded page state. It is available on `Tag`, `User`, `Pseud`,
`Series`, `Collection`, `ExternalWork`, `Language`, and `Kudos`.

Languages are lightweight browse handles too. A work exposes both AO3's short code
and display name:

```python
language = client.language("zh")
print(language.url, language.works_page.total)

work_language = client.work(WORK_ID).language
if work_language:
    print(work_language.short, work_language.name)
```

## Works, chapters, comments, kudos, and downloads

```python
work = client.work(id=WORK_ID)

print(work.title)
print(work.summary)

if work.language:
    print(work.language.short, work.language.name)

print(work.published, work.updated)
print(work.number_of_posted_chapters, work.expected_number_of_chapters)
print(work.comments_count, work.kudos_count, work.bookmarks_count, work.hits)
print(work.complete, work.restricted)

for chapter in work.chapters:
    print(chapter.id, chapter.position, chapter.title, chapter.published)
    print(chapter.work.title, chapter.pseuds)
    print(chapter.summary_html)
    print(chapter.content_html)

    for comment in chapter.comments:
        print(comment.content)

for comment in work.comments:
    if comment.pseud:
        author = comment.pseud.byline
    elif comment.by_anonymous_creator:
        author = "Anonymous Creator"
    else:
        author = comment.guest_name

    print(author, comment.content, comment.replies_count)

    for reply in comment.replies:
        print(reply.depth, reply.content)

second_comment_page = work.comments_for_page(2)
second_bookmark_page = work.bookmarks_for_page(2)

kudos = work.kudos
print(kudos.users_count, kudos.guest_count, kudos.total)
for user in kudos.users:
    print(user.login)
```

Download links are parsed from the work page and resolved through the same client.
Supported formats are `azw3`, `epub`, `mobi`, `pdf`, and `html`:

```python
epub = work.download(file_type="epub")

with open("work.epub", "wb") as file:
    file.write(epub)
```

## Users and pseuds

```python
user = client.user("your_ao3_username")

print(user.id, user.joined)
print(user.bio, user.bio_html)
print(user.default_pseud)

for pseud in user.pseuds:
    print(pseud.name, pseud.byline)

for work in user.works:
    print(work.title)

for series in user.series:
    print(series.title)

for bookmark in user.bookmarks:
    print(bookmark.bookmarkable)

for collection in user.collections:
    print(collection.title)
```

A `Pseud` points back to its owning `User` and exposes its own works, series, and
bookmarks:

```python
pseud = client.pseud("Public Name", "account_login")
print(pseud.user.login)
print(pseud.works_page.total)
```

## Media and fandom indexes

The AO3 media index is cached once per client. `index_fandoms` exposes the fandoms
shown in that index without implying a separate AO3 "hot tag" concept, while
`fandoms` loads the complete fandom list for one media category:

```python
for media in client.media_index:
    print(media.name)

games = client.media("Video Games")

for fandom in games.index_fandoms:
    print(fandom.name, fandom.works_count)

for fandom in games.fandoms:
    print(fandom.letter, fandom.name, fandom.works_count)
```

## Series, collections, bookmarks, and external works

```python
series = client.series(SERIES_ID)
print(series.title, series.summary, series.complete)

for work in series.works:
    print(work.title)

collection = client.collection("collection_name")
print(collection.title, collection.description)
print(collection.closed, collection.moderated)
print(collection.works_count, collection.bookmarks_count)
print(collection.works, collection.bookmarks, collection.subcollections)

bookmark = client.bookmark(BOOKMARK_ID)
print(bookmark.pseud, bookmark.created, bookmark.notes)
print(bookmark.tags, bookmark.collections)
print(bookmark.recommended, bookmark.private)

# bookmarkable is a lightweight Work, Series, ExternalWork, or None.
print(bookmark.bookmarkable)

external = client.external_work(EXTERNAL_WORK_ID)
print(external.title, external.author, external.url)
print(external.tags, external.bookmarks)
```

## API reference

This section documents the application-level API exported from `ao3`. Nested
`Data`, `Reference`, and `Parsed` classes, model parser methods, and
`AO3Client.fetch_*` methods connect the HTML/network layer to the domain layer; they
remain available for library development but are not the recommended entry points
for application code.

Unless noted otherwise, a model accepts `client=AO3Client(...)`. Browse models also
accept `page=1` and `view_adult=True`.

All supported application-level names can be imported from the package root:

```python
from ao3 import (
    AO3ActionError,
    AO3AuthenticationError,
    AO3Client,
    AO3Error,
    AO3InvalidURLError,
    AO3ParseError,
    Bookmark,
    Chapter,
    Collection,
    Comment,
    ExternalWork,
    Kudos,
    Language,
    Media,
    Pseud,
    Series,
    Subscription,
    Tag,
    TagKind,
    User,
    Work,
)
```

### `AO3Client`

```python
AO3Client(
    *,
    base_url="https://archiveofourown.org",
    cookies=None,
    headers=None,
    timeout=30,
    transport=None,
)
```

| Member | Behavior |
| --- | --- |
| `http` | The underlying synchronous `httpx.Client` and its cookie jar. |
| `base_url` | Read/write origin used to resolve model and download URLs. |
| `get(url, **kwargs)` / `post(url, **kwargs)` | Perform an HTTP request, raise for non-success status, and detect redirects to AO3 login. |
| `login(login, password, *, remember_me=False)` | Authenticate the current cookie session and return the client. `login` accepts an AO3 username or email address. |
| `close()` | Close the connection pool. |
| `with AO3Client() as client` | Close the client automatically on context exit. |
| `media_index` | Lazily parse and cache the top-level AO3 media index once per client. |

Resource factories return unloaded handles bound to this client:

| Factory | Result |
| --- | --- |
| `work(id, chapter_id=None, *, view_adult=True)` | `Work` by ID, optionally retaining a chapter ID. |
| `work(url=..., *, view_adult=True)` | `Work` parsed from a work or chapter URL. |
| `tag(name, *, page=1, view_adult=True)` | `Tag` browse handle. |
| `language(short, name=None, *, page=1, view_adult=True)` | `Language` work listing. |
| `media(name)` | `Media` fandom index. |
| `user(login, *, page=1, view_adult=True)` | AO3 `User` account. |
| `pseud(name, user_login, *, page=1, view_adult=True)` | Public `Pseud` owned by a user. |
| `series(series_id, *, page=1, view_adult=True)` | `Series` by ID. |
| `collection(name, *, page=1, view_adult=True)` | `Collection` by collection name. |
| `comment(comment_id)` | `Comment` by ID. |
| `bookmark(bookmark_id, *, view_adult=True)` | `Bookmark` by ID. |
| `external_work(external_work_id, *, page=1, view_adult=True)` | `ExternalWork` by AO3 record ID. |

### `Work`

Create a work with `Work.from_id(work_id, chapter_id=None, ...)`,
`Work.from_url(url, ...)`, `Work(work_id, chapter_id=None, ...)`, or
`client.work(...)`.

| Group | Members |
| --- | --- |
| Identity | `id`, `chapter_id`, `link`, `url`, `view_adult`, `client` |
| Core metadata | `title`, `summary`, `summary_html`, `language`, `published`, `updated`, `words`, `complete`, `restricted` |
| Chapter/statistics metadata | `number_of_posted_chapters`, `expected_number_of_chapters`, `comments_count`, `kudos_count`, `bookmarks_count`, `collections_count`, `hits` |
| People and grouping | `pseuds`, `recipients`, `series`, `collections` |
| Typed tags | `ratings`, `warnings`, `categories`, `fandoms`, `relationships`, `characters`, `additional_tags`, and combined `tags` |
| Work-level content | `notes`, `notes_html`, `endnotes`, `endnotes_html` |
| Lazy resources | `detail`, `chapters`, `download_links`, `comments_page`, `comments`, `kudos`, `bookmarks_page`, `bookmarks` |

| Method | Behavior |
| --- | --- |
| `comments_for_page(page)` | Load a specific `Comment.Page`. |
| `bookmarks_for_page(page)` | Load a specific `Bookmark.Page`. |
| `create_comment(content, *, pseud_id=None, name=None, email=None)` | Create a comment. `pseud_id` is an optional authenticated-pseud override; `name` and `email` are guest-only fields. |
| `create_bookmark(*, notes="", tags=(), collections=(), private=False, recommended=False, pseud_id=None)` | Create the logged-in user's bookmark. Tag/collection items may be strings or model objects. |
| `subscribe()` / `unsubscribe()` | Create or delete the current user's work subscription. |
| `mark_for_later()` / `mark_as_read()` | Add to or remove from AO3's Marked for Later list; each returns the work. |
| `download(file_type=...)` | Return `bytes` for keyword-only `file_type`: `azw3`, `epub`, `mobi`, `pdf`, or `html`. |

When available, `download_links` is a `Work.DownloadLinks` object with absolute
`azw3`, `epub`, `mobi`, `pdf`, and `html` URL attributes.

### `Chapter`

Chapters are fully parsed objects returned by `work.chapters`; they are not separate
metadata handles.

| Group | Members |
| --- | --- |
| Identity | `id`, `work_id`, `position`, `link`, `url`, `title`, `published`, `view_adult`, `client` |
| Creator/content | `pseuds`, `summary`, `summary_html`, `notes`, `notes_html`, `content`, `content_html`, `endnotes`, `endnotes_html` |
| Relationships | `work`, `comments_page`, `comments` |
| Methods | `comments_for_page(page)` and `create_comment(...)`; authenticated comments need only content, while `name` and `email` are guest-only fields. |

### `Kudos`

Use `work.kudos` or `Kudos(work_id, *, page=1, view_adult=True, client=None)`.

| Member | Behavior |
| --- | --- |
| `work_id`, `page`, `url`, `view_adult`, `client` | Identity and request context. |
| `detail` | Cached parsed Kudos page used by the convenience properties below. |
| `users`, `users_count`, `guest_count`, `total`, `page_count` | Paginated public Kudos data. |
| `leave()` | Submit Kudos and invalidate this object's cached Kudos page. |
| `copy(page=...)` | Create a clean handle for another Kudos page. |

### `Tag` and `TagKind`

Use `Tag(name, ...)`, `Tag.from_url(url, ...)`, or `client.tag(name, ...)`.
`TagKind` is one of `rating`, `warning`, `category`, `fandom`, `relationship`,
`character`, or `freeform`.

| Member | Behavior |
| --- | --- |
| `name`, `kind`, `letter`, `link`, `url`, `page`, `view_adult`, `client` | Tag identity, optional classification/index letter, and request context. |
| `works_page`, `works`, `works_count` | Public works carrying this tag. |
| `bookmarks_page`, `bookmarks` | Public bookmarks carrying this tag. |
| `copy(page=...)` | Create another lightweight page handle. |
| `Tag.path(name, *, bookmarks=False)` | Build AO3's escaped work or bookmark path for a tag. |

### `Language`

Use `Language(short, name=None, ...)`, `Language.from_url(url, ...)`, or
`client.language(short, name=None, ...)`.

| Member | Behavior |
| --- | --- |
| `short`, `name`, `link`, `url`, `page`, `view_adult`, `client` | Language identity and request context. |
| `works_page`, `works`, `works_count` | Public works in this language. |
| `copy(page=...)` | Create another lightweight page handle. |

### `Media`

Use `Media(name, ...)`, `Media.from_url(url, ...)`, `client.media(name)`, or iterate
`client.media_index`.

| Member | Behavior |
| --- | --- |
| `name`, `link`, `url`, `client` | Media identity and request context. |
| `index_fandoms` | Fandom tags included in the cached `/media` index. |
| `fandoms` | Complete fandom-tag listing for this media category. |
| `Media.path(name)` | Build the escaped AO3 fandom-index path. |

### `User`

Use `User(login, ...)`, `User.from_url(url, ...)`, or `client.user(login, ...)`.
A `User` is the AO3 account; it is deliberately distinct from its public `Pseud`
identities.

| Group | Members |
| --- | --- |
| Identity/profile | `login`, `link`, `url`, `id`, `joined`, `title`, `bio`, `bio_html`, `detail`, `page`, `view_adult`, `client` |
| Pseuds | `default_pseud`, `pseuds_page`, `pseuds` |
| Listings | `works_page`, `works`, `series_page`, `series`, `bookmarks_page`, `bookmarks`, `collections_page`, `collections` |
| Actions/paging | `subscribe()`, `unsubscribe()`, `copy(page=...)` |

### `Pseud`

Use `Pseud(name, user_login, ...)`, `Pseud.from_url(url, ...)`, or
`client.pseud(name, user_login, ...)`.

| Group | Members |
| --- | --- |
| Identity/summary | `name`, `user_login`, `byline`, `link`, `url`, `description`, `description_html`, `works_count`, `recs_count`, `page`, `view_adult`, `client` |
| Relationships | `user`, `works_page`, `works`, `series_page`, `series`, `bookmarks_page`, `bookmarks` |
| Paging | `copy(page=...)` |

### `Series`

Use `Series(series_id, ...)`, `Series.from_url(url, ...)`, or
`client.series(series_id, ...)`.

| Group | Members |
| --- | --- |
| Identity | `id`, `position`, `link`, `url`, `title`, `page`, `view_adult`, `client` |
| Parsed state | `detail` |
| Metadata | `begun`, `updated`, `summary`, `summary_html`, `notes`, `notes_html`, `words`, `works_count`, `bookmarks_count`, `complete`, `restricted` |
| Relationships | `pseuds`, `works_page`, `works`, `bookmarks_page`, `bookmarks` |
| Actions/paging | `subscribe()`, `unsubscribe()`, `copy(page=...)` |

### `Collection`

Use `Collection(name, ...)`, `Collection.from_url(url, ...)`, or
`client.collection(name, ...)`.

| Group | Members |
| --- | --- |
| Identity | `name`, `title`, `link`, `url`, `page`, `view_adult`, `client` |
| Parsed state | `detail` |
| Profile | `description`, `description_html`, `active_since`, `updated`, `contact`, `intro`, `intro_html`, `faq`, `faq_html`, `rules`, `rules_html` |
| Configuration | `closed`, `moderated`, `unrevealed`, `anonymous`, `challenge_type` |
| Relationships | `tags`, `maintainers`, `works_page`, `works`, `bookmarks_page`, `bookmarks`, `subcollections_page`, `subcollections` |
| Counts/paging | `works_count`, `bookmarks_count`, `subcollections_count`, `copy(page=...)` |

### `Bookmark`

Use `Bookmark(bookmark_id, ...)`, `Bookmark.from_url(url, ...)`, or
`client.bookmark(bookmark_id, ...)`. New bookmarks are created by
`work.create_bookmark()`.

| Group | Members |
| --- | --- |
| Identity | `id`, `link`, `url`, `view_adult`, `client` |
| Parsed state | `detail` |
| Metadata | `pseud`, `created`, `notes`, `notes_html`, `recommended`, `private`, `tags`, `collections` |
| Target | `bookmarkable`, a lightweight `Work`, `Series`, `ExternalWork`, or `None` when unavailable. |
| Mutation | `update(*, notes=None, tags=None, collections=None, private=None, recommended=None, pseud_id=None)`, `delete()` |

For `update()`, `None` preserves a field; empty text or an empty iterable clears the
corresponding value. `delete()` destroys that bookmark and its stored metadata; a new
bookmark can be created later, but it is a new server-side record rather than an undo.

### `ExternalWork`

Use `ExternalWork(external_work_id, ...)`, `ExternalWork.from_url(url, ...)`, or
`client.external_work(external_work_id, ...)`.

| Group | Members |
| --- | --- |
| Identity | `id`, `link`, `ao3_url`, `page`, `view_adult`, `client`; `ao3_url` is the AO3 record URL. |
| Parsed state | `detail` |
| External metadata | `url`, `title`, `author`, `summary`, `summary_html`, `language`, `created`; `url` is the off-site target. |
| AO3 relationships | `tags`, `bookmarks_count`, `related_works_count`, `bookmarks_page`, `bookmarks` |
| Paging | `copy(page=...)` |

### `Comment`

Use `Comment(comment_id, ...)`, `Comment.from_url(url, ...)`, or
`client.comment(comment_id)`. New root comments are created by a `Work` or `Chapter`.

| Group | Members |
| --- | --- |
| Identity/tree | `id`, `link`, `url`, `parent_id`, `depth`, `replies_count`, `replies`, `client` |
| Parsed state | `detail` |
| Author | `pseud`, `guest_name`, `by_anonymous_creator` |
| Time | `created_at`, `created_at_text`, `timezone`, `edited_at`, `edited_at_text` |
| Content/state | `content`, `content_html`, `deleted`, `unreviewed`, `spam`, `hidden` |
| Mutation | `reply(content, *, pseud_id=None, name=None, email=None)`, `update(content, *, pseud_id=None)`, `delete()`; reply `name` and `email` are guest-only fields. |

`created_at_text` and `edited_at_text` retain AO3's display value when it cannot be
represented completely by a Python `datetime` or when the original wording matters.
`delete()` is irreversible through AO3's user-facing routes; a deleted comment cannot
be restored by this library.

### `Subscription`

`Work.subscribe()`, `Series.subscribe()`, and `User.subscribe()` return a
`Subscription`.

| Member | Behavior |
| --- | --- |
| `id`, `subscribable_type`, `subscribable_id` | Server-side subscription identity. The type is `Work`, `Series`, or `User`. |
| `subscribable_link`, `link`, `url`, `client` | Target and subscription paths plus request context. |
| `delete()` | Remove the subscription. AO3 exposes creation and deletion, not a separate update operation. |

### Page objects

| Type | Item tuple | Returned by |
| --- | --- | --- |
| `Work.Page` | `works` | Tag, language, user, pseud, series, or collection work listings |
| `Bookmark.Page` | `bookmarks` | Work, tag, user, pseud, series, collection, or external-work bookmark listings |
| `Comment.Page` | `comments` | Work and chapter comments |
| `Pseud.Page` | `pseuds` | User pseuds |
| `Series.Page` | `series` | User and pseud series listings |
| `Collection.Page` | `collections` | User collections and collection subcollections |

Each page has `page`, `page_count`, and `total`, implements iteration, and implements
`len(page)`. Its item tuple supports normal indexing and slicing.

### Exceptions

| Exception | Meaning |
| --- | --- |
| `AO3Error` | Base class for library-defined errors. |
| `AO3InvalidURLError` | A URL does not match the requested AO3 resource shape; also a `ValueError`. |
| `AO3AuthenticationError` | AO3 redirected to login or rejected credentials. |
| `AO3ActionError` | AO3 rejected, forbids, or does not provide a requested write operation. |
| `AO3ParseError` | Returned HTML lacks the structure required for that resource. |

HTTP status, connection, TLS, and timeout failures remain `httpx` exceptions.

## Adult content

Page-producing constructors accept `view_adult`. It defaults to `True`, which sends
AO3's `view_adult=true` query parameter where required:

```python
work = Work.from_id(WORK_ID, view_adult=False)
tag = client.tag(TAG_NAME, view_adult=False)
```

This option only controls AO3's adult-content interstitial. It does not bypass login,
visibility, or collection restrictions.

## Network and parsing behavior

```python
import httpx

from ao3 import (
    AO3ActionError,
    AO3AuthenticationError,
    AO3InvalidURLError,
    AO3ParseError,
    Work,
)

try:
    work = Work.from_url(f"https://archiveofourown.org/works/{WORK_ID}")
    print(work.title)
except AO3InvalidURLError:
    print("The URL is not a supported AO3 resource URL")
except AO3AuthenticationError:
    print("This resource requires an authenticated AO3 session")
except AO3ActionError as error:
    print(f"AO3 rejected or does not support the action: {error}")
except AO3ParseError:
    print("AO3 returned a page shape that this version could not parse")
except httpx.HTTPError as error:
    print(f"The HTTP request failed: {error}")
```

`ao3-py` deliberately leaves rate limiting, retries, proxies, persistence, and request
scheduling to the application. This keeps the network layer explicit and lets callers
apply policies appropriate to their own workload.

Fields ending in `_html` preserve parsed fragments from AO3; they are not sanitized
by `ao3-py`. Treat them as untrusted input before inserting them into another HTML
document. Their plain-text counterparts are the safer choice when markup is not
needed.

## Disclaimer

This project is unofficial and is not affiliated with the Organization for
Transformative Works. Use it responsibly and respect AO3, its users, and its terms of
service.
