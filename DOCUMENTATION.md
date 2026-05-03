# API Documentation

Base URL: `/api/`. All responses are JSON. All list endpoints paginated with `?page=1&size=10` (max 50).

## Shared Objects

### Author Object

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `type` | string | `"author"` | Always `"author"`. |
| `id` | URL | `"http://node/api/authors/a3b2..."` | FQID (globally unique URL). Use to reference across nodes. |
| `host` | URL | `"http://node/api/"` | Node's API base URL. Use to identify which node. |
| `displayName` | string | `"Alice"` | Display name for UI. |
| `web` | URL | `"http://node/authors/a3b2..."` | HTML profile URL for browsers. |
| `github` | URL | `"https://github.com/alice"` | GitHub URL. May be empty. |
| `profileImage` | URL | `"https://example.com/alice.png"` | Avatar URL. May be empty. |
| `description` | string | `"I'm Alice"` | Bio. May be empty. |

### Entry Object

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `type` | string | `"entry"` | Always `"entry"`. |
| `id` | URL | `"http://node/api/authors/.../entries/..."` | FQID (globally unique URL). |
| `web` | URL | `"http://node/authors/.../entries/..."` | HTML URL for browsers. |
| `title` | string | `"My Post"` | Entry title. May be empty. |
| `description` | string | `"A summary"` | Brief subtitle. May be empty. |
| `contentType` | string | `"text/plain"` | MIME type. Determines how to render `content`. |
| `content` | string | `"Hello world!"` | Body. Format depends on `contentType`. |
| `visibility` | string | `"PUBLIC"` | `PUBLIC`, `UNLISTED`, `FRIENDS`, or `DELETED`. |
| `published` | datetime | `"2026-02-28T12:00:00Z"` | ISO 8601 creation timestamp. |
| `author` | object | `{...}` | Author object (see above). |
| `comments` | object | `{"type":"comments","count":2,"src":[...]}` | Nested (5 newest comments), plus `id`, `web`, `page_number`, `size`, `count`. |
| `likes` | object | `{"type":"likes","count":0,"src":[]}` | Nested (50 newest likes), plus `id`, `web`, `page_number`, `size`, `count`. |

### Comments Object (Detailed Fields)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `type` | string | `"comments"` | Object type identifier. |
| `id` | URL | `"http://node/api/.../comments"` | Endpoint to retrieve full comments list. |
| `web` | URL | `"http://node/...#comments"` | HTML comments page. |
| `page_number` | integer | `1` | Current page. |
| `size` | integer | `5` | Comments returned. |
| `count` | integer | `12` | Total comment count. |
| `src` | array | `[{...}]` | Array of comment objects. |

### Likes Object (Detailed Fields)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `type` | string | `"likes"` | Object type identifier. |
| `id` | URL | `"http://node/api/.../likes"` | Endpoint to retrieve full like list. |
| `web` | URL | `"http://node/...#likes"` | HTML likes page. |
| `page_number` | integer | `1` | Current page. |
| `size` | integer | `50` | Likes returned. |
| `count` | integer | `78` | Total like count. |
| `src` | array | `[{...}]` | Array of like objects. |

---

### Example: Full Entry Response

```json
{
  "type": "entry",
  "id": "http://node/api/authors/a3b2/entries/f1e2",
  "web": "http://node/authors/a3b2/entries/f1e2",
  "title": "My Post",
  "description": "A summary",
  "contentType": "text/plain",
  "content": "Hello world!",
  "visibility": "PUBLIC",
  "published": "2026-02-28T12:00:00Z",
  "author": {
    "type": "author",
    "id": "http://node/api/authors/a3b2",
    "host": "http://node/api/",
    "displayName": "Alice",
    "web": "http://node/authors/a3b2",
    "github": "https://github.com/alice",
    "profileImage": "",
    "description": "I'm Alice"
  },
  "comments": {
    "type": "comments",
    "page_number": 1,
    "size": 5,
    "count": 2,
    "src": []
  },
  "likes": {
    "type": "likes",
    "page_number": 1,
    "size": 50,
    "count": 0,
    "src": []
  }
}
```

### Content Types

