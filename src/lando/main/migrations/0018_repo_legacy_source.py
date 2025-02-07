# Generated by Django 5.1.5 on 2025-02-04 15:38

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0017_alter_repo_default_branch"),
    ]

    operations = [
        migrations.AddField(
            model_name="repo",
            name="legacy_source",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="new_target",
                to="main.repo",
            ),
        ),
    ]
