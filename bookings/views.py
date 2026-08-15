from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from django.utils import timezone
from .models import Booking, UserProfile
from .forms import SignUpForm, LoginForm
import json
import anthropic
import os
import re
from django.db.models import Q
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages

DEFAULT_NAME = "Rishi"
DEFAULT_PHONE = "7305445110"
DEFAULT_DESCRIPTION = "general booking"

def get_user_defaults(request):
    """Get default values based on logged-in user or fallback to defaults"""
    if request.user.is_authenticated:
        try:
            user_profile = UserProfile.objects.get(user=request.user)
            name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
            phone = user_profile.phone
        except UserProfile.DoesNotExist:
            name = request.user.username
            phone = DEFAULT_PHONE
    else:
        name = DEFAULT_NAME
        phone = DEFAULT_PHONE
    return name, phone

def get_available_slots(date, exclude_booking_id=None):
    """Get available time slots for a specific date"""
    # Get all booked times on that date (excluding cancelled bookings)
    booked_times_query = Booking.objects.filter(
        booking_datetime__date=date,
        is_cancelled=False
    )
    
    # Exclude a specific booking if provided (for modifications)
    if exclude_booking_id:
        booked_times_query = booked_times_query.exclude(id=exclude_booking_id)
    
    booked_times = booked_times_query.values_list('booking_datetime__time', flat=True)
    
    # Generate available time slots (9 AM to 8 PM, every 30 minutes)
    available_slots = []
    current_datetime = timezone.now()
    
    for hour in range(9, 21):  # 9 AM to 8 PM
        for minute in [0, 30]:  # Every 30 minutes
            slot_datetime = timezone.make_aware(
                datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute))
            )
            # Check if slot is not booked AND is in the future
            if slot_datetime.time() not in booked_times and slot_datetime > current_datetime:
                available_slots.append({
                    'time': f"{hour:02d}:{minute:02d}",
                    'datetime': slot_datetime.strftime('%d/%m/%Y %H:%M')
                })
    
    return available_slots




# Claude client setup with environment variable
client = anthropic.Anthropic(api_key='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')
def validate_phone(phone):
    """Validate phone number format"""
    pattern = r'^[\+]?[1-9][\d]{0,15}$'
    return re.match(pattern, phone.replace(' ', '').replace('-', ''))

def validate_future_datetime(dt):
    """Ensure booking is for future date/time"""
    current_time = timezone.now()
    
    # For debugging - you can remove these print statements later
    # print(f"Current time: {current_time}")
    # print(f"Booking time: {dt}")
    # print(f"Is future: {dt > current_time}")
    
    return dt > current_time

def process_multiple_bookings(request, bookings_data, is_modification):
    """Process multiple bookings from a single request"""
    if is_modification:
        return JsonResponse({"status": "error", "message": "❌ Modification of multiple bookings is not supported. Please modify one booking at a time."})
    
    created_bookings = []
    failed_bookings = []
    
    for i, booking_data in enumerate(bookings_data):
        try:
            # Parse datetime
            booking_datetime = timezone.make_aware(
                datetime.strptime(f"{booking_data['date']} {booking_data['time']}", "%Y-%m-%d %H:%M")
            )

            # Validate future datetime
            if not validate_future_datetime(booking_datetime):
                failed_bookings.append(f"Booking {i+1}: Must be for a future date and time")
                continue

            # Check for conflicts
            if Booking.objects.filter(
                booking_datetime__date=booking_datetime.date(),
                booking_datetime__time=booking_datetime.time(),
                is_cancelled=False
            ).exists():
                failed_bookings.append(f"Booking {i+1}: Time slot {booking_data['date']} {booking_data['time']} already taken")
                continue

            # Create booking
            booking_obj_data = {
                "name": booking_data["name"],
                "phone": booking_data["phone"],
                "description": booking_data["description"],
                "booking_datetime": booking_datetime
            }
            
            # Link to user if authenticated
            if request.user.is_authenticated:
                booking_obj_data["user"] = request.user
                
            booking = Booking.objects.create(**booking_obj_data)
            created_bookings.append({
                "id": booking.id,
                "date": booking_data["date"],
                "time": booking_data["time"],
                "description": booking_data["description"]
            })
            
        except Exception as e:
            failed_bookings.append(f"Booking {i+1}: {str(e)}")
    
    # Prepare response
    if created_bookings and not failed_bookings:
        return JsonResponse({
            "status": "success",
            "message": f"🎉 Successfully created {len(created_bookings)} bookings!",
            "bookings": created_bookings
        })
    elif created_bookings and failed_bookings:
        return JsonResponse({
            "status": "partial_success",
            "message": f"✅ Created {len(created_bookings)} bookings, but {len(failed_bookings)} failed.",
            "created_bookings": created_bookings,
            "failed_bookings": failed_bookings
        })
    else:
        return JsonResponse({
            "status": "error",
            "message": "❌ All bookings failed to create.",
            "failed_bookings": failed_bookings
        })



@login_required
def booking_ui(request):
    return render(request, "finalbooking.html")

