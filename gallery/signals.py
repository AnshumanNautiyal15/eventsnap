from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from . import storage
from .models import Event


@receiver(post_delete, sender=Event)
def delete_event_files(sender, instance, **kwargs):
    """However an event is deleted (app, admin, deleting the photographer), remove its stored files too.

    All of an event's uploads and previews live under events/<slug>/, so one folder delete covers them.
    """
    prefix = f"events/{instance.slug}/"
    transaction.on_commit(lambda: storage.delete_prefix_in_background(prefix))
