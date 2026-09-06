from django.urls import path

from apps.search.api import GlobalSearchView, SearchSourcesView

urlpatterns = [
    path("", GlobalSearchView.as_view(), name="global-search"),
    path("sources/", SearchSourcesView.as_view(), name="search-sources"),
]
