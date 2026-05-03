"""URL routing for the authors app."""

from django.urls import path, re_path
from . import views
from entries.views import (
    AuthorCommentDetailAPIView,
    AuthorCommentedAPIView,
    AuthorCommentedByFQIDAPIView,
    AuthorLikeDetailAPIView,
    AuthorLikedAPIView,
    AuthorLikedByFQIDAPIView,
    CommentByFQIDAPIView,
    CommentLikesAPIView,
    EntryCommentsAPIView,
    EntryCommentDetailAPIView,
    EntryDetailAPIView,
    EntryImageBySerialAPIView,
    EntryLikesAPIView,
    EntryListCreateAPIView,
    LikeByFQIDAPIView,
)
from inbox.views import InboxAPIView

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# ── Browser (HTML) routes ────────────────────────────────────────────────────
browser_urlpatterns = [
    path("accounts/register/", views.register, name="register"),
    path("authors/", views.author_list, name="author_list"),
    path("authors/<uuid:author_id>/approve-signup/",
         views.approve_signup, name="approve_signup"),
    path("authors/<uuid:author_id>/reject-signup/",
         views.reject_signup, name="reject_signup"),
    path("authors/<uuid:author_id>/toggle-staff/",
         views.toggle_author_staff, name="toggle_author_staff"),
    path("authors/<uuid:author_id>/toggle-active/",
         views.toggle_author_active, name="toggle_author_active"),
    path("authors/<uuid:author_id>/delete-account/",
         views.delete_author_account, name="delete_author_account"),
    path("authors/remote-follow/", views.follow_remote_author,
         name="follow_remote_author"),
    path("authors/remote-unfollow/", views.unfollow_remote_author,
         name="unfollow_remote_author"),
    path("authors/remote-profile/", views.remote_author_profile,
         name="remote_author_profile"),
    path("authors/<uuid:author_id>/follow/",
         views.follow_author, name="follow_author"),
    path("authors/<uuid:author_id>/unfollow/",
         views.unfollow_author, name="unfollow_author"),
    path("authors/<uuid:author_id>/approve/",
         views.approve_follow, name="approve_follow"),
    path("authors/<uuid:author_id>/deny/",
         views.deny_follow, name="deny_follow"),
    path("authors/remote-approve/",
         views.approve_follow_by_fqid, name="approve_follow_by_fqid"),
    path("authors/remote-deny/",
         views.deny_follow_by_fqid, name="deny_follow_by_fqid"),
    path("authors/<uuid:author_id>/", views.author_profile, name="author_profile"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
]

# ── REST API routes ──────────────────────────────────────────────────────────
api_urlpatterns = [
    # Author list (GET)
    path("api/authors/", views.AuthorListAPIView.as_view(), name="author_list_api"),

    # Entries (under an author)
    path(
        "api/authors/<uuid:author_fqid>/entries/",
        EntryListCreateAPIView.as_view(),
        name="author_entries",
    ),
    path(
        "api/authors/<uuid:author_fqid>/entries/<uuid:entry_fqid>/",
        EntryDetailAPIView.as_view(),
        name="author_entry_detail",
    ),
    path(
        "api/authors/<uuid:author_fqid>/entries/<uuid:entry_fqid>/image",
        EntryImageBySerialAPIView.as_view(),
        name="author_entry_image",
    ),
    path(
        "api/authors/<uuid:author_fqid>/entries/<uuid:entry_fqid>/comments",
        EntryCommentsAPIView.as_view(),
        name="author_entry_comments",
    ),
    path(
        "api/authors/<uuid:author_fqid>/entries/<uuid:entry_fqid>/likes",
        EntryLikesAPIView.as_view(),
        name="author_entry_likes",
    ),
    path(
        "api/authors/<uuid:author_fqid>/entries/<uuid:entry_fqid>/comments/<uuid:comment_id>/likes",
        CommentLikesAPIView.as_view(),
        name="author_entry_comment_likes",
    ),
    re_path(
        rf"^api/authors/(?P<author_fqid>{_UUID})/entries/(?P<entry_fqid>{_UUID})/comments/(?P<comment_ref>.+)/likes$",
        CommentLikesAPIView.as_view(),
        name="author_entry_comment_likes_by_fqid",
    ),
    re_path(
        rf"^api/authors/(?P<author_fqid>{_UUID})/entries/(?P<entry_fqid>{_UUID})/comments/(?P<comment_ref>.+)$",
        EntryCommentDetailAPIView.as_view(),
        name="author_entry_comment_detail",
    ),
    path(
        "api/authors/<uuid:author_fqid>/commented",
        AuthorCommentedAPIView.as_view(),
        name="author_commented",
    ),
    path(
        "api/authors/<uuid:author_fqid>/commented/<uuid:comment_id>",
        AuthorCommentDetailAPIView.as_view(),
        name="author_commented_detail",
    ),
    path(
        "api/authors/<uuid:author_fqid>/liked",
        AuthorLikedAPIView.as_view(),
        name="author_liked",
    ),
    path(
        "api/authors/<uuid:author_fqid>/liked/<uuid:like_id>",
        AuthorLikeDetailAPIView.as_view(),
        name="author_liked_detail",
    ),
    re_path(
        r"^api/authors/(?P<author_encoded_fqid>.+)/commented$",
        AuthorCommentedByFQIDAPIView.as_view(),
        name="author_commented_by_fqid",
    ),
    re_path(
        r"^api/authors/(?P<author_encoded_fqid>.+)/liked$",
        AuthorLikedByFQIDAPIView.as_view(),
        name="author_liked_by_fqid",
    ),
    re_path(
        r"^api/commented/(?P<comment_fqid>.+)$",
        CommentByFQIDAPIView.as_view(),
        name="comment_by_fqid",
    ),
    re_path(
        r"^api/liked/(?P<like_fqid>.+)$",
        LikeByFQIDAPIView.as_view(),
        name="like_by_fqid",
    ),

    # Following / Followers – detail with percent-encoded FQID
    re_path(
        rf"^api/authors/(?P<author_fqid>{_UUID})/following/(?P<foreign_fqid>.+)$",
        views.FollowingDetailAPIView.as_view(),
        name="following_detail",
    ),
    re_path(
        rf"^api/authors/(?P<author_fqid>{_UUID})/followers/(?P<foreign_fqid>.+)$",
        views.FollowerDetailAPIView.as_view(),
        name="follower_detail",
    ),

    # Following / Followers – list endpoints (no trailing FQID)
    path(
        "api/authors/<uuid:author_fqid>/following",
        views.FollowingListAPIView.as_view(),
        name="following_list",
    ),
    path(
        "api/authors/<uuid:author_fqid>/followers",
        views.FollowerListAPIView.as_view(),
        name="followers_list",
    ),

    # Follow requests & Inbox
    path(
        "api/authors/<uuid:author_fqid>/follow_requests",
        views.FollowRequestsAPIView.as_view(),
        name="follow_requests",
    ),
    path(
        "api/authors/<uuid:author_fqid>/inbox",
        InboxAPIView.as_view(),
        name="author_inbox_no_slash",
    ),
    path(
        "api/authors/<uuid:author_fqid>/inbox/",
        InboxAPIView.as_view(),
        name="author_inbox",
    ),

    # Single author by serial (GET / PUT)
    path(
        "api/authors/<uuid:author_fqid>/",
        views.AuthorDetailAPIView.as_view(),
        name="author_detail_api",
    ),

    # Author by FQID (catch-all – must be last)
    re_path(r"^api/authors/(?P<fqid>.+)$", views.AuthorFQIDAPIView.as_view(),
            name="author_by_fqid"),
]

# Combined – used by the root include in config/urls.py
urlpatterns = browser_urlpatterns + api_urlpatterns
