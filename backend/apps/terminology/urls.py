from django.urls import path

from apps.terminology.api import DiagnosisCodeView

urlpatterns = [
    path("diagnosis-codes/", DiagnosisCodeView.as_view(), name="diagnosis-codes"),
]
