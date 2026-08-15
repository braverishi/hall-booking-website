from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(
            regex=r'^[\+]?[1-9][\d]{0,15}$',
            message="Enter a valid phone number"
        )]
    )
    
    def __str__(self):
        return f"{self.user.username} - {self.phone}"

class Booking(models.Model):
    # User association (optional for backward compatibility)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Basic booking information
    name = models.CharField(max_length=100)
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(
            regex=r'^[\+]?[1-9][\d]{0,15}$',
            message="Enter a valid phone number"
        )]
    )
    description = models.TextField(max_length=500)
    
    # Unified datetime field
    booking_datetime = models.DateTimeField()
    
    # Status tracking
    is_cancelled = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['booking_datetime']
        # Only prevent double-booking for active bookings, not cancelled ones
        constraints = [
            models.UniqueConstraint(
                fields=['booking_datetime'],
                condition=models.Q(is_cancelled=False),
                name='unique_active_booking_datetime'
            )
        ]
        
    def __str__(self):
        status = "Cancelled" if self.is_cancelled else "Active"
        return f"{self.name} - {self.booking_datetime.strftime('%d/%m/%Y %H:%M')} ({status})"
    
    @property
    def is_past(self):
        """Check if booking is in the past"""
        return self.booking_datetime < timezone.now()
    
    @property
    def formatted_datetime(self):
        """Get formatted datetime string"""
        return self.booking_datetime.strftime("%d/%m/%Y %H:%M")
    
    def save(self, *args, **kwargs):
        # Auto-cancel past bookings
        if self.is_past and not self.is_cancelled:
            self.is_cancelled = True
        super().save(*args, **kwargs)