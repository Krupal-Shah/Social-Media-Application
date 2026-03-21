from django.db import models


class Node(models.Model):
    base_url = models.URLField(unique=True)

    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)

    active = models.BooleanField(default=True)
