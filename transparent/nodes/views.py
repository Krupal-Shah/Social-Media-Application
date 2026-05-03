"""View logic for the nodes app."""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import Node
from .remote import sync_remote_authors_for_node
from .models import RemoteAuthor
from inbox.models import InboxItem


def _normalize_api_base(raw_base):
    """Execute normalize api base."""
    base = (raw_base or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api"):
        return base
    return f"{base}/api"


def _node_scope_variants(node):
    """Execute node scope variants."""
    return node.scope_variants


def _payload_source_fqid(item):
    """Execute payload source fqid."""
    payload = item.payload or {}
    item_type = str(item.type or "").lower().strip()

    if item_type == "follow":
        actor = payload.get("actor", {}) if isinstance(payload, dict) else {}
        return str(actor.get("id", "")).strip()

    if item_type in {"entry", "comment", "like"}:
        author = payload.get("author", {}) if isinstance(payload, dict) else {}
        return str(author.get("id", "")).strip()

    return ""


@staff_member_required
def nodes_list(request):
    """Display all remote nodes and the form to add a new one."""
    nodes = Node.objects.exclude(base_url__isnull=True).exclude(base_url="").order_by("base_url")
    return render(request, "nodes.html", {"nodes": nodes, "active_nav": "nodes"})


@staff_member_required
@require_POST
def nodes_add(request):
    """Add a new remote node."""
    base_url = request.POST.get("base_url", "").strip()
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "").strip()

    if not base_url or not username or not password:
        nodes = Node.objects.all().order_by("base_url")
        return render(request, "nodes.html", {
            "nodes": nodes,
            "add_error": "All fields are required.",
            "active_nav": "",
        })

    normalized_base_url = _normalize_api_base(base_url)
    node, created = Node.objects.update_or_create(
        base_url=normalized_base_url,
        defaults={"username": username, "password": password, "active": True},
    )
    result = sync_remote_authors_for_node(node)
    if result["ok"]:
        messages.success(
            request,
            f"Connected {node.base_url} and discovered {result['upserted']} remote author(s).",
        )
    else:
        messages.error(
            request,
            f"Saved {node.base_url}, but author sync failed: {result['error']}",
        )

    return redirect("nodes_list")


@staff_member_required
@require_POST
def nodes_toggle(request, node_id):
    """Toggle a node's active status."""
    node = get_object_or_404(Node, pk=node_id)
    node.active = not node.active
    node.save()
    messages.info(
        request,
        f"{'Enabled' if node.active else 'Disabled'} remote node {node.base_url}.",
    )
    return redirect("nodes_list")


@staff_member_required
@require_POST
def nodes_delete(request, node_id):
    """Remove a remote node."""
    node = get_object_or_404(Node, pk=node_id)
    RemoteAuthor.objects.filter(node=node).delete()

    scopes = _node_scope_variants(node)
    if scopes:
        to_delete_ids = []
        for item in InboxItem.objects.all().only("id", "type", "payload"):
            source_fqid = _payload_source_fqid(item)
            if source_fqid and any(source_fqid.startswith(scope) for scope in scopes):
                to_delete_ids.append(item.id)
        if to_delete_ids:
            InboxItem.objects.filter(id__in=to_delete_ids).delete()

    node.delete()
    messages.info(request, "Removed remote node and cleared its cached federation data.")
    return redirect("nodes_list")
