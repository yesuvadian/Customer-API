# Notification Worker Deployment Guide

## Overview

The notification worker is a separate process that handles notification delivery asynchronously, independent from the main FastAPI application.

## Prerequisites

- Python 3.9+ with virtualenv
- PostgreSQL database
- systemd (Linux) or equivalent service manager
- User account for running the service (recommended: `cogniwatt`)

## Installation Steps

### 1. Run Database Migration

```bash
cd /opt/cogniwatt/Customer-API

# Connect to PostgreSQL
psql -U postgres -d your_database

# Run migration
\i migrations/014_add_notification_events_table.sql

# Verify table created
\d notification_events
```

### 2. Install Systemd Service

```bash
# Copy service file
sudo cp deployment/cogniwatt-notification-worker.service /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable cogniwatt-notification-worker

# Start service
sudo systemctl start cogniwatt-notification-worker

# Check status
sudo systemctl status cogniwatt-notification-worker
```

### 3. Verify Worker is Running

```bash
# Check logs
sudo journalctl -u cogniwatt-notification-worker -f

# You should see output like:
# Notification Worker started
# Database: ...
# Poll interval: 5s
# Batch size: 10
```

### 4. Test Event Processing

```bash
# In Python shell or script
from services.notification_event_emitter import emit_notification_event
from database import get_db

db = next(get_db())

emit_notification_event(
    db=db,
    organization_id="your-org-uuid",
    event_type="test_submitted",
    payload={"test": "data"},
)

# Check worker logs - you should see:
# Processing event... 
# ✓ Successfully processed event...
```

## Configuration

### Environment Variables

Edit `.env` file or override in systemd service:

```bash
# Database connection
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Worker settings
POLL_INTERVAL=5        # Polling interval in seconds (default: 5)
BATCH_SIZE=10          # Events per batch (default: 10)
LOG_LEVEL=INFO         # Logging level (DEBUG, INFO, WARNING, ERROR)
```

### Systemd Overrides

To override settings without editing the service file:

```bash
sudo systemctl edit cogniwatt-notification-worker
```

Add:
```ini
[Service]
Environment="POLL_INTERVAL=10"
Environment="BATCH_SIZE=20"
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart cogniwatt-notification-worker
```

## Monitoring

### Check Status

```bash
# Service status
sudo systemctl status cogniwatt-notification-worker

# Live logs
sudo journalctl -u cogniwatt-notification-worker -f

# Logs since boot
sudo journalctl -u cogniwatt-notification-worker -b

# Last 100 lines
sudo journalctl -u cogniwatt-notification-worker -n 100
```

### Check Database Stats

```sql
-- Pending events
SELECT COUNT(*) FROM notification_events WHERE status = 'pending';

-- Failed events
SELECT COUNT(*) FROM notification_events WHERE status = 'failed';

-- Processing rate (last hour)
SELECT 
    COUNT(*) as total_sent,
    AVG(EXTRACT(EPOCH FROM (processed_at - created_at))) as avg_seconds
FROM notification_events
WHERE status = 'sent' 
  AND processed_at > NOW() - INTERVAL '1 hour';

-- Events by status
SELECT status, COUNT(*) 
FROM notification_events 
GROUP BY status;

-- Recent failures
SELECT id, event_type, attempts, last_error, created_at
FROM notification_events
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 10;
```

## Management Commands

### Start/Stop/Restart

```bash
# Start
sudo systemctl start cogniwatt-notification-worker

# Stop
sudo systemctl stop cogniwatt-notification-worker

# Restart
sudo systemctl restart cogniwatt-notification-worker

# Reload configuration
sudo systemctl daemon-reload
sudo systemctl restart cogniwatt-notification-worker
```

### Enable/Disable Auto-start

```bash
# Enable (start on boot)
sudo systemctl enable cogniwatt-notification-worker

# Disable
sudo systemctl disable cogniwatt-notification-worker
```

## Scaling

### Run Multiple Workers

To process notifications faster, run multiple worker instances:

```bash
# Create additional service instances
sudo cp /etc/systemd/system/cogniwatt-notification-worker.service \
       /etc/systemd/system/cogniwatt-notification-worker@.service

# Edit the service file to add instance identifier
# ExecStart=/opt/cogniwatt/venv/bin/python notification_worker.py --instance %i

# Start multiple instances
sudo systemctl start cogniwatt-notification-worker@1
sudo systemctl start cogniwatt-notification-worker@2
sudo systemctl start cogniwatt-notification-worker@3

# Check all instances
sudo systemctl status 'cogniwatt-notification-worker*'
```

The workers use `SKIP LOCKED` in SQL queries, so multiple instances won't process the same event.

## Troubleshooting

### Worker Won't Start

1. Check database connection:
   ```bash
   psql $DATABASE_URL -c "SELECT 1"
   ```

2. Check Python environment:
   ```bash
   /opt/cogniwatt/venv/bin/python -c "import models; print('OK')"
   ```

3. Check permissions:
   ```bash
   ls -la /opt/cogniwatt/Customer-API/notification_worker.py
   # Should be readable by cogniwatt user
   ```

4. Check logs for errors:
   ```bash
   sudo journalctl -u cogniwatt-notification-worker -n 50
   ```

### Events Not Processing

1. Check worker is running:
   ```bash
   sudo systemctl status cogniwatt-notification-worker
   ```

2. Check for pending events:
   ```sql
   SELECT * FROM notification_events WHERE status = 'pending' LIMIT 5;
   ```

3. Check for errors in event processing:
   ```sql
   SELECT * FROM notification_events WHERE status = 'failed' ORDER BY created_at DESC LIMIT 5;
   ```

4. Manually retry a failed event:
   ```sql
   UPDATE notification_events 
   SET status = 'pending', attempts = 0, last_error = NULL 
   WHERE id = 'event-uuid-here';
   ```

### High CPU/Memory Usage

1. Reduce poll frequency:
   ```bash
   sudo systemctl edit cogniwatt-notification-worker
   # Set POLL_INTERVAL=10 or higher
   ```

2. Reduce batch size:
   ```bash
   sudo systemctl edit cogniwatt-notification-worker
   # Set BATCH_SIZE=5
   ```

3. Check for stuck events:
   ```sql
   SELECT * FROM notification_events 
   WHERE status = 'processing' 
     AND created_at < NOW() - INTERVAL '1 hour';
   ```

## Cleanup

### Archive Old Events

```sql
-- Archive sent events older than 30 days
INSERT INTO notification_events_archive
SELECT * FROM notification_events
WHERE status = 'sent' AND processed_at < NOW() - INTERVAL '30 days';

DELETE FROM notification_events
WHERE status = 'sent' AND processed_at < NOW() - INTERVAL '30 days';
```

Or create a cron job:

```bash
# Add to crontab
0 2 * * * psql $DATABASE_URL -c "DELETE FROM notification_events WHERE status = 'sent' AND processed_at < NOW() - INTERVAL '30 days';"
```

## Uninstallation

```bash
# Stop and disable service
sudo systemctl stop cogniwatt-notification-worker
sudo systemctl disable cogniwatt-notification-worker

# Remove service file
sudo rm /etc/systemd/system/cogniwatt-notification-worker.service

# Reload systemd
sudo systemctl daemon-reload

# Drop table (CAUTION: This deletes all notification history)
psql -U postgres -d your_database -c "DROP TABLE notification_events;"
```
