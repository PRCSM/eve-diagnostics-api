import itertools

import pytest

from apps.bookings import state
from apps.bookings.exceptions import InvalidBookingTransition
from apps.bookings.models import BookingStatus

ALLOWED = {
    (BookingStatus.PENDING, BookingStatus.CONFIRMED),
    (BookingStatus.PENDING, BookingStatus.FAILED),
    (BookingStatus.PENDING, BookingStatus.CANCELLED),
}


@pytest.mark.parametrize(
    "current, target", list(itertools.product(BookingStatus.values, BookingStatus.values))
)
def test_transition_table(current, target):
    expected = (current, target) in ALLOWED
    assert state.can_transition(current, target) is expected
    if expected:
        state.assert_transition(current, target)
    else:
        with pytest.raises(InvalidBookingTransition):
            state.assert_transition(current, target)
