from __future__ import annotations

import uuid

from django.conf import settings
from rest_framework.test import APITestCase

from authors.models import Author
from entries.models import Entry
from interactions.models import Comment, Like
from social.models import Follow


def _create_author(*, username: str, display_name: str, approved: bool = True) -> Author:
    author = Author.objects.create_user(
        username=username,
        password="pw123456!",
        display_name=display_name,
        host=getattr(settings, "SERVICE_URL", "http://testserver/api/"),
        fqid="",
    )
    author.approved = approved
    author.save()
    return author


class CommentsAndLikesIntegrationTests(APITestCase):
    def test_comments_and_likes_appear_on_entry_api_response(self):
        author = _create_author(username="author", display_name="Author")
        liker = _create_author(username="liker", display_name="Liker")
        commenter = _create_author(
            username="commenter", display_name="Commenter")

        entry = Entry.objects.create(
            author=author,
            title="t",
            description="",
            content="hello",
            content_type="text/plain",
            visibility="PUBLIC",
            fqid="",
        )

        # No comment/like API exists; create them directly (user story)
        for i in range(2):
            Comment.objects.create(
                fqid=f"{author.host}comments/{uuid.uuid4()}",
                author_fqid=commenter.fqid,
                entry_fqid=entry.fqid,
                comment=f"c{i}",
                content_type="text/plain",
            )

        for _ in range(3):
            Like.objects.create(
                fqid=f"{author.host}likes/{uuid.uuid4()}",
                author_fqid=liker.fqid,
                object_fqid=entry.fqid,
            )

        # Verify via the entry API (Android client style)
        resp = self.client.get(f"/api/authors/{author.id}/entries/{entry.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "entry")

        self.assertEqual(resp.data["comments"]["type"], "comments")
        self.assertEqual(resp.data["comments"]["count"], 2)
        self.assertEqual(len(resp.data["comments"]["src"]), 2)
        self.assertEqual(resp.data["comments"]["src"][0]["type"], "comment")

        self.assertEqual(resp.data["likes"]["type"], "likes")
        self.assertEqual(resp.data["likes"]["count"], 3)
        self.assertEqual(len(resp.data["likes"]["src"]), 3)
        self.assertEqual(resp.data["likes"]["src"][0]["type"], "like")

    def test_author_can_comment_and_like_accessible_entry(self):
        author = _create_author(username="entry_owner",
                                display_name="Entry Owner")
        commenter = _create_author(
            username="entry_commenter", display_name="Entry Commenter")
        entry = Entry.objects.create(
            author=author,
            title="public",
            description="",
            content="hello",
            content_type="text/plain",
            visibility="PUBLIC",
            fqid="",
        )

        self.client.force_authenticate(user=commenter)

        comment_resp = self.client.post(
            f"/api/authors/{author.id}/entries/{entry.id}/comments",
            {"comment": "nice post", "contentType": "text/plain"},
            format="json",
        )
        self.assertEqual(comment_resp.status_code, 201)
        self.assertEqual(comment_resp.data["comment"], "nice post")

        like_resp = self.client.post(
            f"/api/authors/{author.id}/entries/{entry.id}/likes",
            {},
            format="json",
        )
        self.assertEqual(like_resp.status_code, 201)

        like_resp_repeat = self.client.post(
            f"/api/authors/{author.id}/entries/{entry.id}/likes",
            {},
            format="json",
        )
        self.assertEqual(like_resp_repeat.status_code, 200)
        self.assertEqual(Like.objects.filter(
            object_fqid=entry.fqid, author_fqid=commenter.fqid).count(), 1)

    def test_author_can_like_comment_they_can_access(self):
        author = _create_author(username="owner2", display_name="Owner2")
        commenter = _create_author(
            username="commenter2", display_name="Commenter2")
        liker = _create_author(username="liker2", display_name="Liker2")
        entry = Entry.objects.create(
            author=author,
            title="public",
            description="",
            content="hello",
            content_type="text/plain",
            visibility="PUBLIC",
            fqid="",
        )
        comment = Comment.objects.create(
            fqid=f"{author.host}comments/{uuid.uuid4()}",
            author_fqid=commenter.fqid,
            entry_fqid=entry.fqid,
            comment="great",
            content_type="text/plain",
        )

        self.client.force_authenticate(user=liker)
        like_resp = self.client.post(
            f"/api/authors/{author.id}/entries/{entry.id}/comments/{comment.id}/likes",
            {},
            format="json",
        )
        self.assertEqual(like_resp.status_code, 201)
        self.assertEqual(Like.objects.filter(
            object_fqid=comment.fqid, author_fqid=liker.fqid).count(), 1)

    def test_friends_only_comment_visibility_is_friend_or_comment_author(self):
        owner = _create_author(username="owner3", display_name="Owner3")
        friend = _create_author(username="friend3", display_name="Friend3")
        commenter = _create_author(
            username="commenter3", display_name="Commenter3")
        outsider = _create_author(
            username="outsider3", display_name="Outsider3")

        # Make friend and commenter initially friends with owner.
        Follow.objects.create(follower_fqid=owner.fqid,
                              following_fqid=friend.fqid, accepted=True)
        Follow.objects.create(follower_fqid=friend.fqid,
                              following_fqid=owner.fqid, accepted=True)
        Follow.objects.create(follower_fqid=owner.fqid,
                              following_fqid=commenter.fqid, accepted=True)
        Follow.objects.create(follower_fqid=commenter.fqid,
                              following_fqid=owner.fqid, accepted=True)

        entry = Entry.objects.create(
            author=owner,
            title="friends",
            description="",
            content="hello",
            content_type="text/plain",
            visibility="FRIENDS",
            fqid="",
        )

        # Commenter comments while still a friend.
        self.client.force_authenticate(user=commenter)
        post_comment_resp = self.client.post(
            f"/api/authors/{owner.id}/entries/{entry.id}/comments",
            {"comment": "my comment", "contentType": "text/plain"},
            format="json",
        )
        self.assertEqual(post_comment_resp.status_code, 201)

        # Another friend comment.
        Comment.objects.create(
            fqid=f"{owner.host}comments/{uuid.uuid4()}",
            author_fqid=friend.fqid,
            entry_fqid=entry.fqid,
            comment="friend comment",
            content_type="text/plain",
        )

        # Remove mutual friendship for commenter afterwards.
        Follow.objects.filter(follower_fqid=owner.fqid,
                              following_fqid=commenter.fqid).delete()
        Follow.objects.filter(follower_fqid=commenter.fqid,
                              following_fqid=owner.fqid).delete()

        # Comment author can still see their own comment, but not all comments.
        self.client.force_authenticate(user=commenter)
        commenter_get_resp = self.client.get(
            f"/api/authors/{owner.id}/entries/{entry.id}/comments"
        )
        self.assertEqual(commenter_get_resp.status_code, 200)
        self.assertEqual(commenter_get_resp.data["count"], 1)

        # Friend can see all comments.
        self.client.force_authenticate(user=friend)
        friend_get_resp = self.client.get(
            f"/api/authors/{owner.id}/entries/{entry.id}/comments"
        )
        self.assertEqual(friend_get_resp.status_code, 200)
        self.assertEqual(friend_get_resp.data["count"], 2)

        # Outsider sees nothing.
        self.client.force_authenticate(user=outsider)
        outsider_resp = self.client.get(
            f"/api/authors/{owner.id}/entries/{entry.id}/comments"
        )
        self.assertEqual(outsider_resp.status_code, 404)


class CommentedAndLikedAPITests(APITestCase):
    def test_entry_fqid_comments_and_likes_endpoints(self):
        owner = _create_author(username="owner_fqid",
                               display_name="Owner FQID")
        actor = _create_author(username="actor_fqid",
                               display_name="Actor FQID")

        entry = Entry.objects.create(
            author=owner,
            title="public",
            description="",
            content="hello",
            content_type="text/plain",
            visibility="PUBLIC",
            fqid="",
        )
        comment = Comment.objects.create(
            fqid=f"{owner.host}authors/{owner.id}/commented/{uuid.uuid4()}",
            author_fqid=actor.fqid,
            entry_fqid=entry.fqid,
            comment="nice",
            content_type="text/plain",
        )
        Like.objects.create(
            fqid=f"{owner.host}authors/{actor.id}/liked/{uuid.uuid4()}",
            author_fqid=actor.fqid,
            object_fqid=entry.fqid,
        )

        encoded_entry_fqid = entry.fqid.replace(":", "%3A").replace("/", "%2F")
        comments_resp = self.client.get(
            f"/api/entries/{encoded_entry_fqid}/comments")
        likes_resp = self.client.get(
            f"/api/entries/{encoded_entry_fqid}/likes")

        self.assertEqual(comments_resp.status_code, 200)
        self.assertEqual(comments_resp.data["type"], "comments")
        self.assertEqual(comments_resp.data["count"], 1)
        self.assertEqual(comments_resp.data["src"][0]["id"], comment.fqid)

        self.assertEqual(likes_resp.status_code, 200)
        self.assertEqual(likes_resp.data["type"], "likes")
        self.assertEqual(likes_resp.data["count"], 1)

    def test_commented_and_liked_endpoints(self):
        owner = _create_author(username="owner_hist",
                               display_name="Owner Hist")
        entry = Entry.objects.create(
            author=owner,
            title="public",
            description="",
            content="hello",
            content_type="text/plain",
            visibility="PUBLIC",
            fqid="",
        )

        self.client.force_authenticate(user=owner)
        post_resp = self.client.post(
            f"/api/authors/{owner.id}/commented",
            {
                "type": "comment",
                "entry": entry.fqid,
                "comment": "history comment",
                "contentType": "text/plain",
            },
            format="json",
        )
        self.assertEqual(post_resp.status_code, 201)

        created_comment = Comment.objects.get(fqid=post_resp.data["id"])
        created_like = Like.objects.create(
            fqid=f"{owner.host}authors/{owner.id}/liked/{uuid.uuid4()}",
            author_fqid=owner.fqid,
            object_fqid=created_comment.fqid,
        )

        commented_resp = self.client.get(f"/api/authors/{owner.id}/commented")
        liked_resp = self.client.get(f"/api/authors/{owner.id}/liked")
        comment_detail_resp = self.client.get(
            f"/api/authors/{owner.id}/commented/{created_comment.id}"
        )
        like_detail_resp = self.client.get(
            f"/api/authors/{owner.id}/liked/{created_like.id}"
        )

        encoded_comment_fqid = created_comment.fqid.replace(
            ":", "%3A").replace("/", "%2F")
        encoded_like_fqid = created_like.fqid.replace(
            ":", "%3A").replace("/", "%2F")
        comment_by_fqid_resp = self.client.get(
            f"/api/commented/{encoded_comment_fqid}")
        like_by_fqid_resp = self.client.get(f"/api/liked/{encoded_like_fqid}")

        self.assertEqual(commented_resp.status_code, 200)
        self.assertEqual(commented_resp.data["type"], "comments")
        self.assertEqual(commented_resp.data["count"], 1)

        self.assertEqual(liked_resp.status_code, 200)
        self.assertEqual(liked_resp.data["type"], "likes")
        self.assertEqual(liked_resp.data["count"], 1)

        self.assertEqual(comment_detail_resp.status_code, 200)
        self.assertEqual(comment_detail_resp.data["id"], created_comment.fqid)
        self.assertEqual(like_detail_resp.status_code, 200)
        self.assertEqual(like_detail_resp.data["id"], created_like.fqid)

        self.assertEqual(comment_by_fqid_resp.status_code, 200)
        self.assertEqual(comment_by_fqid_resp.data["id"], created_comment.fqid)
        self.assertEqual(like_by_fqid_resp.status_code, 200)
        self.assertEqual(like_by_fqid_resp.data["id"], created_like.fqid)

    def test_inbox_accepts_comment_and_like_payloads(self):
        owner = _create_author(username="inbox_owner",
                               display_name="Inbox Owner")
        remote_author_fqid = "http://remote.example/api/authors/remote-user"

        comment_payload = {
            "type": "comment",
            "id": "http://remote.example/api/authors/remote-user/commented/123",
            "author": {"type": "author", "id": remote_author_fqid},
            "entry": "http://remote.example/api/authors/someone/entries/1",
            "comment": "remote comment",
            "contentType": "text/plain",
        }
        like_payload = {
            "type": "like",
            "id": "http://remote.example/api/authors/remote-user/liked/456",
            "author": {"type": "author", "id": remote_author_fqid},
            "object": "http://remote.example/api/authors/someone/entries/1",
        }

        comment_resp = self.client.post(
            f"/api/authors/{owner.id}/inbox", comment_payload, format="json"
        )
        like_resp = self.client.post(
            f"/api/authors/{owner.id}/inbox", like_payload, format="json"
        )

        self.assertEqual(comment_resp.status_code, 201)
        self.assertEqual(like_resp.status_code, 201)
        self.assertTrue(Comment.objects.filter(
            fqid=comment_payload["id"]).exists())
        self.assertTrue(Like.objects.filter(fqid=like_payload["id"]).exists())
