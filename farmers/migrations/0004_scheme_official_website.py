# Generated migration for official_website field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farmers', '0003_alter_applicationrequest_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheme',
            name='official_website',
            field=models.URLField(blank=True, null=True),
        ),
    ]
