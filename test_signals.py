import pytest
from datetime import datetime, timedelta, timezone
import db

def test_signals():
    now = datetime.now(timezone.utc)
    
    # Waiting signal: applied > 7 days ago
    job_waiting = {
        "application_status": "applied",
        "application_updated_at": (now - timedelta(days=8)).isoformat(),
        "deadline_at": (now + timedelta(days=10)).isoformat(),
        "last_verified_at": (now - timedelta(days=5)).isoformat(),
        "effective_listing_status": "active"
    }
    assert db.compute_waiting_signal(job_waiting, now) is True
    
    # Not waiting: applied < 7 days ago
    job_not_waiting = job_waiting.copy()
    job_not_waiting["application_updated_at"] = (now - timedelta(days=6)).isoformat()
    assert db.compute_waiting_signal(job_not_waiting, now) is False

    # Expiring signal: deadline within 7 days
    job_expiring = {
        "deadline_at": (now + timedelta(days=5)).isoformat(),
    }
    assert db.compute_expiring_signal(job_expiring, now) is True
    
    # Not expiring: deadline > 7 days
    job_not_expiring = {
        "deadline_at": (now + timedelta(days=8)).isoformat(),
    }
    assert db.compute_expiring_signal(job_not_expiring, now) is False

    # Stale signal: verified > 14 days ago
    job_stale = {
        "last_verified_at": (now - timedelta(days=15)).isoformat(),
    }
    assert db.compute_stale_signal(job_stale, now) is True
    
    # Not stale: verified < 14 days ago
    job_not_stale = {
        "last_verified_at": (now - timedelta(days=13)).isoformat(),
    }
    assert db.compute_stale_signal(job_not_stale, now) is False

    # Archive candidate: closed/expired AND not_reviewed
    job_archive = {
        "effective_listing_status": "closed",
        "application_status": "not_reviewed",
    }
    assert db.compute_archive_candidate_signal(job_archive) is True
    
    # Not archive: closed BUT applied
    job_not_archive = {
        "effective_listing_status": "closed",
        "application_status": "applied",
    }
    assert db.compute_archive_candidate_signal(job_not_archive) is False