| contentType | content format |
|-------------|---------------|
| `text/plain` | Plain text |
| `text/markdown` | Markdown string |
| `image/png`, `image/jpeg` | Base64 string |
| `image/{type}/text/{format}` | JSON: `{"image":"<b64>","text":"<str>"}` |
| `image/gallery` | JSON array: `[{"type":"image/png","data":"<b64>"}]` |
| `image/gallery/text/{format}` | JSON: `{"gallery":[...],"text":"<str>"}` |

### Visibility Rules

| Level | In Stream For | Direct Link |
|-------|--------------|-------------|
| `PUBLIC` | Everyone | Anyone |
| `UNLISTED` | Followers only | Anyone |
| `FRIENDS` | Friends only | Friends + author only |
| `DELETED` | Nobody | Admin only |

Friend = mutual accepted follow. Follower = one-way accepted follow.

### Pagination

All list endpoints accept `?page=<int>&size=<int>`. Default size 10, max 50. Response includes `type`, `page_number`, `size`, `count`, and a data array.

### Pagination Wrapper Object (Detailed Fields)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `type` | string | `"entries"` | Identifies collection type. |
| `page_number` | integer | `1` | Current page number. |
| `size` | integer | `10` | Number of items per page. |
| `count` | integer | `42` | Total number of items across all pages. |
| `<data_key>` | array | `[{...}]` | Array of returned objects (key varies per endpoint). |

### Status Codes

| Code | Meaning | When Used |
|------|----------|-----------|
| 200 | OK | Successful GET or PUT |
| 201 | Created | Successful POST |
| 204 | No Content | Successful DELETE |
| 400 | Bad Request | Missing or invalid request fields |
| 401 | Unauthorized | Not authenticated |
| 403 | Forbidden | Authenticated but not permitted |
| 404 | Not Found | Resource does not exist or intentionally hidden by privacy rules |

Privacy Note: Some endpoints return 404 instead of 403 to prevent leaking existence of private resources.

---

## Authors

### GET `/api/authors/` (List authors)

**When:** Discovering authors on the node. **How:** GET, no auth. **Why:** Only way to list authors. **Why not:** Use detail endpoint for a single author.
**Notes:** Paginated. Only approved authors. Sorted by display name.

Response: `{ "type": "authors", "page_number": 1, "size": 10, "count": 42, "authors": [{...}] }`

| Example | Result |
|---------|--------|
| `GET /api/authors/` | 200 (page 1, 10 authors) |
| `GET /api/authors/?page=2&size=5` | 200 (page 2, 5 per page) |
| `GET /api/authors/?size=500` | 200 (size clamped to 50) |

### GET `/api/authors/{AUTHOR_SERIAL}/` (Get author)

**When:** Viewing a profile. **How:** GET with UUID, no auth. **Why:** Full profile data. **Why not:** Use list to browse.

Response: Author object.

| Example | Result |
|---------|--------|
| `GET /api/authors/a3b2.../` | 200 (author object) |
| `GET /api/authors/nonexistent-uuid/` | 404 |

### PUT `/api/authors/{AUTHOR_SERIAL}/` (Update profile)

**When:** Author edits own profile. **How:** PUT with JSON, auth as this author. **Why:** Only way to update via API. **Why not:** Can't update others.
**Notes:** Partial update supported. `id` and `host` are read-only.

Request fields:

| Field | Type | Required | Example | Purpose |
|-------|------|----------|---------|---------|
| `displayName` | string | No | `"New Name"` | Update display name. |
| `github` | URL | No | `"https://github.com/me"` | Update GitHub. Empty to clear. |
| `profileImage` | URL | No | `"https://example.com/me.png"` | Update avatar. Empty to clear. |
| `description` | string | No | `"New bio"` | Update bio. Empty to clear. |

| Example | Result |
|---------|--------|
| `PUT .../` as self with `{"displayName":"New"}` | 200 (updated author) |
| `PUT .../` as different user | 403 |
| `PUT .../` not authenticated | 403 |

### GET `/api/authors/{AUTHOR_FQID}` (Get by FQID)

**When:** Remote node lookup by FQID. **How:** Percent-encode FQID in path. **Why:** Remote nodes store FQIDs. **Why not:** Use UUID endpoint if you have it.

