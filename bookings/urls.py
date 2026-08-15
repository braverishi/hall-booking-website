from django.urls import path
from .views import (
    bookings, 
    booking_ui, 
    ai_booking_view, 
    ai_cancel_view,
    view_bookings,
    edit_booking,
    signup_view,
    login_view,
    logout_view
)

urlpatterns = [
    # Authentication Routes
    path('signup/', signup_view, name='signup'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    
    # UI Routes
    path('', booking_ui, name='booking_ui'),
    
    # Booking Operations
    path('bookings/', bookings, name='bookings'),
    path('bookings/view/', view_bookings, name='view_bookings'),
    path('bookings/edit/', edit_booking, name='edit_booking'),
    
    # AI-Powered Routes
    path('ai-booking/', ai_booking_view, name='ai_booking_view'),
    path('ai-cancel/', ai_cancel_view, name='ai_cancel_view'),
]

