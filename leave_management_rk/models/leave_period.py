from dateutil.relativedelta import relativedelta

from odoo import fields

# A "leave month" does not follow the calendar month. It runs from the 26th of
# one calendar month to the 25th of the next, and it is *named* after the month
# it ends in: 26 Aug -> 25 Sep is the "September" leave month.
#
# Every leave.balance row stays anchored on the 1st of the month it is named
# after (2026-09-01 for the 26 Aug -> 25 Sep period), so rows written before
# this cycle existed keep their meaning and the (user, leave type, date)
# uniqueness constraint is untouched. Only the date -> period mapping changed.
LEAVE_MONTH_START_DAY = 26
LEAVE_MONTH_END_DAY = 25


def leave_month_anchor(any_date):
    """Anchor date of the leave month that ``any_date`` falls in.

    25 Aug 2026 -> 2026-08-01 (August leave month)
    26 Aug 2026 -> 2026-09-01 (September leave month)
    """
    day = fields.Date.to_date(any_date)
    if day.day >= LEAVE_MONTH_START_DAY:
        day += relativedelta(months=1)
    return day.replace(day=1)


def leave_month_bounds(anchor):
    """(first day, last day) of the leave month anchored on ``anchor``."""
    anchor = fields.Date.to_date(anchor).replace(day=1)
    start = (anchor - relativedelta(months=1)).replace(day=LEAVE_MONTH_START_DAY)
    end = anchor.replace(day=LEAVE_MONTH_END_DAY)
    return start, end


def shift_leave_month(anchor, months=1):
    """Anchor of the leave month ``months`` periods after ``anchor``."""
    return fields.Date.to_date(anchor).replace(day=1) + relativedelta(months=months)


def current_leave_month_bounds(today=None):
    """(first day, last day) of the leave month currently in progress."""
    return leave_month_bounds(leave_month_anchor(today or fields.Date.today()))


def leave_month_label(anchor):
    """'September 2026 (26 Aug - 25 Sep)' - how a period is named in the UI."""
    anchor = fields.Date.to_date(anchor).replace(day=1)
    start, end = leave_month_bounds(anchor)
    return '%s (%s - %s)' % (
        anchor.strftime('%B %Y'),
        start.strftime('%d %b'),
        end.strftime('%d %b'),
    )