| Example | Result |
|---------|--------|
| `GET /api/authors/http%3A%2F%2Fnode%2Fapi%2Fauthors%2Fa3b2...` | 200 (author object) |
| `GET /api/authors/http%3A%2F%2Fexample.com%2Fnobody` | 404 |

---

## Entries

### GET `/api/authors/{AUTHOR_SERIAL}/entries/` (List entries)

**When:** Browsing an author's posts. **How:** GET with author UUID, auth optional. **Why:** Auto-filters by visibility. **Why not:** Use detail for single entry.
**Notes:** Paginated. Newest first by `published`. DELETED never returned.

Visibility filtering:

| Requester | Sees |
|-----------|------|
| No auth / stranger | PUBLIC |
| Follower | PUBLIC + UNLISTED |
| Friend | PUBLIC + UNLISTED + FRIENDS |
| Author themselves | All non-deleted |

Response: `{ "type": "entries", "page_number": 1, "size": 10, "count": 5, "src": [{...}] }`

| Example | Result |
|---------|--------|
| `GET .../entries/` no auth | 200 (PUBLIC only) |
| `GET .../entries/` as follower | 200 (PUBLIC + UNLISTED) |
| `GET .../entries/` as friend | 200 (PUBLIC + UNLISTED + FRIENDS) |
| `GET .../entries/` as author | 200 (all non-deleted) |
| `GET .../entries/?page=2&size=5` | 200 (page 2) |

### POST `/api/authors/{AUTHOR_SERIAL}/entries/` (Create entry)

**When:** Author creates a post. **How:** POST with JSON, auth as this author. **Why:** API equivalent of HTML form. **Why not:** Use PUT to edit existing.
**Notes:** All fields optional with defaults.

Request fields:

| Field | Type | Required | Default | Example | Purpose |
|-------|------|----------|---------|---------|---------|
| `title` | string | No | `""` | `"My Post"` | Entry title. |
| `description` | string | No | `""` | `"Summary"` | Description. |
| `contentType` | string | No | `"text/plain"` | `"text/markdown"` | MIME type. |
| `content` | string | No | `""` | `"Hello!"` | Body. |
| `visibility` | string | No | `"PUBLIC"` | `"FRIENDS"` | Visibility level. |

Response: 201 with created entry object.

| Example | Result |
|---------|--------|
| `POST .../entries/` as author with full body | 201 (entry created) |
| `POST .../entries/` not authenticated | 401 |
| `POST .../entries/` as different user | 403 |

### GET `/api/authors/{AUTHOR_SERIAL}/entries/{ENTRY_SERIAL}/` (Get entry)

**When:** Direct link to an entry. **How:** GET with both UUIDs, auth optional. **Why:** Full entry with comments/likes. **Why not:** Use list to browse.
**Notes:** Returns 404 (not 403) when denied, to hide whether entry exists.

Access rules:

| Visibility | No auth | Stranger | Follower | Friend | Author | Admin |
|------------|---------|----------|----------|--------|--------|-------|
| PUBLIC | 200 | 200 | 200 | 200 | 200 | 200 |
| UNLISTED | 200 | 200 | 200 | 200 | 200 | 200 |
| FRIENDS | 404 | 404 | 404 | 200 | 200 | 404 |
| DELETED | 404 | 404 | 404 | 404 | 404 | 200 |

| Example | Result |
|---------|--------|
| `GET .../entries/f1e2.../` public entry, no auth | 200 |
| `GET .../entries/f1e2.../` FRIENDS entry, as friend | 200 |
| `GET .../entries/f1e2.../` FRIENDS entry, as stranger | 404 |
| `GET .../entries/f1e2.../` DELETED entry, as admin | 200 |
| `GET .../entries/f1e2.../` DELETED entry, as author | 404 |

### PUT `/api/authors/{AUTHOR_SERIAL}/entries/{ENTRY_SERIAL}/` (Update entry)

**When:** Author edits their post. **How:** PUT with full JSON, auth as author. **Why:** Only way to edit via API. **Why not:** Use DELETE to remove, POST to create.
**Notes:** Full replacement (all fields required or returns 400).

Request fields:

