import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser


class Author(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    host = models.URLField()
    fqid = models.URLField(unique=True)

    display_name = models.CharField(max_length=255)
    github = models.URLField(blank=True)
    profile_image = models.URLField(blank=True)

    approved = models.BooleanField(default=False)
    
    # get the description (can be blank).
    description = models.TextField(blank=True, default="")


    def save(self, *args, **kwargs):
        if not self.host:
            self.host = settings.SERVICE_URL
        if not self.fqid:
            self.fqid = f"{self.host}authors/{self.id}"
        super().save(*args, **kwargs)
        
    @property 
    def web(self): 
        """this generates the HTML frontend URL for the author profile""" 
        base_host = self.host.replace('/api/', '/') 
        return f"{base_host}authors/{self.id}"     
