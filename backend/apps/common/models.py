"""Base model primitives shared by control-plane and tenant apps."""

import uuid

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Adds creation/modification timestamps to a model."""

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """Public-facing identifier that is safe to expose in URLs and exports.

    Tenant databases are separate, so integer primary keys collide across
    tenants. A UUID keeps identifiers globally unique -- which matters the
    moment data crosses a boundary: platform analytics, exports, FHIR
    resource ids, or a patient record moving between facilities.
    """

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class ActorStampedModel(models.Model):
    """Records which user created and last modified a row.

    Stored as a plain id rather than a foreign key: users live in the control
    plane while most of these rows live in a tenant database, and Django
    cannot enforce a cross-database constraint.
    """

    created_by_id = models.UUIDField(null=True, blank=True, editable=False)
    updated_by_id = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def delete(self):
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Default manager that hides soft-deleted rows.

    Healthcare records are rarely destroyed: clinical, financial and
    inventory history has to stay reconstructable for audit and for the
    version history required by the record-keeping rules. Use
    `all_objects` when you deliberately need the deleted rows too.
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class SoftDeleteModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_by_id = models.UUIDField(null=True, blank=True, editable=False)

    objects = SoftDeleteManager()
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, actor_id=None):
        self.deleted_at = timezone.now()
        self.deleted_by_id = actor_id
        self.save(using=using, update_fields=["deleted_at", "deleted_by_id"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.deleted_by_id = None
        self.save(update_fields=["deleted_at", "deleted_by_id"])


class BaseModel(UUIDModel, TimeStampedModel, ActorStampedModel, SoftDeleteModel):
    """The standard base for domain entities in this project."""

    class Meta:
        abstract = True
