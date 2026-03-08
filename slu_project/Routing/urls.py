from django.urls import path
from . import views

app_name = "Routing"

urlpatterns = [
    path("route-management/", views.route_management, name="route_management"),
    path("api/stations/", views.api_stations, name="api_stations"),
    path("api/optimized-route/", views.api_optimized_route, name="api_optimized_route"),
]