| Field | Type | Required | Example | Purpose |
|-------|------|----------|---------|---------|
| `title` | string | Yes | `"Updated"` | New title. |
| `description` | string | Yes | `""` | New description. |
| `contentType` | string | Yes | `"text/plain"` | New MIME type. |
| `content` | string | Yes | `"New body"` | New content. |
| `visibility` | string | Yes | `"FRIENDS"` | New visibility. |

Response: 200 with updated entry object.

| Example | Result |
|---------|--------|
| `PUT .../` as author, full body | 200 (updated) |
| `PUT .../` as author, partial body `{"title":"x"}` | 400 |
| `PUT .../` as different user | 403 |
| `PUT .../` not authenticated | 401 |

### DELETE `/api/authors/{AUTHOR_SERIAL}/entries/{ENTRY_SERIAL}/` (Delete entry)

**When:** Author removes a post. **How:** DELETE, auth as author, no body. **Why:** Soft-deletes (sets visibility=DELETED, stays in DB). **Why not:** Irreversible via API.
**Notes:** After deletion: list excludes it, detail returns 404 (admin gets 200).

| Example | Result |
|---------|--------|
| `DELETE .../` as author | 204 |
| `DELETE .../` as different user | 403 |
| `DELETE .../` not authenticated | 401 |
| `GET .../` after delete, as author | 404 |
| `GET .../` after delete, as admin | 200 |

### GET `/api/entries/{ENTRY_FQID}` (Get by FQID)

**When:** Remote node lookup. **How:** Percent-encode FQID. **Why:** Remote nodes store FQIDs. **Why not:** Use UUID endpoint if available.
Same visibility rules as serial-based GET.

| Example | Result |
|---------|--------|
| `GET /api/entries/http%3A%2F%2Fnode%2Fapi%2Fauthors%2F...%2Fentries%2F...` | 200 |
| Non-existent FQID | 404 |

### GET `/api/authors/{AUTHOR_SERIAL}/entries/{ENTRY_SERIAL}/image` (Get image by serial)

**When:** Displaying an entry's image in `<img src>`. **How:** GET, returns raw bytes. **Why:** No client-side base64 decoding needed. **Why not:** Only works for pure image entries (not combined or gallery types).
**Notes:** `Content-Type` header matches the entry's type. Same visibility rules.

| Example | Result |
|---------|--------|
| `GET .../image` on `image/png` entry | 200 (raw PNG bytes) |
| `GET .../image` on `text/plain` entry | 404 |
| `GET .../image` on `image/png/text/plain` entry | 404 |

### GET `/api/entries/{ENTRY_FQID}/image` (Get image by FQID)

**When:** Displaying an image using the entry's FQID. **How:** Percent-encode FQID, append `/image`. **Why:** Remote nodes reference entries by FQID. **Why not:** Use serial-based endpoint if you have the UUIDs.
Same visibility rules and limitations as serial-based image endpoint.

| Example | Result |
|---------|--------|
| `GET /api/entries/http%3A%2F%2Fnode%2F...%2Fentries%2F.../image` on image entry | 200 (raw bytes) |
| `GET /api/entries/http%3A%2F%2Fnode%2F...%2Fentries%2F.../image` on text entry | 404 |
| Non-existent FQID | 404 |

---

## Following

### GET `/api/authors/{AUTHOR_SERIAL}/following` (List following)

**When:** Viewing who an author follows. **How:** GET, auth as this author. **Why:** Returns accepted follows. **Why not:** Use followers endpoint for the reverse.
**Notes:** Paginated. Remote authors appear as stubs if not cached locally.

Response: `{ "type": "following", "page_number": 1, "size": 10, "count": 3, "following": [{...}] }`

| Example | Result |
|---------|--------|
| `GET .../following` as this author | 200 (list of followed authors) |
| `GET .../following` as different user | 401 |
| `GET .../following` not authenticated | 401 |

### GET/PUT/DELETE `/api/authors/{AUTHOR_SERIAL}/following/{FOREIGN_FQID}` (Manage following)

**GET:** Check if following someone. 200 = yes (accepted), 404 = no or pending. Auth as this author.
**PUT:** Send follow request. Creates pending follow. Idempotent (201 first time, 200 after). Auth as this author.
**DELETE:** Unfollow. Removes the record entirely. Auth as this author.

