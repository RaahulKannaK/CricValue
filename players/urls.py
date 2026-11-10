from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("discover/", views.discover, name="discover"),
    path("markets/", views.markets, name="markets"),
    path("markets/<slug:slug>/", views.market_detail, name="market_detail"),
    path("player/<int:pk>/", views.detail, name="detail"),
    path("<slug:slug>/", views.tab, name="tab"),
]