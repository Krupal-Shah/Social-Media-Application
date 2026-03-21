"""
URL configuration for transparent project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from authors import views as author_views

urlpatterns = [
    path("", RedirectView.as_view(url="/stream/", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/login/", author_views.login_view, name="login"),
    path("accounts/register/", author_views.register, name="register"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("authors.urls")),
    path("", include("entries.urls")),
]
