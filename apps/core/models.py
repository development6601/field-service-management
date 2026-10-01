import uuid
from django.db import models
from django.utils import timezone
from .managers import SoftDeletableManager


class UUIDModel(models.Model):
    """
    An abstract base class that provides a UUIDv4 primary key.
    Prevents sequential ID guessing attacks across multi-tenant or public endpoints.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier (UUIDv4)",
    )

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """
    An abstract base class model that provides self-updating
    ``created_at`` and ``updated_at`` fields.
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when the record was created",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the record was last modified",
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class SoftDeletableModel(models.Model):
    """
    An abstract base class model that supports soft-deletion.
    Records are flagged as deleted rather than physically dropped.
    """

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Flag indicating whether this record is soft-deleted",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when this record was soft-deleted",
    )

    objects = SoftDeletableManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """Soft-delete the instance."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        """Permanently remove from the database."""
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        """Restore a soft-deleted instance."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


class BaseModel(UUIDModel, TimeStampedModel, SoftDeletableModel):
    """
    Enterprise standard base model combining UUIDv4, timestamps,
    and soft-deletion capabilities.
    """

    class Meta:
        abstract = True
        ordering = ["-created_at"]
