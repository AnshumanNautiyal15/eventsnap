from django.db import migrations


def encrypt_existing(apps, schema_editor):
    from gallery.crypto import encrypt
    GoogleAccount = apps.get_model("gallery", "GoogleAccount")
    for account in GoogleAccount.objects.all():
        account.refresh_token = encrypt(account.refresh_token)
        account.save(update_fields=["refresh_token"])


class Migration(migrations.Migration):
    dependencies = [("gallery", "0006_index_on_request")]
    operations = [migrations.RunPython(encrypt_existing, migrations.RunPython.noop)]
