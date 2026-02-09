from django.urls import path
from .views import device_dashboard

urlpatterns = [
    path("device/<str:device_id>/", device_dashboard, name="device_dashboard"),
]
