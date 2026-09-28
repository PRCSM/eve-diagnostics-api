import uuid

from django.db import models


class BaseModel(models.Model):
    """UUID primary key plus audit timestamps, shared by every domain table."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
