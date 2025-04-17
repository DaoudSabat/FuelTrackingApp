from django.urls import path
from . import views

urlpatterns = [
    path('calculate_trip/', views.calculate_trip_view, name='calculate_trip'),
]