@csrf_exempt
@login_required
def bookings(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            name = data.get("name", "").strip()
            phone = data.get("phone", "").strip()
            description = data.get("description", "").strip()
            datetime_str = data.get("datetime", "").strip()

            # Validate required fields
            if not all([name, phone, description, datetime_str]):
                return JsonResponse({"error": "❌ Missing required fields."}, status=400)

            # Validate phone number
            if not validate_phone(phone):
                return JsonResponse({"error": "❌ Invalid phone number format."}, status=400)

            # Parse date and time from 'DD/MM/YYYY HH:MM'
            try:
                booking_datetime = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M")
                booking_datetime = timezone.make_aware(booking_datetime)
            except ValueError:
                return JsonResponse({"error": "⚠️ Date and time must be in DD/MM/YYYY HH:MM format."}, status=400)

            # Validate future datetime
            if not validate_future_datetime(booking_datetime):
                current_time = timezone.now()
                if booking_datetime.date() == current_time.date():
                    return JsonResponse({"error": f"❌ Cannot book past times. It's currently {current_time.strftime('%H:%M')}, please choose a time after {current_time.strftime('%H:%M')}."}, status=400)
                else:
                    return JsonResponse({"error": "❌ Cannot book dates in the past."}, status=400)

            # Check for conflicts
            if Booking.objects.filter(
                booking_datetime__date=booking_datetime.date(),
                booking_datetime__time=booking_datetime.time(),
                is_cancelled=False
            ).exists():
                return JsonResponse({"error": "❌ Time slot already booked."}, status=400)

            # Save booking
            booking_data = {
                "name": name,
                "phone": phone,
                "description": description,
                "booking_datetime": booking_datetime
            }
            
            # Link to user if authenticated
            if request.user.is_authenticated:
                booking_data["user"] = request.user
                
            Booking.objects.create(**booking_data)

            return JsonResponse({"message": "✅ Booking successful!"})
        
        except Exception as e:
            return JsonResponse({"error": f"❌ Server error: {str(e)}"}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)

@csrf_exempt
def view_bookings(request):
    """View all bookings with pagination and filtering"""
    if request.method == "GET":
        try:
            # Get query parameters
            page = request.GET.get('page', 1)
            date_filter = request.GET.get('date')
            search = request.GET.get('search', '')
            show_cancelled = request.GET.get('show_cancelled', 'false').lower() == 'true'
            
            # Build query - filter by logged-in user
            if request.user.is_authenticated:
                # Filter by user or by phone number (for backward compatibility)
                user_name, user_phone = get_user_defaults(request)
                bookings_query = Booking.objects.filter(
                    Q(user=request.user) | Q(phone=user_phone)
                )
            else:
                bookings_query = Booking.objects.none()
            
            if not show_cancelled:
                bookings_query = bookings_query.filter(is_cancelled=False)
            
            if date_filter:
                try:
                    filter_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
                    bookings_query = bookings_query.filter(booking_datetime__date=filter_date)
                except ValueError:
                    pass
            
            if search:
                bookings_query = bookings_query.filter(
                    Q(name__icontains=search) | 
                    Q(description__icontains=search) |
                    Q(phone__icontains=search)
                )
            
            # Order by booking datetime
            bookings_query = bookings_query.order_by('booking_datetime')
            
            # Paginate
            paginator = Paginator(bookings_query, 10)
            bookings_page = paginator.get_page(page)
            
            # Format response
            bookings_data = []
            for booking in bookings_page:
                bookings_data.append({
                    'id': booking.id,
                    'name': booking.name,
                    'phone': booking.phone,
                    'description': booking.description,
                    'datetime': booking.booking_datetime.strftime("%d/%m/%Y %H:%M"),
                    'is_cancelled': booking.is_cancelled,
                    'created_at': booking.created_at.strftime("%d/%m/%Y %H:%M") if hasattr(booking, 'created_at') else None
                })
            
            return JsonResponse({
                'bookings': bookings_data,
                'has_next': bookings_page.has_next(),
                'has_previous': bookings_page.has_previous(),
                'current_page': bookings_page.number,
                'total_pages': paginator.num_pages,
                'total_count': paginator.count
            })
            
        except Exception as e:
            return JsonResponse({"error": f"❌ Error fetching bookings: {str(e)}"}, status=500)
    
    return JsonResponse({"error": "Only GET method allowed"}, status=405)

@csrf_exempt
@login_required
def ai_booking_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            query = data.get("query", "").strip().lower()

            if not query:
                return JsonResponse({"status": "error", "message": "❌ Query cannot be empty"})

            # ✅ Check for modification intent FIRST (before view keywords)
            modification_keywords = [
                # Original keywords
                "modify", "reschedule", "change", "shift", "move", "update", 
                "different time", "new time", "another day", "different day",
                "postpone", "advance", "earlier", "later", "switch",
                
                # More natural phrases
                "can i change", "i want to change", "need to change", "please change",
                "can i move", "i want to move", "need to move", "please move",
                "can i reschedule", "i want to reschedule", "need to reschedule",
                "push back", "bring forward", "delay", "prepone",
                
                # Direct modification phrases
                "modify my booking", "modify booking", "change my booking", "change booking",
                "reschedule my booking", "reschedule booking", "move my booking", "move booking",
                "update my booking", "update booking", "shift my booking", "shift booking",
                
                # Time-based modifications
                "make it earlier", "make it later", "different slot", "new slot",
                "change timing", "change date", "change time", "new date",
                "alter booking", "edit booking", "adjust booking", "revise booking",
                
                # With specific references
                "booking on", "meeting on", "reservation on", "appointment on",
                
                # Duration and specific modifications
                "make sure", "make the", "modify the", "change the", "update the",
                "the meeting", "the booking", "the reservation", "above meeting",
                "that meeting", "this meeting", "that booking", "this booking",
                "for 1 hour", "for 2 hours", "for 1.5 hours", "for 30 mins",
                "duration", "length", "extend", "shorten", "longer", "shorter"
            ]
            is_modification = any(kw in query for kw in modification_keywords)

            # ✅ Check for available slots query first
            availability_keywords = [
                "available slots", "available slot", "free slots", "free slot",
                "show available", "show free", "what's available", "whats available",
                "availability", "available times", "free times", "open slots",
                "available time", "free time", "open time", "vacant slots",
                "empty slots", "show slots", "available bookings", "free bookings",
                "slot availability", "time availability", "what times are available",
                "what slots are available", "show me available", "show me free",
                "list available", "list free", "get available", "get free",
                "check available", "check free", "find available", "find free",
                "available on", "free on", "open on", "vacant on", "empty on",
                "slots for", "times for", "availability for", "available for",
                "what's free", "whats free", "what's open", "whats open",
                "show availability", "display availability", "get availability",
                "check availability", "find availability", "see availability",
                "available dates", "free dates", "open dates", "vacant dates"
            ]
            
            # Check if this is an availability query
            if not is_modification and any(kw in query for kw in availability_keywords):
                # Extract date from query
                date_match = None
                today = timezone.now().date()
                
                # Look for date patterns
                date_patterns = [
                    r'(\d{1,2}/\d{1,2}/\d{4})',  # DD/MM/YYYY
                    r'(\d{1,2}-\d{1,2}-\d{4})',  # DD-MM-YYYY
                    r'(\d{4}-\d{1,2}-\d{1,2})',  # YYYY-MM-DD
                ]
                
                for pattern in date_patterns:
                    match = re.search(pattern, query)
                    if match:
                        date_str = match.group(1)
                        try:
                            if '/' in date_str:
                                date_match = datetime.strptime(date_str, "%d/%m/%Y").date()
                            elif '-' in date_str and len(date_str.split('-')[0]) == 4:
                                date_match = datetime.strptime(date_str, "%Y-%m-%d").date()
                            else:
                                date_match = datetime.strptime(date_str, "%d-%m-%Y").date()
                            break
                        except ValueError:
                            continue
                
                # If no date found, check for relative dates
                if not date_match:
                    query_lower = query.lower()
                    if "tomorrow" in query_lower:
                        date_match = today + timedelta(days=1)
                    elif "today" in query_lower:
                        date_match = today
                    elif "day after tomorrow" in query_lower:
                        date_match = today + timedelta(days=2)
                    else:
                        # Default to today if no date specified
                        date_match = today
                
                # Get available slots for the date
                available_slots = get_available_slots(date_match)
                
                if available_slots:
                    slots_text = "<br>".join([f"• {slot['time']} ({slot['datetime']})" for slot in available_slots])
                    message = f"✅🕐 Available time slots on {date_match.strftime('%d/%m/%Y')}:<br><br>{slots_text}"
                    return JsonResponse({
                        "status": "success",
                        "message": message,
                        "bookings": []
                    })
                else:
                    message = f"❌ No available slots found on {date_match.strftime('%d/%m/%Y')}. All slots are either booked or in the past."
                    return JsonResponse({
                        "status": "error",
                        "message": message
                    })

            # ✅ Handle view requests early (without Claude) - Enhanced pattern matching
            view_keywords = [
                # Original keywords
                "view booking", "view my bookings", "show bookings", "show my bookings",
                "see bookings", "list bookings", "my reservations", "check bookings",
                "what bookings", "booking status", "my appointments", "scheduled",
                "what's booked", "current bookings", "existing bookings",
                "show all books", "show all bookings", "all bookings", "all books",
                "display bookings", "get bookings", "fetch bookings", "retrieve bookings",
                "show my booking", "view my booking", "see my booking", "check my booking",
                "show booking", "my booking", "see booking", "display booking",
                
                # Question-based phrases
                "do i have any bookings", "do i have a booking", "do i have bookings",
                "what are my bookings", "what is my booking", "when is my booking",
                "when are my bookings", "what time is my booking", "what day is my booking",
                
                # Status checks
                "booking details", "reservation details", "my schedule", "hall schedule",
                "upcoming bookings", "future bookings", "active bookings", "my active bookings",
                "booked slots", "reserved slots", "my slots", "my reserved slots",
                
                # Informal phrases
                "whats booked", "wat bookings", "bookings?", "my bookings?",
                "show schedule", "view schedule", "check schedule", "see schedule",
                
                # Commands
                "list all bookings", "list my bookings", "give me my bookings",
                "tell me my bookings", "find my bookings", "search bookings",
                "lookup bookings", "look up bookings",
                
                # Handle common typos
                "view my boookings", "show my boookings", "see my boookings",
                "my boookings", "boookings", "bookng", "bookigns", "bookins",
                "veiw", "veiwing", "shwo", "sho", "bookig", "boking", "bking"
            ]
            
            # Check for view keywords only if NOT a modification request
            if not is_modification and any(kw in query for kw in view_keywords):
                # Check for date filtering in the query
                bookings_filter = {"is_cancelled": False}
                
                # Look for date patterns and relative dates in the query
                start_date = None
                query_lower = query.lower()
                
                # Check for relative date expressions first
                today = timezone.now().date()
                end_date = None
                
                if any(phrase in query_lower for phrase in ["next week", "nxt week", "next wk", "nextweek"]):
                    # Next Monday
                    days_ahead = 7 - today.weekday()  # weekday() returns 0 for Monday
                    if days_ahead <= 0:  # Already Monday or past, go to next Monday
                        days_ahead += 7
                    start_date = today + timedelta(days=days_ahead)
                    bookings_filter["booking_datetime__date__gte"] = start_date
                    
                    # If "for next week" (not "from"), limit to that week only
                    if any(phrase in query_lower for phrase in ["for next week", "for nxt week", "for next wk"]):
                        end_date = start_date + timedelta(days=6)  # Sunday of next week
                        bookings_filter["booking_datetime__date__lte"] = end_date
                elif "this week" in query_lower or "from this week" in query_lower:
                    # This Monday
                    start_date = today - timedelta(days=today.weekday())
                    bookings_filter["booking_datetime__date__gte"] = start_date
                elif any(word in query_lower for word in ["tomorrow", "tommorow", "tomorow", "tommarow", "from tomorrow", "from tommorow"]):
                    start_date = today + timedelta(days=1)
                    bookings_filter["booking_datetime__date__gte"] = start_date
                elif "today" in query_lower or "from today" in query_lower:
                    start_date = today
                    bookings_filter["booking_datetime__date__gte"] = start_date
                elif "next month" in query_lower or "from next month" in query_lower:
                    # First day of next month
                    if today.month == 12:
                        start_date = today.replace(year=today.year + 1, month=1, day=1)
                    else:
                        start_date = today.replace(month=today.month + 1, day=1)
                    bookings_filter["booking_datetime__date__gte"] = start_date
                else:
                    # Look for specific date patterns
                    date_patterns = [
                        r"from\s+(\d{1,2}/\d{1,2}/\d{4})",  # "from 01/01/2025"
                        r"after\s+(\d{1,2}/\d{1,2}/\d{4})",  # "after 01/01/2025"
                        r"since\s+(\d{1,2}/\d{1,2}/\d{4})",  # "since 01/01/2025"
                        r"(\d{1,2}/\d{1,2}/\d{4})",  # just "01/01/2025"
                    ]
                    
                    for pattern in date_patterns:
                        match = re.search(pattern, query_lower)
                        if match:
                            try:
                                date_str = match.group(1)
                                start_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                                bookings_filter["booking_datetime__date__gte"] = start_date
                                break
                            except ValueError:
                                continue
                
                # Filter by logged-in user
                user_name, user_phone = get_user_defaults(request)
                bookings = Booking.objects.filter(
                    Q(user=request.user) | Q(phone=user_phone),
                    **bookings_filter
                ).order_by("booking_datetime")
                booking_list = [
                    {
                        "id": b.id,
                        "name": b.name,
                        "phone": b.phone,
                        "description": b.description,
                        "datetime": b.booking_datetime.strftime("%d/%m/%Y %H:%M"),
                    }
                    for b in bookings
                ]
                if booking_list:
                    if start_date and end_date:
                        message = f"✅📋 Found {len(booking_list)} active booking(s) from {start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}"
                    elif start_date:
                        # Check if this was a relative date request
                        if any(phrase in query_lower for phrase in ["next week", "nxt week", "next wk", "nextweek"]):
                            message = f"✅📋 Found {len(booking_list)} active booking(s) for next week (from {start_date.strftime('%d/%m/%Y')})"
                        elif "this week" in query_lower:
                            message = f"✅📋 Found {len(booking_list)} active booking(s) for this week (from {start_date.strftime('%d/%m/%Y')})"
                        elif any(word in query_lower for word in ["tomorrow", "tommorow", "tomorow", "tommarow"]):
                            message = f"✅📋 Found {len(booking_list)} active booking(s) for tomorrow ({start_date.strftime('%d/%m/%Y')})"
                        elif "today" in query_lower:
                            message = f"✅📋 Found {len(booking_list)} active booking(s) for today ({start_date.strftime('%d/%m/%Y')})"
                        else:
                            message = f"✅📋 Found {len(booking_list)} active booking(s) from {start_date.strftime('%d/%m/%Y')} onwards"
                    else:
                        message = f"✅📋 Found {len(booking_list)} active booking(s)"
                    return JsonResponse({
                        "status": "success",
                        "message": message,
                        "bookings": booking_list
                    })
                else:
                    if start_date and end_date:
                        message = f"📋 No active bookings found from {start_date.strftime('%d/%m/%Y')} to {end_date.strftime('%d/%m/%Y')}. Would you like to create a new booking?"
                    elif start_date:
                        if any(phrase in query_lower for phrase in ["next week", "nxt week", "next wk", "nextweek"]):
                            message = f"📋 No active bookings found for next week. Would you like to create a new booking?"
                        elif "this week" in query_lower:
                            message = f"📋 No active bookings found for this week. Would you like to create a new booking?"
                        else:
                            message = f"📋 No active bookings found from {start_date.strftime('%d/%m/%Y')} onwards. Would you like to create a new booking?"
                    else:
                        message = "📋 No active bookings found. Would you like to create a new booking?"
                    return JsonResponse({
                        "status": "success",
                        "message": message,
                        "bookings": []
                    })

            # Handle duration-related modification requests directly
            if is_modification and any(word in query.lower() for word in ["duration", "hours", "hour", "mins", "minutes", "1.5", "2.5", "30 mins"]):
                return JsonResponse({
                    "status": "error", 
                    "message": "⏰ I understand you want to modify the duration, but our booking system works with specific time slots rather than durations. You can reschedule to a different time by saying something like 'change my booking to 3pm tomorrow' or 'move my meeting to next Friday at 2pm'."
                })

            # 🧠 Ask Claude for booking intent with enhanced understanding
            prompt = (
                "You are an advanced AI hall booking assistant with sophisticated natural language understanding.\n"
                "Extract booking information from complex, conversational requests with high accuracy.\n\n"
                "CONTEXT:\n"
                f"- Today's date: {timezone.now().strftime('%A, %B %d, %Y (%Y-%m-%d)')}\n"
                f"- Current time: {timezone.now().strftime('%H:%M')}\n"
                f"- Day of week: {timezone.now().strftime('%A')}\n\n"
                "UNDERSTAND COMPLEX TIME EXPRESSIONS:\n"
                "- Relative times: 'in 2 hours', 'after lunch' (13:00), 'before dinner' (17:00)\n"
                "- Time ranges: 'late morning' (10:00-11:00), 'early evening' (17:00-18:00)\n"
                "- Business terms: 'COB/EOD' (17:00), 'start of business' (09:00)\n"
                "- Contextual: 'after work' (18:00), 'lunch time' (12:00-13:00)\n"
                "- Specific times: 'half past 3' (15:30), 'quarter to 5' (16:45), '3:15' (15:15)\n"
                "- Same time: 'same time', 'keep time', 'keep the time' = preserve original time\n\n"
                "UNDERSTAND COMPLEX DATE EXPRESSIONS:\n"
                "- Relative dates: 'day after tomorrow', 'next Monday', 'this coming Friday'\n"
                "- Week references: 'end of next week', 'middle of this week', 'early next month'\n"
                "- Specific dates: '15th of next month', 'last Friday of January'\n"
                "- Holidays/Events: 'next weekend', 'this Saturday', 'coming Sunday'\n"
                "- Multiple dates: 'every Friday', 'all weekends' (handle as single booking for now)\n\n"
                "UNDERSTAND EVENT CONTEXTS:\n"
                "- Business: 'team meeting', 'client presentation', 'board meeting', 'workshop', 'training session'\n"
                "- Social: 'birthday celebration', 'anniversary party', 'reunion', 'get-together'\n"
                "- Cultural: 'wedding reception', 'engagement ceremony', 'religious gathering'\n"
                "- Educational: 'seminar', 'lecture', 'study group', 'coaching class'\n\n"
                "HANDLE COMPLEX REQUESTS:\n"
                "- Conditional: 'if available', 'preferably', 'or else'\n"
                "- Preferences: 'around 3pm', 'sometime in the evening', 'flexible timing'\n"
                "- Multiple info: 'book for John's birthday next Friday evening around 7'\n"
                "- Questions: 'can I book', 'is it possible', 'would like to reserve'\n"
                "- Follow-up responses: 'yes' (alone) = query intent, 'yes' with context = continue previous request\n\n"
                "SPECIAL INSTRUCTIONS:\n"
                "- For ambiguous times (e.g., 'around 3'), use the exact hour mentioned\n"
                "- For date ranges or recurring requests, extract only the first date\n"
                "- Infer reasonable defaults based on event type (parties→evening, meetings→morning/afternoon)\n"
                "- For modification requests, extract the booking details being modified\n"
                "- When no date specified in modification, return intent='modification' with null date\n"
                "- Modification examples: 'modify my booking on 8/07/2025 to 7pm', 'change booking tomorrow to 3pm'\n"
                "- No date examples: 'modify my booking to 3pm' → intent='modification', date=null\n\n"
                "EXTRACT AND RETURN A JSON OBJECT with these keys: bookings, intent, confidence\n"
                "- bookings: array of booking objects (usually just one, but can be multiple)\n"
                "  Each booking object should have: {name, phone, date, time, description}\n"
                "  - name: string or null\n"
                "  - phone: string or null\n"
                "  - date: YYYY-MM-DD format or null\n"
                "  - time: HH:MM (24-hour) or null\n"
                "  - description: detailed event description\n"
                "- intent: 'booking', 'modification', 'cancellation', 'query'\n"
                "- confidence: float 0-1 (how confident about the extraction)\n\n"
                "EXAMPLES:\n"
                "'I need to book the hall for our annual team meeting next Tuesday afternoon' → \n"
                "{\"bookings\": [{\"name\": null, \"phone\": null, \"date\": \"2025-01-14\", \"time\": \"14:00\", \"description\": \"annual team meeting\"}], \"intent\": \"booking\", \"confidence\": 0.9}\n\n"
                "'Can we get the venue this weekend for my daughter's birthday, preferably Saturday evening around 6 or 7?' → \n"
                "{\"bookings\": [{\"name\": null, \"phone\": null, \"date\": \"2025-01-11\", \"time\": \"18:00\", \"description\": \"daughter's birthday party\"}], \"intent\": \"booking\", \"confidence\": 0.85}\n\n"
                "'Book hall tomorrow at 2pm for meeting and Friday evening for party' → \n"
                "{\"bookings\": [{\"name\": null, \"phone\": null, \"date\": \"2025-01-08\", \"time\": \"14:00\", \"description\": \"meeting\"}, {\"name\": null, \"phone\": null, \"date\": \"2025-01-10\", \"time\": \"18:00\", \"description\": \"party\"}], \"intent\": \"booking\", \"confidence\": 0.9}\n\n"
                "'Modify my booking on 8/07/2025 to 7:00pm' → \n"
                "{\"bookings\": [{\"name\": null, \"phone\": null, \"date\": \"2025-07-08\", \"time\": \"19:00\", \"description\": null}], \"intent\": \"modification\", \"confidence\": 0.95}\n\n"
                "'Modify my booking on 08/07/2025 to 9/07/2025 same time' → \n"
                "{\"bookings\": [{\"name\": null, \"phone\": null, \"date\": \"2025-07-09\", \"time\": \"same\", \"description\": null}], \"intent\": \"modification\", \"confidence\": 0.9}\n\n"
                "**Output ONLY the JSON object.**\n\n"
                f"User Request: \"{query}\""
            )

            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    temperature=0.2,
                    messages=[{"role": "user", "content": prompt}]
                )
                ai_response = response.content[0].text.strip()
            except anthropic.APIError:
                return JsonResponse({"status": "error", "message": "❌ I'm having trouble processing your request right now. Please try again in a moment."})

            # Extract JSON from Claude response with better error handling
            try:
                match = re.search(r'\{.*\}', ai_response, re.DOTALL)
                if not match:
                    return JsonResponse({"status": "error", "message": "❌ I had trouble understanding your request. Please try rephrasing it (e.g., 'book hall tomorrow at 3pm for birthday party')."})
                ai_data = json.loads(match.group())
            except json.JSONDecodeError:
                return JsonResponse({"status": "error", "message": "❌ I couldn't process your request. Please try again with clear booking details."})
            
            # Check intent and confidence
            intent = ai_data.get("intent", "booking")
            confidence = ai_data.get("confidence", 0.5)
            
            # Handle different intents
            if intent == "query":
                return JsonResponse({"status": "info", "message": "ℹ️ For queries about bookings, please use 'show my bookings' or similar commands. To make a booking, please specify the date and time."})
            elif intent == "cancellation":
                return JsonResponse({"status": "info", "message": "ℹ️ To cancel a booking, please use commands like 'cancel my booking tomorrow' or 'cancel my last booking'."})
            elif intent == "modification":
                # Handle modification intent specially - even if is_modification wasn't triggered
                is_modification = True
            
            # Low confidence handling
            if confidence < 0.7:
                return JsonResponse({
                    "status": "error", 
                    "message": f"🤔 I'm not quite sure I understood correctly. Could you please rephrase your request more clearly? For example: 'Book hall next Friday at 3pm for team meeting'"
                })

            # Get bookings array from AI response
            bookings_data = ai_data.get("bookings", [])
            if not bookings_data:
                # Fallback to old format for backward compatibility
                bookings_data = [ai_data]
                
            # Process each booking
            processed_bookings = []
            user_name, user_phone = get_user_defaults(request)
            
            for booking_data in bookings_data:
                # ✅ Smart default values with user-friendly messaging
                booking_data["name"] = booking_data.get("name") or user_name
                booking_data["phone"] = booking_data.get("phone") or user_phone
                
                # Enhance description with more intelligent defaults
                if not booking_data.get("description") or booking_data["description"] == "null":
                    booking_data["description"] = "general booking"
                else:
                    # Keep the detailed description from AI, don't oversimplify
                    booking_data["description"] = booking_data["description"].strip()

                # ✅ For modifications, date is optional (we can find by description/recent)
                # For new bookings, date and time are mandatory
                if not is_modification:
                    if not booking_data.get("date") or booking_data["date"] == "null":
                        return JsonResponse({"status": "error", "message": "❌ Could not determine the date. Please specify when you'd like to book (e.g., 'tomorrow', 'next Friday', or a specific date)."})

                if not booking_data.get("time") or booking_data["time"] == "null":
                    if is_modification:
                        return JsonResponse({"status": "error", "message": "❌ Could not determine the new time. Please specify what time you want to change it to (e.g., '3pm', '15:00', 'evening', or 'same time')."})
                    else:
                        return JsonResponse({"status": "error", "message": "❌ Could not determine the time. Please specify what time you need (e.g., 'morning', 'evening', '2pm', or '14:00')."})

                # Validate phone
                if not validate_phone(booking_data["phone"]):
                    return JsonResponse({"status": "error", "message": "❌ Invalid phone number"})

                # Check for cancellation keywords
                if any(word in booking_data["description"].lower() for word in ["cancel", "delete", "remove"]):
                    return JsonResponse({"status": "error", "message": "❌ Detected cancellation intent. Use cancel endpoint."})
                
                processed_bookings.append(booking_data)
            
            # If multiple bookings, process them all
            if len(processed_bookings) > 1:
                return process_multiple_bookings(request, processed_bookings, is_modification)
            
            # Single booking - use existing logic
            ai_data = processed_bookings[0]

            # For modifications without date, we need to find the booking first
            if is_modification and (not ai_data.get("date") or ai_data["date"] == "null"):
                # Handle modification without specific date - find booking and use new time
                user_name, user_phone = get_user_defaults(request)
                
                # Search for booking by description or get most recent
                existing = None
                
                # Extract description clues from the original query
                query_words = query.lower().split()
                event_keywords = ["birthday", "meeting", "party", "wedding", "conference", "workshop", "training", "seminar", "celebration", "bash", "event"]
                description_keywords = [word for word in query_words if word in event_keywords]
                
                # Try to find by description keywords
                if description_keywords:
                    for keyword in description_keywords:
                        existing = Booking.objects.filter(
                            Q(user=request.user) | Q(phone=user_phone),
                            description__icontains=keyword,
                            is_cancelled=False
                        ).order_by("-booking_datetime").first()
                        if existing:
                            break
                
                # If not found and only one booking exists, use it
                if not existing:
                    all_bookings = Booking.objects.filter(
                        Q(user=request.user) | Q(phone=user_phone),
                        is_cancelled=False
                    ).order_by("-booking_datetime")
                    
                    if all_bookings.count() == 1:
                        existing = all_bookings.first()
                    elif all_bookings.count() > 1:
                        # Show bookings and ask for clarification
                        booking_list = []
                        for i, booking in enumerate(all_bookings[:5], 1):
                            booking_list.append(f"{i}. {booking.booking_datetime.strftime('%d/%m/%Y %H:%M')} - {booking.description}")
                        
                        return JsonResponse({
                            "status": "error",
                            "message": f"❌ You have multiple bookings. Please be more specific:\n\n" + 
                                      "\n".join(booking_list) + 
                                      "\n\nExample: 'modify my birthday booking to 3pm' or 'modify my booking on 8/07/2025 to 3pm'"
                        })
                    else:
                        return JsonResponse({"status": "error", "message": "❌ No bookings found to modify."})
                
                if existing:
                    # Use the existing booking's date with the new time
                    new_time = datetime.strptime(ai_data['time'], "%H:%M").time()
                    booking_datetime = timezone.make_aware(
                        datetime.combine(existing.booking_datetime.date(), new_time)
                    )
                    ai_data['date'] = existing.booking_datetime.date().strftime("%Y-%m-%d")
                else:
                    return JsonResponse({"status": "error", "message": "❌ Could not find the booking to modify."})
            else:
                # Check if it's a "same time" modification for a specific date
                if is_modification and ai_data.get('time') == 'same':
                    # Find the existing booking on the original date
                    user_name, user_phone = get_user_defaults(request)
                    date_match = re.search(r'(\d{1,2})[/?](\d{1,2})[/?](\d{4})', query)
                    
                    if date_match:
                        try:
                            original_date = datetime.strptime(f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}", "%d/%m/%Y").date()
                            existing_booking = Booking.objects.filter(
                                Q(user=request.user) | Q(phone=user_phone),
                                booking_datetime__date=original_date,
                                is_cancelled=False
                            ).first()
                            
                            if existing_booking:
                                # Use the existing booking's time
                                ai_data['time'] = existing_booking.booking_datetime.strftime("%H:%M")
                            else:
                                return JsonResponse({"status": "error", "message": f"❌ No booking found on {date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)} to get the time from."})
                        except ValueError:
                            return JsonResponse({"status": "error", "message": "❌ Invalid date format in your request."})
                    else:
                        return JsonResponse({"status": "error", "message": "❌ To use 'same time', please specify the original date (e.g., 'modify my booking on 8/07/2025 to 9/07/2025 same time')."})
                
                # Parse datetime normally
                booking_datetime = timezone.make_aware(
                    datetime.strptime(f"{ai_data['date']} {ai_data['time']}", "%Y-%m-%d %H:%M")
                )

            if not validate_future_datetime(booking_datetime):
                current_time = timezone.now()
                if booking_datetime.date() == current_time.date():
                    return JsonResponse({"status": "error", "message": f"❌ I can't book past times. It's currently {current_time.strftime('%H:%M')}, so please choose a time after that for today."})
                else:
                    return JsonResponse({"status": "error", "message": "❌ I can't book dates in the past. Please choose a future date."})

            if Booking.objects.filter(
                booking_datetime__date=booking_datetime.date(),
                booking_datetime__time=booking_datetime.time(),
                is_cancelled=False
            ).exists():
                # Find available slots on the same day
                booked_times = Booking.objects.filter(
                    booking_datetime__date=booking_datetime.date(),
                    is_cancelled=False
                ).values_list('booking_datetime__time', flat=True)
                
                # Generate available time slots (9 AM to 8 PM)
                available_slots = []
                current_datetime = timezone.now()
                
                for hour in range(9, 21):  # 9 AM to 8 PM
                    for minute in [0, 30]:  # Every 30 minutes
                        slot_datetime = timezone.make_aware(
                            datetime.combine(booking_datetime.date(), datetime.min.time().replace(hour=hour, minute=minute))
                        )
                        # Check if slot is not booked AND is in the future
                        if slot_datetime.time() not in booked_times and slot_datetime > current_datetime:
                            available_slots.append(f"{hour:02d}:{minute:02d}")
                
                available_msg = ""
                if available_slots:
                    available_msg = f"\n\n✅ Available slots on {booking_datetime.date().strftime('%d/%m/%Y')}:\n" + ", ".join(available_slots[:8])
                    if len(available_slots) > 8:
                        available_msg += f" (and {len(available_slots) - 8} more)"
                
                return JsonResponse({
                    "status": "error", 
                    "message": f"❌ The {booking_datetime.time().strftime('%H:%M')} slot on {booking_datetime.date().strftime('%d/%m/%Y')} is already taken.{available_msg}\n\nTry: 'Book {booking_datetime.date().strftime('%d/%m/%Y')} at [available time]'"
                })

            # Create booking
            if is_modification:
                # Try to find the booking to modify (only user's bookings)
                user_name, user_phone = get_user_defaults(request)
                
                # First, try to find booking by the original date mentioned in the query
                # Extract original date from query if mentioned (handle typos like ? instead of /)
                date_match = re.search(r'(\d{1,2})[/?](\d{1,2})[/?](\d{4})', query)
                
                if date_match:
                    # User specified a date - find booking on that specific date
                    try:
                        original_date = datetime.strptime(f"{date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}", "%d/%m/%Y").date()
                        bookings_on_date = Booking.objects.filter(
                            Q(user=request.user) | Q(phone=user_phone),
                            booking_datetime__date=original_date,
                            is_cancelled=False
                        )
                        
                        if bookings_on_date.count() == 1:
                            existing = bookings_on_date.first()
                        elif bookings_on_date.count() > 1:
                            # Multiple bookings on that date - show them and ask for clarification
                            booking_times = [f"{b.booking_datetime.strftime('%H:%M')} ({b.description})" for b in bookings_on_date]
                            return JsonResponse({
                                "status": "error", 
                                "message": f"❌ Found multiple bookings on {date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)}:\n" + 
                                          "\n".join([f"• {time}" for time in booking_times]) + 
                                          "\n\nPlease specify which one you want to modify (e.g., 'modify my 10:00 meeting on 8/07/2025 to 7pm')"
                            })
                        else:
                            existing = None
                    except ValueError:
                        existing = None
                else:
                    # No specific date mentioned - search by description in the original query
                    description_keywords = []
                    
                    # Extract description clues from the original query
                    query_words = query.lower().split()
                    event_keywords = ["birthday", "meeting", "party", "wedding", "conference", "workshop", "training", "seminar", "celebration", "bash", "event"]
                    for word in query_words:
                        if word in event_keywords:
                            description_keywords.append(word)
                    
                    # Try to find booking by description keywords from query
                    if description_keywords:
                        for keyword in description_keywords:
                            existing = Booking.objects.filter(
                                Q(user=request.user) | Q(phone=user_phone),
                                description__icontains=keyword,
                                is_cancelled=False
                            ).order_by("-booking_datetime").first()
                            if existing:
                                break
                    
                    # If no description match, try by AI extracted description
                    if not existing and ai_data.get("description"):
                        existing = Booking.objects.filter(
                            Q(user=request.user) | Q(phone=user_phone),
                            description__icontains=ai_data["description"],
                            is_cancelled=False
                        ).order_by("-booking_datetime").first()
                    
                    # If still no match, get most recent booking
                    if not existing:
                        all_bookings = Booking.objects.filter(
                            Q(user=request.user) | Q(phone=user_phone),
                            is_cancelled=False
                        ).order_by("-booking_datetime")
                        
                        if all_bookings.count() == 1:
                            existing = all_bookings.first()
                        elif all_bookings.count() > 1:
                            # Show all bookings and ask for clarification
                            booking_list = []
                            for i, booking in enumerate(all_bookings[:5], 1):  # Show first 5
                                booking_list.append(f"{i}. {booking.booking_datetime.strftime('%d/%m/%Y %H:%M')} - {booking.description}")
                            
                            return JsonResponse({
                                "status": "error",
                                "message": f"❌ You have multiple bookings. Please specify which one to modify:\n\n" + 
                                          "\n".join(booking_list) + 
                                          "\n\nExample: 'modify my birthday booking to 3pm' or 'modify my booking on 8/07/2025 to 3pm'"
                            })
                        else:
                            existing = None

                if not existing:
                    if date_match:
                        return JsonResponse({"status": "error", "message": f"❌ I couldn't find any booking on {date_match.group(1)}/{date_match.group(2)}/{date_match.group(3)} to modify. Please check the date or create a new booking."})
                    else:
                        return JsonResponse({"status": "error", "message": "❌ I couldn't find an existing booking to modify. Please specify the date or description of the booking you want to change."})

                # Check if new time is already taken (excluding the booking being modified)
                if Booking.objects.filter(
                    booking_datetime__date=booking_datetime.date(),
                    booking_datetime__time=booking_datetime.time(),
                    is_cancelled=False
                ).exclude(id=existing.id).exists():
                    return JsonResponse({"status": "error", "message": "❌ That new time slot is already taken. Please choose a different time for your rescheduled booking."})

                # Update the booking
                old_datetime = existing.booking_datetime.strftime('%d/%m/%Y %H:%M')
                existing.booking_datetime = booking_datetime
                existing.save()

                return JsonResponse({
                    "status": "success",
                    "message": f"🎉 Perfect! I've successfully updated your booking from {old_datetime} to {ai_data['date']} at {ai_data['time']} for {existing.description}. See you then!",
                    "booking_id": existing.id
                })

            else:
                # Create new booking
                booking_data = {
                    "name": ai_data["name"],
                    "phone": ai_data["phone"],
                    "description": ai_data["description"],
                    "booking_datetime": booking_datetime
                }
                
                # Link to user if authenticated
                if request.user.is_authenticated:
                    booking_data["user"] = request.user
                    
                booking = Booking.objects.create(**booking_data)

                return JsonResponse({
                    "status": "success",
                    "message": f"🎉 Fantastic! Your hall is booked for {ai_data['date']} at {ai_data['time']} for {ai_data['description']}. Looking forward to your event!",
                    "booking_id": booking.id
                })

        except Exception as e:
            # Log the actual error for debugging
            import logging
            logging.error(f"Booking error: {str(e)}")
            # In development, show the actual error for debugging
            if hasattr(e, '__class__'):
                error_type = e.__class__.__name__
                return JsonResponse({"status": "error", "message": f"⚠️ Error ({error_type}): {str(e)}. Please try again or contact support."})
            else:
                return JsonResponse({"status": "error", "message": "⚠️ Something went wrong while processing your booking. Please try again or contact support."})

    return JsonResponse({"status": "error", "message": "❌ Please use POST method for requests."})

