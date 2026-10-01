from django.db import models
from django.utils import timezone


class SoftDeletableQuerySet(models.QuerySet):
    """Custom queryset that supports soft-deletion and custom filtering."""

    def delete(self):
        """Soft-delete all records in this queryset."""
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        """Permanently delete records from the database."""
        return super().delete()

    def alive(self):
        """Return only active (non-deleted) records."""
        return self.filter(is_deleted=False)

    def dead(self):
        """Return only soft-deleted records."""
        return self.filter(is_deleted=True)


class SoftDeletableManager(models.Manager):
    """Manager that excludes soft-deleted records by default."""

    def get_queryset(self):
        return SoftDeletableQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def all_with_deleted(self):
        """Returns all records including soft-deleted ones."""
        return SoftDeletableQuerySet(self.model, using=self._db)

    def deleted_only(self):
        """Returns only soft-deleted records."""
        return SoftDeletableQuerySet(self.model, using=self._db).filter(is_deleted=True)
