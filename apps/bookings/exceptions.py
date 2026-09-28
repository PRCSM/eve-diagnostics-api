from apps.common.exceptions import ConflictError, NotFoundError


class BookingNotFound(NotFoundError):
    code = "BOOKING_NOT_FOUND"
    default_message = "Booking not found."


class DuplicateBooking(ConflictError):
    code = "DUPLICATE_BOOKING"
    default_message = "You already have an active booking for this test, centre and time."


class BookingNotCancellable(ConflictError):
    code = "BOOKING_NOT_CANCELLABLE"
    default_message = "Only pending bookings can be cancelled."


class BookingNotPayable(ConflictError):
    code = "BOOKING_NOT_PAYABLE"
    default_message = "This booking cannot accept a payment."


class InvalidBookingTransition(ConflictError):
    code = "BOOKING_INVALID_TRANSITION"
    default_message = "This booking status change is not allowed."
