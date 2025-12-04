from datetime import datetime

def format_date(dt_object=None):
    """Formats a datetime object into 'Www, DDth Mmm, YYYY at hh:mmam/pm'."""
    if dt_object is None:
        dt_object = datetime.now()

    day = dt_object.day
    if 4 <= day <= 20 or 24 <= day <= 30:
        suffix = "th"
    else:
        suffix = ["st", "nd", "rd"][day % 10 - 1]

    return dt_object.strftime(f"%a, {day}{suffix} %b, %Y at %I:%M%p").lower()
