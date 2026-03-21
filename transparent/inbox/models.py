from django.db import models
from django.conf import settings


class InboxItem(models.Model):
    author = models.ForeignKey("authors.Author", on_delete=models.CASCADE)

    type = models.CharField(max_length=20)
    payload = models.JSONField()

    received = models.DateTimeField(auto_now_add=True)
