"""sessions.purge: delete expired portal sessions and abandoned pending logins."""

from portal import auth
from portal.jobs import job_handler


@job_handler("sessions.purge")
def purge(db, job) -> None:
    auth.purge_expired_sessions(db)
