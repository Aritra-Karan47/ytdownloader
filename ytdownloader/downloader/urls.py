from django.urls import path
from . import views
import include , path 

urlpatterns = [
    path('', views.home, name='home'),
    path('download/video/<str:video_id>/', views.download_video, name='download_video'),
    path('download/thumbnail/<str:video_id>/', views.download_thumbnail, name='download_thumbnail'),
    path('download/playlist/', views.download_playlist, name='download_playlist'),
]