from django.urls import path
from .views import device_dashboard

app_name = "demo"

urlpatterns = [
    path("", device_dashboard, name="dashboard"),
    path("device/<str:device_id>/", device_dashboard, name="device_dashboard"),
]