@csrf_exempt
@login_required
def ai_cancel_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            query = data.get("query", "")

            if not query.strip():
                return JsonResponse({"status": "error", "message": "❌ Please tell me which booking you'd like to cancel (e.g., 'cancel my booking tomorrow' or 'cancel Friday evening')."})

            # Handle common cancellation patterns directly (without Claude)
            query_lower = query.lower()
            direct_cancel_keywords = [
                # Original keywords
                "cancel my last booking", "cancel last booking", "cancel my recent booking", 
                "cancel recent booking", "cancel my latest booking", "cancel latest booking",
                "cancel my most recent", "cancel most recent", "cancel my booking",
                
                # Additional common phrases
                "cancel booking", "cancel it", "cancel the booking", "cancel reservation",
                "delete booking", "delete my booking", "remove booking", "remove my booking",
                "i want to cancel", "i need to cancel", "please cancel", "can i cancel",
                "want to cancel", "need to cancel", "like to cancel", "undo booking",
                "cancel that", "cancel this", "undo that", "undo this",
                
                # Informal phrases
                "dont need the booking", "dont want the booking", "no longer need",
                "cant make it", "wont be able to make it", "cancel everything",
                "cancel all", "cancel latest", "cancel newest"
            ]
            
            if any(keyword in query_lower for keyword in direct_cancel_keywords):
                user_name, user_phone = get_user_defaults(request)
                
                # Check if it's a "cancel all" request
                if any(phrase in query_lower for phrase in ["cancel all", "cancel everything", "cancel all my bookings", "cancel all bookings"]):
                    # Cancel ALL bookings for the user
                    try:
                        if request.user.is_authenticated:
                            all_bookings = Booking.objects.filter(
                                Q(user=request.user) | Q(phone=user_phone),
                                is_cancelled=False
                            )
                        else:
                            all_bookings = Booking.objects.filter(
                                phone=user_phone,
                                is_cancelled=False
                            )
                    except Exception as query_error:
                        # Fallback to phone-only search if Q query fails
                        all_bookings = Booking.objects.filter(
                            phone=user_phone,
                            is_cancelled=False
                        )
                    
                    if not all_bookings.exists():
                        return JsonResponse({"status": "error", "message": "❌ No active bookings found to cancel."})
                    
                    # Cancel all bookings
                    cancelled_count = all_bookings.count()
                    cancelled_bookings = []
                    
                    for booking in all_bookings:
                        cancelled_bookings.append({
                            "date": booking.booking_datetime.strftime('%d/%m/%Y'),
                            "time": booking.booking_datetime.strftime('%H:%M'),
                            "description": booking.description
                        })
                        booking.is_cancelled = True
                        booking.save()
                    
                    return JsonResponse({
                        "status": "success",
                        "message": f"✅ Perfect! I've successfully cancelled all {cancelled_count} of your active bookings. Hope to see you again soon!",
                        "cancelled_bookings": cancelled_bookings
                    })
                
                else:
                    # Cancel only the most recent booking
                    try:
                        if request.user.is_authenticated:
                            latest_booking = Booking.objects.filter(
                                Q(user=request.user) | Q(phone=user_phone),
                                is_cancelled=False
                            ).order_by("-created_at").first()
                        else:
                            latest_booking = Booking.objects.filter(
                                phone=user_phone,
                                is_cancelled=False
                            ).order_by("-created_at").first()
                    except Exception as query_error:
                        # Fallback to phone-only search if Q query fails
                        latest_booking = Booking.objects.filter(
                            phone=user_phone,
                            is_cancelled=False
                        ).order_by("-created_at").first()
                    
                    # If no booking found for the user, return error
                    if not latest_booking:
                        return JsonResponse({"status": "error", "message": "❌ No active bookings found to cancel."})
                    
                    # Cancel the booking
                    latest_booking.is_cancelled = True
                    latest_booking.save()
                    
                    return JsonResponse({
                        "status": "success",
                        "message": f"✅ Perfect! I've successfully cancelled your most recent booking on {latest_booking.booking_datetime.strftime('%d/%m/%Y')} at {latest_booking.booking_datetime.strftime('%H:%M')} for {latest_booking.description}. Hope to see you again soon!",
                        "cancelled_booking": {
                            "name": latest_booking.name,
                            "description": latest_booking.description,
                            "date": latest_booking.booking_datetime.strftime('%d/%m/%Y'),
                            "time": latest_booking.booking_datetime.strftime('%H:%M'),
                            "created_at": latest_booking.created_at.strftime('%d/%m/%Y %H:%M')
                        }
                    })

            # Enhanced cancellation prompt with better natural language understanding
            prompt = (
                "You are a friendly and intelligent booking cancellation assistant.\n"
                "Your job is to understand natural cancellation requests and extract booking details.\n\n"
                "CONTEXT:\n"
                f"- Today's date: {timezone.now().strftime('%A, %B %d, %Y (%Y-%m-%d)')}\n"
                f"- Current time: {timezone.now().strftime('%H:%M')}\n\n"
                "UNDERSTAND THESE NATURAL EXPRESSIONS:\n"
                "- 'Cancel my booking' = find most recent booking\n"
                "- 'Cancel my last booking' = find most recent booking\n"
                "- 'Cancel tomorrow' = cancel booking for tomorrow\n"
                "- 'Cancel my party booking' = find booking with 'party' in description\n"
                "- 'Cancel next Friday' = cancel booking for next Friday\n"
                "- Time references: 'morning', 'evening', 'afternoon', specific times\n\n"
                "EXTRACT AND RETURN ONLY A JSON OBJECT with these keys: date, time\n"
                "- Date format: YYYY-MM-DD\n"
                "- Time format: HH:MM (24-hour format)\n"
                "- For general cancellation requests without specific time, use null for time\n"
                "- Convert relative dates to absolute dates\n\n"
                "EXAMPLES:\n"
                "'Cancel my booking tomorrow' → {\"date\": \"2025-01-08\", \"time\": null}\n"
                "'Cancel Friday evening booking' → {\"date\": \"2025-01-10\", \"time\": \"18:00\"}\n\n"
                "**IMPORTANT: Output ONLY the JSON object. No explanations.**\n\n"
                f"Cancellation Request: \"{query}\""
            )

            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=512,
                    temperature=0.2,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                ai_response = response.content[0].text.strip()
                ai_data = json.loads(ai_response)
                
            except anthropic.APIError as e:
                return JsonResponse({"status": "error", "message": "❌ I'm having trouble processing your request right now. Please try again in a moment."})
            except json.JSONDecodeError:
                return JsonResponse({"status": "error", "message": "❌ I couldn't understand which booking to cancel. Please be more specific (e.g., 'cancel tomorrow at 3pm')."})

            # Validate extracted data (allow null time for general cancellations)
            if not ai_data.get("date"):
                return JsonResponse({"status": "error", "message": "❌ I need more details about which booking to cancel. Please specify the date."})

            # Enhanced booking search logic
            try:
                # If time is specified, find exact match
                if ai_data.get("time") and ai_data["time"] != "null":
                    booking_datetime = datetime.strptime(f"{ai_data['date']} {ai_data['time']}", "%Y-%m-%d %H:%M")
                    booking_datetime = timezone.make_aware(booking_datetime)
                    
                    user_name, user_phone = get_user_defaults(request)
                    booking = Booking.objects.get(
                        Q(user=request.user) | Q(phone=user_phone),
                        booking_datetime__date=booking_datetime.date(),
                        booking_datetime__time=booking_datetime.time(),
                        is_cancelled=False
                    )
                else:
                    # If no time specified, find any booking on that date
                    booking_date = datetime.strptime(ai_data['date'], "%Y-%m-%d").date()
                    user_name, user_phone = get_user_defaults(request)
                    bookings_on_date = Booking.objects.filter(
                        Q(user=request.user) | Q(phone=user_phone),
                        booking_datetime__date=booking_date,
                        is_cancelled=False
                    ).order_by('booking_datetime')
                    
                    if not bookings_on_date.exists():
                        return JsonResponse({"status": "error", "message": f"❌ No active bookings found on {ai_data['date']}. Please check the date and try again."})
                    elif bookings_on_date.count() == 1:
                        booking = bookings_on_date.first()
                    else:
                        # Multiple bookings on that date, ask for clarification
                        booking_times = [b.booking_datetime.strftime('%H:%M') for b in bookings_on_date]
                        return JsonResponse({
                            "status": "error", 
                            "message": f"❌ Found multiple bookings on {ai_data['date']} at times: {', '.join(booking_times)}. Please specify which time to cancel."
                        })
                        
            except ValueError:
                return JsonResponse({"status": "error", "message": "❌ The date or time format seems incorrect. Please try again with a clear date and time."})
            except Booking.DoesNotExist:
                return JsonResponse({"status": "error", "message": f"❌ No active booking found on {ai_data['date']} at the specified time. Please check your booking details."})

            # If we get here, booking was found successfully
            booking.is_cancelled = True
            booking.save()

            booking_time = booking.booking_datetime.strftime('%H:%M')
            return JsonResponse({
                "status": "success", 
                "message": f"✅ Perfect! I've successfully cancelled your booking on {ai_data['date']} at {booking_time} for {booking.description}. Hope to see you again soon!",
                "cancelled_booking": {
                    "name": booking.name,
                    "description": booking.description,
                    "date": ai_data['date'],
                    "time": booking_time
                }
            })

        except Exception as e:
            # Log the actual error for debugging
            import logging
            logging.error(f"Cancellation error: {str(e)}")
            # In development, show the actual error for debugging
            if hasattr(e, '__class__'):
                error_type = e.__class__.__name__
                return JsonResponse({"status": "error", "message": f"⚠️ Cancellation Error ({error_type}): {str(e)}. Please try again or contact support."})
            else:
                return JsonResponse({"status": "error", "message": "⚠️ Something went wrong while processing your cancellation. Please try again or contact support."})

    return JsonResponse({"status": "error", "message": "❌ Please use POST method for requests."})

