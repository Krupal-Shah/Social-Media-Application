from django.urls import path, re_path
from . import views

urlpatterns = [
    # Browser routes
    path("stream/", views.stream, name="stream"),
     path("explore/", views.explore, name="explore"),
    path("profile/", views.profile, name="profile"),
    path("profile/follow-requests/", views.follow_requests_page,
         name="follow_requests_page"),

    # API Entry routes
    # TODO: Add just entry + just entry id + pagination.
    path("api/entries/create/", views.create_entry, name="create_entry"),
    path("api/entries/<uuid:entry_id>/edit/",
         views.edit_entry, name="edit_entry"),
    path("api/entries/<uuid:entry_id>/delete/",
         views.delete_entry, name="delete_entry"),
    path("api/entries/<uuid:entry_id>/",
         views.entry_detail, name="entry_detail"),
    path("api/entries/<uuid:entry_id>/comment/",
         views.create_comment, name="create_comment"),
    path("api/entries/<uuid:entry_id>/like/",
         views.like_entry, name="like_entry"),
    path("api/entries/<uuid:entry_id>/unlike/",
         views.unlike_entry, name="unlike_entry"),
    path("api/comments/<uuid:comment_id>/like/",
         views.like_comment, name="like_comment"),
    path("api/comments/<uuid:comment_id>/unlike/",
         views.unlike_comment, name="unlike_comment"),
    path("api/comments/<uuid:comment_id>/delete/",
         views.delete_comment, name="delete_comment"),
    re_path(
        r"^api/entries/(?P<fqid>.+)/comments$",
        views.EntryCommentsByFQIDAPIView.as_view(),
        name="entry_comments_by_fqid",
    ),
    re_path(
        r"^api/entries/(?P<fqid>.+)/likes$",
        views.EntryLikesByFQIDAPIView.as_view(),
        name="entry_likes_by_fqid",
    ),
    re_path(r"^api/entries/(?P<fqid>.+)/image$", views.EntryImageByFQIDAPIView.as_view(),
            name="entry_image_by_fqid"),
    re_path(r"^api/entries/(?P<fqid>.+)$", views.EntryFQIDAPIView.as_view(),
            name="entry_by_fqid"),
]
