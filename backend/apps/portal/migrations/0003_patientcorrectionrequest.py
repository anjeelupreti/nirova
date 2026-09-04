# Generated for Nirova Phase 9 §94 Patient Portal

import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0001_initial'),
        ('portal', '0002_portalinvitation_failed_attempts'),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientCorrectionRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uuid', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('created_by_id', models.UUIDField(blank=True, null=True)),
                ('field_name', models.CharField(db_index=True, max_length=32)),
                ('old_value', models.CharField(blank=True, max_length=255)),
                ('proposed_value', models.CharField(max_length=255)),
                ('reason', models.CharField(max_length=512)),
                ('status', models.CharField(db_index=True, default='pending', max_length=16)),
                ('requested_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('decided_by_id', models.UUIDField(blank=True, null=True)),
                ('decided_by_name', models.CharField(blank=True, max_length=255)),
                ('decision_notes', models.CharField(blank=True, max_length=512)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='correction_requests', to='portal.portalaccount')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='correction_requests', to='patients.patient')),
            ],
            options={
                'ordering': ['-requested_at'],
                'indexes': [
                    models.Index(fields=['patient', 'status', '-requested_at'], name='portal_pati_patient_77a9c1_idx'),
                    models.Index(fields=['status', '-requested_at'], name='portal_pati_status_94b1c2_idx'),
                ],
            },
        ),
    ]