@csrf_exempt
@login_required
def edit_booking(request):
    """Edit existing booking"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            booking_id = data.get("booking_id")
            
            if not booking_id:
                return JsonResponse({"error": "❌ Booking ID required"}, status=400)
            
            try:
                user_name, user_phone = get_user_defaults(request)
                booking = Booking.objects.get(
                    Q(user=request.user) | Q(phone=user_phone),
                    id=booking_id, 
                    is_cancelled=False
                )
            except Booking.DoesNotExist:
                return JsonResponse({"error": "❌ Booking not found or you don't have permission to edit it"}, status=404)
            
            # Update fields if provided
            if "name" in data:
                booking.name = data["name"].strip()
            if "phone" in data:
                phone = data["phone"].strip()
                if not validate_phone(phone):
                    return JsonResponse({"error": "❌ Invalid phone number format"}, status=400)
                booking.phone = phone
            if "description" in data:
                booking.description = data["description"].strip()
            if "datetime" in data:
                try:
                    new_datetime = datetime.strptime(data["datetime"], "%d/%m/%Y %H:%M")
                    new_datetime = timezone.make_aware(new_datetime)
                    
                    if not validate_future_datetime(new_datetime):
                        return JsonResponse({"error": "❌ Booking must be for a future date and time"}, status=400)
                    
                    # Check for conflicts (excluding current booking)
                    if Booking.objects.filter(
                        booking_datetime__date=new_datetime.date(),
                        booking_datetime__time=new_datetime.time(),
                        is_cancelled=False
                    ).exclude(id=booking_id).exists():
                        return JsonResponse({"error": "❌ Time slot already booked"}, status=400)
                    
                    booking.booking_datetime = new_datetime
                except ValueError:
                    return JsonResponse({"error": "❌ Invalid date format"}, status=400)
            
            booking.save()
            return JsonResponse({"message": "✅ Booking updated successfully!"})
            
        except Exception as e:
            return JsonResponse({"error": f"❌ Server error: {str(e)}"}, status=500)
    
    return JsonResponse({"error": "Only POST method allowed"}, status=405)

def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create UserProfile
            UserProfile.objects.create(
                user=user,
                phone=form.cleaned_data.get('phone')
            )
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            login(request, user)
            messages.success(request, 'Account created successfully!')
            return redirect('booking_ui')
    else:
        form = SignUpForm()
    return render(request, 'signup.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, 'Login successful!')
                return redirect('booking_ui')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')