| Example | Method | Result |
|---------|--------|--------|
| Check following (accepted) | GET | 200 (author object) |
| Check following (not following) | GET | 404 |
| Send follow request (new) | PUT | 201 |
| Send follow request (exists) | PUT | 200 |
| Unfollow | DELETE | 204 |
| Unfollow (no record) | DELETE | 404 |

---

## Followers

### GET `/api/authors/{AUTHOR_SERIAL}/followers` (List followers)

**When:** Viewing who follows an author. **How:** GET, no auth required. **Why:** Followers are public info. **Why not:** Use following endpoint for the reverse.
**Notes:** Paginated. Only accepted follows.

Response: `{ "type": "followers", "page_number": 1, "size": 10, "count": 2, "followers": [{...}] }`

| Example | Result |
|---------|--------|
| `GET .../followers` | 200 (list of followers) |
| `GET .../followers?page=2&size=5` | 200 (paginated) |

### GET/PUT/DELETE `/api/authors/{AUTHOR_SERIAL}/followers/{FOREIGN_FQID}` (Manage followers)

**GET:** Check if someone is a follower. 200 = accepted follower, 404 = not. No auth required.
**PUT:** Accept a pending follow request. Auth as this author. 404 if no pending request.
**DELETE:** Reject/remove a follower. Auth as this author.

| Example | Method | Result |
|---------|--------|--------|
| Check follower (accepted) | GET | 200 (author object) |
| Check follower (not a follower) | GET | 404 |
| Accept pending request | PUT | 200 (author object) |
| Accept (no pending request) | PUT | 404 |
| Remove follower | DELETE | 204 |
| Remove (not authenticated) | DELETE | 401 |
| Remove (no record) | DELETE | 404 |

---

## Follow Requests

### GET `/api/authors/{AUTHOR_SERIAL}/follow_requests` (List pending requests)

**When:** Viewing follow requests to approve/reject. **How:** GET, auth as this author. **Why:** Shows pending requests. **Why not:** Use followers endpoint for accepted followers.
**Notes:** Not paginated (returns all pending requests).

Response: `{ "type": "follow_requests", "follow_requests": [{ "type": "follow", "summary": "Bob wants to follow Alice", "actor": {...}, "object": {...} }] }`

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `type` | string | `"follow_requests"` | Always `"follow_requests"`. |
| `follow_requests` | array | `[{...}]` | Pending request objects. |
| `[].type` | string | `"follow"` | Always `"follow"`. |
| `[].summary` | string | `"Bob wants to follow Alice"` | Human-readable. For display. |
| `[].actor` | object | `{...}` | Author object of the person requesting to follow. |
| `[].object` | object | `{...}` | Author object of the person being followed (you). |

| Example | Result |
|---------|--------|
| `GET .../follow_requests` as this author | 200 (list of pending requests) |
| `GET .../follow_requests` not authenticated | 401 |

---

## Inbox

### POST `/api/authors/{AUTHOR_SERIAL}/inbox`
### PUT `/api/authors/{AUTHOR_SERIAL}/inbox`

**When:** Remote node sends or updates an inbox item.  
**How:** `POST` creates/ingests, `PUT` updates existing item semantics for entries.  
**Auth:** Node-to-node authentication is required by remote auth checks.  
**Supported `type`:** `follow`, `author`, `entry`, `comment`, `like`.

If `type` is not in the supported set:

```json
{
  "detail": "Unsupported inbox item type. Expected one of: follow, author, entry, comment, like."
}
```

Status: `400 Bad Request`

### Inbox Item Type Behavior (Actual Code)

| Type | Validation | Side Effects | Response |
|------|------------|--------------|----------|
| `author` | `id` required | Upserts remote author profile cache | `201 {"detail":"Author received."}` |
| `entry` | none beyond type | Upserts entry payload in inbox by `payload.id` | `POST -> 201`, `PUT -> 200` with `{"detail":"Entry received."}` |
| `comment` | `author.id`, `entry`, `comment` required | Stores inbox payload + creates local `Comment` if absent | `201 {"detail":"Comment received."}` |
| `like` | `author.id`, `object` required | Stores inbox payload + creates local `Like` if absent | `201 {"detail":"Like received."}` |
| `follow` | `actor.id` required; `status` in `REQUESTED, ACCEPTED, REJECTED, UNFOLLOW` | Stores inbox item + updates follow graph | depends on status (below) |

