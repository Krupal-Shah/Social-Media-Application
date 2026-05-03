"""URL routing for the nodes app."""

from django.urls import path
from . import views

urlpatterns = [
    path("", views.nodes_list, name="nodes_list"),
    path("add/", views.nodes_add, name="nodes_add"),
    path("<int:node_id>/toggle/", views.nodes_toggle, name="nodes_toggle"),
    path("<int:node_id>/delete/", views.nodes_delete, name="nodes_delete"),
]
