from django.urls import path

from apps.workspace.api import MyWorkspaceView

urlpatterns = [
    path("workspace/", MyWorkspaceView.as_view(), name="my-workspace"),
]