### Follow Status Handling

| `follow.status` | Effect | Response |
|-----------------|--------|----------|
| `REQUESTED` | Creates pending follow (`accepted=False`) from actor -> target | `201 {"detail":"Follow received."}` if new, else `200` |
| `ACCEPTED` | Marks target-side acceptance relationship | `200 {"detail":"Follow acceptance received."}` |
| `REJECTED` | Removes relationship records for the pair | `200 {"detail":"Follow rejection received."}` |
| `UNFOLLOW` | Deletes actor->target follow record | `200 {"detail":"Unfollow received."}` |

### Real Response Examples

#### 1. Entry delivery

Request (`POST /api/authors/{AUTHOR_SERIAL}/inbox`):

```json
{
  "type": "entry",
  "id": "https://remote.example/api/authors/4f3f.../entries/9c51...",
  "title": "Remote Entry",
  "description": "Delivered via inbox",
  "contentType": "text/plain",
  "content": "Hello from remote node",
  "visibility": "PUBLIC",
  "author": {
    "type": "author",
    "id": "https://remote.example/api/authors/4f3f...",
    "host": "https://remote.example/",
    "displayName": "RemoteUser"
  }
}
```

Response:

```json
{
  "detail": "Entry received."
}
```

Status: `201 Created`

#### 2. Comment delivery

Request:

```json
{
  "type": "comment",
  "id": "https://remote.example/api/commented/2175...",
  "author": {
    "id": "https://remote.example/api/authors/4f3f..."
  },
  "entry": "https://transparent.example/api/authors/aa11.../entries/bb22...",
  "comment": "Nice post!",
  "contentType": "text/plain"
}
```

Response:

```json
{
  "detail": "Comment received."
}
```

Status: `201 Created`

#### 3. Like delivery

Request:

```json
{
  "type": "like",
  "id": "https://remote.example/api/liked/8ad2...",
  "author": {
    "id": "https://remote.example/api/authors/4f3f..."
  },
  "object": "https://transparent.example/api/authors/aa11.../entries/bb22..."
}
```

Response:

```json
{
  "detail": "Like received."
}
```

Status: `201 Created`

#### 4. Follow request delivery

Request:

```json
{
  "type": "follow",
  "status": "REQUESTED",
  "actor": {
    "id": "https://remote.example/api/authors/4f3f..."
  },
  "object": {
    "id": "https://transparent.example/api/authors/aa11..."
  }
}
```

Response (new request):

```json
{
  "detail": "Follow received."
}
```

Status: `201 Created`

### Adapter Normalization Examples

The inbox applies adapter-specific normalization before processing.

#### SteelBlue follow status normalization

Input:

```json
{
  "type": "follow",
  "status": "REQUESTING",
  "actor": {"id": "https://steelblue.example/api/authors/a1"},
  "object": {"id": "https://transparent.example/api/authors/b2"}
}
```

Normalized payload used internally:

```json
{
  "type": "follow",
  "status": "REQUESTED",
  "actor": {"type": "author", "id": "https://steelblue.example/api/authors/a1", "host": "https://steelblue.example/", "displayName": "a1"},
  "object": {"type": "author", "id": "https://transparent.example/api/authors/b2", "host": "https://transparent.example/", "displayName": "b2"}
}
```

#### PapayaWhip post alias normalization

Input:

```json
{
  "type": "post",
  "id": "https://papayawhip.example/api/authors/a1/posts/p9",
  "author": {"id": "https://papayawhip.example/api/authors/a1"},
  "content_type": "text/markdown",
  "content": "# hello"
}
```

Normalized payload used internally:

```json
{
  "type": "entry",
  "id": "https://papayawhip.example/api/authors/a1/posts/p9",
  "author": {"type": "author", "id": "https://papayawhip.example/api/authors/a1", "host": "https://papayawhip.example/", "displayName": "a1"},
  "content_type": "text/markdown",
  "contentType": "text/markdown",
  "ContentType": "text/markdown",
  "content": "# hello"
}
```